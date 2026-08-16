"""Small operator CLI that never acquires Guardian mutation authority."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import stat
import sys
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

import psycopg
import uvicorn

from melloa.adapters.guardian.file import FileGuardianStatusReader
from melloa.adapters.models.codex_cli import load_codex_cli_route_config
from melloa.adapters.models.openai_compatible import load_openai_compatible_route_config
from melloa.adapters.postgres.migrations import (
    apply_migrations,
    discover_migrations,
    migration_status,
)
from melloa.adapters.telegram import TelegramBotApiConfig
from melloa.apps.core import create_app
from melloa.apps.mvp import build_mvp_runtime
from melloa.apps.postgres_mvp import (
    PostgresMvpBootstrapError,
    build_postgres_mvp_stores,
    validate_private_database_dsn,
)
from melloa.apps.synthetic import SYNTHETIC_TELEGRAM_ADAPTER_ID, build_synthetic_runtime

ROOT = Path(__file__).resolve().parents[3]


def _exit_error(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _private_bind_address(value: str) -> str:
    if value == "localhost":
        return value
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "bind address must be localhost or a literal IP"
        ) from error
    if address.is_unspecified or address.is_global or address.is_multicast:
        raise argparse.ArgumentTypeError("public or unspecified bind addresses are forbidden")
    tailscale_range = ipaddress.ip_network("100.64.0.0/10")
    is_tailscale = isinstance(address, ipaddress.IPv4Address) and address in tailscale_range
    if not (address.is_loopback or address.is_private or is_tailscale):
        raise argparse.ArgumentTypeError("bind address must be loopback or private")
    return value


def _read_secret_file(path: Path) -> str:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError:
        _exit_error("database DSN path must be a securely readable regular file")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            _exit_error("database DSN path must be a regular file")
        if metadata.st_mode & 0o077:
            _exit_error("database DSN file must not be accessible by group or others")
        raw_value = os.read(descriptor, 4097)
    except OSError:
        _exit_error("database DSN file could not be read securely")
    finally:
        os.close(descriptor)
    try:
        value = raw_value.decode("utf-8").strip()
    except UnicodeDecodeError:
        _exit_error("database DSN file must contain UTF-8 text")
    if not value or len(value) > 4096:
        _exit_error("database DSN file is empty or too large")
    return value


def _read_owner_credential_file(path: Path) -> str:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        _exit_error("owner credential path must be a regular file")
    if metadata.st_mode & 0o077:
        _exit_error("owner credential file must not be accessible by group or others")
    value = path.read_text(encoding="utf-8").strip()
    if not 32 <= len(value) <= 4096:
        _exit_error("owner credential file must contain between 32 and 4096 characters")
    return value


def _guardian_reader(args: argparse.Namespace) -> FileGuardianStatusReader:
    return FileGuardianStatusReader(args.guardian_status, args.guardian_public_key)


def doctor(_args: argparse.Namespace) -> int:
    checks = {
        "python_3_13_or_newer": sys.version_info >= (3, 13),
        "architecture_decisions_present": (ROOT / "docs/23-v0.2-decisions.md").is_file(),
        "migration_manifest_present": (ROOT / "migrations/manifest.json").is_file(),
        "event_schema_present": (ROOT / "schemas/events/event-envelope-v1.json").is_file(),
        "public_ingress_configured": False,
    }
    print(json.dumps({"checks": checks}, indent=2, sort_keys=True))
    required_checks_pass = all(
        value for key, value in checks.items() if key != "public_ingress_configured"
    )
    return 0 if required_checks_pass else 1


def guardian_status(args: argparse.Namespace) -> int:
    verified = _guardian_reader(args).read_status()
    print(verified.model_dump_json(indent=2))
    return 0


def serve(args: argparse.Namespace) -> int:
    app = create_app(_guardian_reader(args))
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)
    return 0


def serve_synthetic(args: argparse.Namespace) -> int:
    bootstrap_token = _read_owner_credential_file(args.owner_credential_file)
    runtime = build_synthetic_runtime(_guardian_reader(args), bootstrap_token)
    print(
        json.dumps(
            {
                "external_network_calls": False,
                "persistence": "process-only",
                "runtime": "synthetic-in-memory",
                "seed_assertion_id": runtime.seed_assertion_id,
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    uvicorn.run(runtime.app, host=args.host, port=args.port, access_log=False)
    return 0


def serve_mvp(args: argparse.Namespace) -> int:
    bootstrap_token = _read_owner_credential_file(args.owner_credential_file)
    with ExitStack() as resources:
        try:
            route_configs = tuple(
                load_openai_compatible_route_config(path) for path in args.model_route_config
            )
            cli_agent_route_configs = tuple(
                load_codex_cli_route_config(path)
                for path in getattr(args, "cli_agent_route_config", ())
            )
            telegram_config = None
            telegram_token_file = getattr(args, "telegram_bot_token_file", None)
            if telegram_token_file is not None:
                telegram_config = TelegramBotApiConfig(
                    token_file=telegram_token_file,
                    api_base_url=getattr(
                        args,
                        "telegram_api_base_url",
                        "https://api.telegram.org",
                    ),
                )
            durable_stores = None
            database_dsn_file = getattr(args, "database_dsn_file", None)
            if database_dsn_file is not None:
                dsn = validate_private_database_dsn(_read_secret_file(database_dsn_file))
                connections = tuple(
                    resources.enter_context(
                        psycopg.connect(
                            dsn,
                            autocommit=True,
                            connect_timeout=5,
                            application_name=f"melloa-mvp-{store_name}",
                            options=(
                                "-c statement_timeout=5000 -c lock_timeout=5000 "
                                "-c idle_in_transaction_session_timeout=10000"
                            ),
                        )
                    )
                    for store_name in ("conversation", "memory", "delivery", "telegram")
                )
                durable_stores = build_postgres_mvp_stores(
                    *connections,
                    telegram_adapter_id=(
                        SYNTHETIC_TELEGRAM_ADAPTER_ID
                        if telegram_config is None
                        else telegram_config.adapter_id
                    ),
                )
            if durable_stores is None:
                runtime = build_mvp_runtime(
                    _guardian_reader(args),
                    bootstrap_token,
                    route_configs,
                    telegram_config,
                    cli_agent_route_configs=cli_agent_route_configs,
                )
            else:
                runtime = build_mvp_runtime(
                    _guardian_reader(args),
                    bootstrap_token,
                    route_configs,
                    telegram_config,
                    cli_agent_route_configs=cli_agent_route_configs,
                    durable_stores=durable_stores,
                )
        except PostgresMvpBootstrapError:
            _exit_error(
                "MVP database bootstrap rejected incompatible canonical state; "
                "connection details were not logged"
            )
        except psycopg.Error:
            _exit_error(
                "MVP database unavailable or incompatible; connection details were not logged"
            )
        except (OSError, ValueError) as error:
            _exit_error(f"MVP configuration rejected: {error}")
        external_route_ids = {
            *(
                config.route_id
                for config in route_configs
                if config.processing_location.value == "approved_provider"
            ),
            *(config.route_id for config in cli_agent_route_configs),
        }
        print(
            json.dumps(
                {
                    "external_disclosure_routes": [
                        route_id
                        for route_id in runtime.model_route_ids
                        if route_id in external_route_ids
                    ],
                    "fallback_route_ids": runtime.model_route_ids,
                    "experimental_cli_agent": {
                        "approval_policy": "never",
                        "configured": bool(cli_agent_route_configs),
                        "external_disclosure": bool(cli_agent_route_configs),
                        "melloa_authority": "none",
                        "route_ids": [config.route_id for config in cli_agent_route_configs],
                        "sandbox": "read-only",
                        "session_persistence": "ephemeral",
                        "usage_metadata": "unreported",
                    },
                    "persistence": asdict(runtime.persistence),
                    "route_ids": runtime.model_route_ids,
                    "runtime": "owner-console-mvp-preview",
                    "seed_assertion_id": runtime.seed_assertion_id,
                    "synthetic_fallback": True,
                    "telegram": {
                        "adapter_id": (
                            None if telegram_config is None else telegram_config.adapter_id
                        ),
                        "attachments": "rejected-before-fetch",
                        "configured": telegram_config is not None,
                        "persistence": {
                            "delivery_records": (
                                "postgresql"
                                if runtime.persistence.mode == "postgresql-partial-preview"
                                else "process-only-preview"
                            ),
                            "pairing_offsets_ingestion": (
                                "postgresql"
                                if runtime.persistence.mode == "postgresql-partial-preview"
                                else "process-only-preview"
                            ),
                            "challenge_send_observation": "process-only-preview",
                            "attachment_quarantine_bytes": "not-stored",
                        },
                    },
                },
                indent=2,
                sort_keys=True,
            ),
            flush=True,
        )
        uvicorn.run(runtime.app, host=args.host, port=args.port, access_log=False)
    return 0


def migrate(args: argparse.Namespace) -> int:
    dsn = _read_secret_file(args.dsn_file)
    migrations = discover_migrations(ROOT / "migrations", ROOT / "migrations/manifest.json")
    with psycopg.connect(dsn, autocommit=True) as connection:
        status_result = (
            apply_migrations(connection, migrations)
            if args.migration_command == "apply"
            else migration_status(connection, migrations)
        )
    print(
        json.dumps(
            {"applied": status_result.applied, "pending": status_result.pending},
            indent=2,
        )
    )
    return 0 if args.migration_command == "apply" or not status_result.pending else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="melloa")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.set_defaults(handler=doctor)

    guardian_parser = subparsers.add_parser("guardian-status")
    guardian_parser.add_argument("--status", dest="guardian_status", type=Path, required=True)
    guardian_parser.add_argument(
        "--public-key",
        dest="guardian_public_key",
        type=Path,
        required=True,
    )
    guardian_parser.set_defaults(handler=guardian_status)

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--status", dest="guardian_status", type=Path, required=True)
    serve_parser.add_argument("--public-key", dest="guardian_public_key", type=Path, required=True)
    serve_parser.add_argument("--host", type=_private_bind_address, default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8080)
    serve_parser.set_defaults(handler=serve)

    synthetic_parser = subparsers.add_parser("serve-synthetic")
    synthetic_parser.add_argument(
        "--status",
        dest="guardian_status",
        type=Path,
        required=True,
    )
    synthetic_parser.add_argument(
        "--public-key",
        dest="guardian_public_key",
        type=Path,
        required=True,
    )
    synthetic_parser.add_argument(
        "--owner-credential-file",
        type=Path,
        default=Path(os.environ.get("MELLOA_OWNER_CREDENTIAL_FILE", "")),
        required="MELLOA_OWNER_CREDENTIAL_FILE" not in os.environ,
    )
    synthetic_parser.add_argument("--host", type=_private_bind_address, default="127.0.0.1")
    synthetic_parser.add_argument("--port", type=int, default=8000)
    synthetic_parser.set_defaults(handler=serve_synthetic)

    mvp_parser = subparsers.add_parser("serve-mvp")
    mvp_parser.add_argument(
        "--status",
        dest="guardian_status",
        type=Path,
        required=True,
    )
    mvp_parser.add_argument(
        "--public-key",
        dest="guardian_public_key",
        type=Path,
        required=True,
    )
    mvp_parser.add_argument(
        "--owner-credential-file",
        type=Path,
        default=Path(os.environ.get("MELLOA_OWNER_CREDENTIAL_FILE", "")),
        required="MELLOA_OWNER_CREDENTIAL_FILE" not in os.environ,
    )
    mvp_parser.add_argument(
        "--model-route-config",
        type=Path,
        action="append",
        default=[],
        help="Repeat for each OpenAI-compatible local or optional external route.",
    )
    mvp_parser.add_argument(
        "--cli-agent-route-config",
        type=Path,
        action="append",
        default=[],
        help="Repeat with each absolute private experimental Codex CLI route config path.",
    )
    database_dsn_path = os.environ.get("MELLOA_MVP_DATABASE_DSN_FILE")
    mvp_parser.add_argument(
        "--database-dsn-file",
        type=Path,
        default=None if database_dsn_path is None else Path(database_dsn_path),
        help=(
            "Optional mode-0600 core-role DSN file for partial PostgreSQL restart "
            "durability; migrations must already be applied."
        ),
    )
    telegram_token_path = os.environ.get("MELLOA_TELEGRAM_BOT_TOKEN_FILE")
    mvp_parser.add_argument(
        "--telegram-bot-token-file",
        type=Path,
        default=None if telegram_token_path is None else Path(telegram_token_path),
        help="Mode-0600 Telegram Bot API token file; omitted keeps Telegram synthetic.",
    )
    mvp_parser.add_argument(
        "--telegram-api-base-url",
        default=os.environ.get("MELLOA_TELEGRAM_API_BASE_URL", "https://api.telegram.org"),
        help="Canonical Telegram API origin or a private local Bot API endpoint.",
    )
    mvp_parser.add_argument("--host", type=_private_bind_address, default="127.0.0.1")
    mvp_parser.add_argument("--port", type=int, default=8000)
    mvp_parser.set_defaults(handler=serve_mvp)

    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.add_argument("migration_command", choices=("check", "apply"))
    migrate_parser.add_argument(
        "--dsn-file",
        type=Path,
        default=Path(os.environ.get("MELLOA_DATABASE_DSN_FILE", "")),
        required="MELLOA_DATABASE_DSN_FILE" not in os.environ,
    )
    migrate_parser.set_defaults(handler=migrate)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()
