"""Small operator CLI that never acquires Guardian mutation authority."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import stat
import sys
from pathlib import Path
from typing import NoReturn

import psycopg
import uvicorn

from melloa.adapters.guardian.file import FileGuardianStatusReader
from melloa.adapters.postgres.migrations import (
    apply_migrations,
    discover_migrations,
    migration_status,
)
from melloa.apps.core import create_app
from melloa.apps.synthetic import build_synthetic_runtime

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
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        _exit_error("database DSN path must be a regular file")
    if metadata.st_mode & 0o077:
        _exit_error("database DSN file must not be accessible by group or others")
    value = path.read_text(encoding="utf-8").strip()
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
