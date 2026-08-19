"""Small operator CLI that never acquires Guardian mutation authority."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import stat
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import NoReturn

import psycopg
import uvicorn
from psycopg.conninfo import conninfo_to_dict

from melloa.adapters.guardian.file import FileGuardianStatusReader, GuardianVerificationError
from melloa.adapters.models.openai_compatible import load_openai_compatible_model_config
from melloa.adapters.postgres.migrations import (
    apply_migrations,
    discover_migrations,
    migration_status,
)
from melloa.apps.core import AccessScope
from melloa.apps.runtime import build_runtime

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
    tailscale = ipaddress.ip_network("100.64.0.0/10")
    is_tailscale = isinstance(address, ipaddress.IPv4Address) and address in tailscale
    if (
        address.is_unspecified
        or address.is_global
        or address.is_multicast
        or not (address.is_loopback or address.is_private or is_tailscale)
    ):
        raise argparse.ArgumentTypeError("bind address must be loopback or private")
    return value


def _read_private_file(path: Path, *, label: str, minimum: int = 1) -> str:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError:
        _exit_error(f"{label} path must be a securely readable regular file")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            _exit_error(f"{label} file must be private and regular")
        raw_value = os.read(descriptor, 4097)
    except OSError:
        _exit_error(f"{label} file could not be read securely")
    finally:
        os.close(descriptor)
    try:
        value = raw_value.decode("utf-8").strip()
    except UnicodeDecodeError:
        _exit_error(f"{label} file must contain UTF-8 text")
    if not minimum <= len(value) <= 4096:
        _exit_error(f"{label} file has an invalid length")
    return value


def _read_secret_file(path: Path) -> str:
    return _read_private_file(path, label="database DSN")


def _read_owner_credential_file(path: Path) -> str:
    return _read_private_file(path, label="owner credential", minimum=32)


def _validate_private_database_dsn(dsn: str) -> str:
    parameters = conninfo_to_dict(dsn)
    if parameters.get("service"):
        raise ValueError("database service indirection is not supported")
    for field, allow_socket in (("host", True), ("hostaddr", False)):
        value = str(parameters.get(field, ""))
        if value:
            _validate_database_targets(value, allow_unix_socket=allow_socket)
    return dsn


def _validate_database_targets(value: str, *, allow_unix_socket: bool) -> None:
    tailscale = ipaddress.ip_network("100.64.0.0/10")
    for target in value.split(","):
        if allow_unix_socket and target.startswith("/"):
            continue
        if target == "localhost":
            continue
        try:
            address = ipaddress.ip_address(target)
        except ValueError as error:
            raise ValueError(
                "database host must be localhost, a Unix socket, or a private literal IP"
            ) from error
        is_tailscale = isinstance(address, ipaddress.IPv4Address) and address in tailscale
        if (
            address.is_unspecified
            or address.is_global
            or address.is_multicast
            or not (
                address.is_loopback
                or address.is_private
                or address.is_link_local
                or is_tailscale
            )
        ):
            raise ValueError("database target must remain on a private network")


def _guardian_reader(args: argparse.Namespace) -> FileGuardianStatusReader:
    return FileGuardianStatusReader(args.guardian_status, args.guardian_public_key)


def guardian_status(args: argparse.Namespace) -> int:
    try:
        verified = _guardian_reader(args).read_status()
    except GuardianVerificationError as error:
        _exit_error(f"Guardian status rejected: {error}")
    print(verified.model_dump_json(indent=2))
    return 0


def serve(args: argparse.Namespace) -> int:
    bootstrap_token = _read_owner_credential_file(args.owner_credential_file)
    with ExitStack() as resources:
        try:
            model_config = (
                None
                if args.model_config is None
                else load_openai_compatible_model_config(args.model_config)
            )
            connection = None
            if args.database_dsn_file is not None:
                dsn = _validate_private_database_dsn(
                    _read_secret_file(args.database_dsn_file)
                )
                connection = resources.enter_context(
                    psycopg.connect(
                        dsn,
                        autocommit=True,
                        connect_timeout=5,
                        application_name="melloa",
                        options=(
                            "-c statement_timeout=30000 -c lock_timeout=5000 "
                            "-c idle_in_transaction_session_timeout=10000"
                        ),
                    )
                )
            access_scope: AccessScope = (
                "loopback"
                if args.host == "localhost" or ipaddress.ip_address(args.host).is_loopback
                else "private-network"
            )
            runtime = build_runtime(
                _guardian_reader(args),
                bootstrap_token,
                model_config,
                database_connection=connection,
                access_scope=access_scope,
            )
        except psycopg.Error:
            _exit_error("Private database is unavailable or incompatible.")
        except (OSError, ValueError) as error:
            _exit_error(f"Melloa configuration rejected: {error}")
        print(
            json.dumps(
                {
                    "access_scope": access_scope,
                    "model_configured": model_config is not None,
                    "model_external_disclosure": (
                        False
                        if model_config is None
                        else model_config.processing_location.value == "approved_provider"
                    ),
                    "persistence": runtime.persistence,
                },
                indent=2,
                sort_keys=True,
            ),
            flush=True,
        )
        uvicorn.run(runtime.app, host=args.host, port=args.port, access_log=False)
    return 0


def migrate(args: argparse.Namespace) -> int:
    dsn = _validate_private_database_dsn(_read_secret_file(args.dsn_file))
    migrations = discover_migrations(ROOT / "migrations", ROOT / "migrations/manifest.json")
    with psycopg.connect(dsn, autocommit=True) as connection:
        result = (
            apply_migrations(connection, migrations)
            if args.migration_command == "apply"
            else migration_status(connection, migrations)
        )
    print(json.dumps({"applied": result.applied, "pending": result.pending}, indent=2))
    return 0 if args.migration_command == "apply" or not result.pending else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="melloa")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    serve_parser.add_argument(
        "--public-key",
        dest="guardian_public_key",
        type=Path,
        required=True,
    )
    serve_parser.add_argument(
        "--owner-credential-file",
        type=Path,
        default=Path(os.environ.get("MELLOA_OWNER_CREDENTIAL_FILE", "")),
        required="MELLOA_OWNER_CREDENTIAL_FILE" not in os.environ,
    )
    serve_parser.add_argument("--model-config", type=Path)
    database_path = os.environ.get("MELLOA_DATABASE_DSN_FILE")
    serve_parser.add_argument(
        "--database-dsn-file",
        type=Path,
        default=None if database_path is None else Path(database_path),
    )
    serve_parser.add_argument("--host", type=_private_bind_address, default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.set_defaults(handler=serve)

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
