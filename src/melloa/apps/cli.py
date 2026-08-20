"""Small operator CLI that never acquires Guardian mutation authority."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import stat
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any, NoReturn, Protocol

import psycopg
import uvicorn
from psycopg.conninfo import conninfo_to_dict
from pydantic import ValidationError

from melloa.adapters.coding import (
    CodexCliSourceChangePlanner,
    ExternalSandboxSelfChangeVerifier,
    GitSelfChangeReleaseExecutor,
    ServerReleaseDeployment,
)
from melloa.adapters.guardian.file import FileGuardianStatusReader, GuardianVerificationError
from melloa.adapters.models.openai_compatible import load_openai_compatible_model_config
from melloa.adapters.models.routed import ModelRouteConfigs
from melloa.adapters.postgres.migrations import (
    apply_migrations,
    discover_migrations,
    migration_status,
)
from melloa.adapters.postgres.self_change import PostgresSelfChangeStore
from melloa.adapters.telegram import TelegramOwnerConfig
from melloa.application.release_activation import ReleaseActivationGate
from melloa.application.self_change_applying import SelfChangeApplyingWorker
from melloa.application.self_change_planning import SelfChangePlanningWorker
from melloa.apps.core import AccessScope
from melloa.apps.deployment_check import (
    DeploymentCheckError,
    check_deployment_integrations,
)
from melloa.apps.runtime import build_runtime

ROOT = Path(__file__).resolve().parents[3]
_PLANNER_ENVIRONMENT = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
)
_RELEASE_ENVIRONMENT = (
    "DOCKER_CONFIG",
    "HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "MELLOA_POSTGRES_IMAGE",
    "MELLOA_PYTHON_IMAGE",
    "MELLOA_RELEASE_HEALTH_TIMEOUT_SECONDS",
    "MELLOA_RELEASE_POLL_SECONDS",
    "MELLOA_RESTIC_IMAGE",
    "MELLOA_UV_IMAGE",
    "NO_PROXY",
)
_MODEL_CREDENTIAL_ENVIRONMENT = ("CODEX_HOME", "OPENAI_API_KEY")
_CONTAINER_CONTROL_SOCKETS = (
    Path("/run/docker.sock"),
    Path("/var/run/docker.sock"),
    Path("/run/podman/podman.sock"),
)


class _ForeverWorker(Protocol):
    async def run_forever(self) -> None:
        """Run until the service supervisor stops the process."""


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


def _sha256_digest(value: str) -> str:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("expected a tagged SHA-256 digest")
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


def _read_telegram_owner_config(path: Path) -> TelegramOwnerConfig:
    document = _read_private_file(path, label="Telegram owner config")
    try:
        return TelegramOwnerConfig.model_validate_json(document, strict=True)
    except ValidationError:
        _exit_error("Telegram owner config is invalid")


def _read_telegram_bot_token(path: Path) -> str:
    return _read_private_file(path, label="Telegram bot token", minimum=37)


def _require_private_directory(path: Path, *, label: str, owner_uid: int) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise ValueError(f"{label} is unavailable") from error
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != owner_uid
        or metadata.st_mode & 0o077
    ):
        raise ValueError(f"{label} must be an owner-only directory for the coding agent")


def _reject_planner_container_authority() -> None:
    if os.environ.get("DOCKER_HOST"):
        raise ValueError("self-change planning must not receive container-control authority")
    for path in _CONTAINER_CONTROL_SOCKETS:
        try:
            metadata = path.stat(follow_symlinks=False)
        except (FileNotFoundError, PermissionError):
            continue
        except OSError as error:
            raise ValueError("container-control authority could not be verified") from error
        if stat.S_ISSOCK(metadata.st_mode) and os.access(path, os.R_OK | os.W_OK):
            raise ValueError("self-change planning must not access a container-control socket")


def _connect_self_change_database(
    dsn_file: Path,
    *,
    application_name: str,
    expected_role: str,
) -> psycopg.Connection[tuple[Any, ...]]:
    dsn = _validate_private_database_dsn(_read_secret_file(dsn_file))
    connection: psycopg.Connection[tuple[Any, ...]] = psycopg.connect(
        dsn,
        autocommit=True,
        connect_timeout=5,
        application_name=application_name,
        options=(
            "-c statement_timeout=30000 -c lock_timeout=5000 "
            "-c idle_in_transaction_session_timeout=10000"
        ),
    )
    try:
        row = connection.execute("SELECT current_user").fetchone()
    except Exception:
        connection.close()
        raise
    if row != (expected_role,):
        connection.close()
        raise ValueError("self-change database login has the wrong active role")
    return connection


def _run_worker(worker: _ForeverWorker) -> None:
    asyncio.run(worker.run_forever())


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
    return FileGuardianStatusReader(
        args.guardian_status,
        args.guardian_public_key,
        expected_initial_receipt_hash=getattr(
            args,
            "expected_guardian_receipt",
            None,
        ),
    )


def guardian_status(args: argparse.Namespace) -> int:
    try:
        verified = _guardian_reader(args).read_status()
    except GuardianVerificationError as error:
        _exit_error(f"Guardian status rejected: {error}")
    print(verified.model_dump_json(indent=2))
    return 0


def deployment_check(args: argparse.Namespace) -> int:
    try:
        result = check_deployment_integrations(
            guardian_status=args.guardian_status,
            guardian_public_key=args.guardian_public_key,
            capable_model_config=args.capable_model_config,
            economy_model_config=args.economy_model_config,
            telegram_owner_config=args.telegram_owner_config,
            telegram_bot_token_file=args.telegram_bot_token_file,
            model_credential_source_root=args.model_credential_source_root,
        )
    except DeploymentCheckError as error:
        _exit_error(f"Deployment activation check failed: {error}")
    print(json.dumps(result, indent=2, sort_keys=True))
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
            capable_model_path = getattr(args, "capable_model_config", None)
            economy_model_path = getattr(args, "economy_model_config", None)
            if (capable_model_path is None) != (economy_model_path is None):
                raise ValueError(
                    "capable and economy model config files must be supplied together"
                )
            if model_config is not None and capable_model_path is not None:
                raise ValueError(
                    "single-model and routed-model configuration cannot be combined"
                )
            model_routes = (
                None
                if capable_model_path is None or economy_model_path is None
                else ModelRouteConfigs(
                    capable=load_openai_compatible_model_config(capable_model_path),
                    economy=load_openai_compatible_model_config(economy_model_path),
                )
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
            telegram_config_path = getattr(args, "telegram_owner_config", None)
            telegram_token_path = getattr(args, "telegram_bot_token_file", None)
            if (telegram_config_path is None) != (telegram_token_path is None):
                raise ValueError(
                    "Telegram owner config and bot token file must be supplied together"
                )
            telegram_config = (
                None
                if telegram_config_path is None
                else _read_telegram_owner_config(telegram_config_path)
            )
            telegram_token = (
                None
                if telegram_token_path is None
                else _read_telegram_bot_token(telegram_token_path)
            )
            backup_status_file = getattr(args, "backup_status_file", None)
            activation_file = getattr(args, "deployment_activation_file", None)
            source_revision = getattr(args, "source_revision", None)
            if (activation_file is None) != (source_revision is None):
                raise ValueError(
                    "deployment activation file and source revision must be supplied together"
                )
            activation_gate = (
                None
                if activation_file is None or source_revision is None
                else ReleaseActivationGate(activation_file, source_revision)
            )
            if telegram_config is not None and connection is None:
                raise ValueError("Telegram requires a private PostgreSQL database")
            if telegram_config is not None and model_routes is None:
                raise ValueError("Telegram requires capable and economy model routes")
            if backup_status_file is not None and telegram_config is None:
                raise ValueError("backup status is exposed through the Telegram owner channel")
            access_scope: AccessScope = (
                "loopback"
                if args.host == "localhost" or ipaddress.ip_address(args.host).is_loopback
                else "private-network"
            )
            runtime = build_runtime(
                _guardian_reader(args),
                bootstrap_token,
                model_config,
                model_routes=model_routes,
                database_connection=connection,
                access_scope=access_scope,
                telegram_config=telegram_config,
                telegram_bot_token=telegram_token,
                backup_status_file=backup_status_file,
                background_activation=(
                    None if activation_gate is None else activation_gate.is_active
                ),
            )
        except psycopg.Error:
            _exit_error("Private database is unavailable or incompatible.")
        except (OSError, ValueError) as error:
            _exit_error(f"Melloa configuration rejected: {error}")
        print(
            json.dumps(
                {
                    "access_scope": access_scope,
                    "model_configured": (
                        model_config is not None or model_routes is not None
                    ),
                    "model_external_disclosure": (
                        model_config is not None
                        and model_config.processing_location.value == "approved_provider"
                    )
                    or (
                        model_routes is not None
                        and any(
                            config.processing_location.value == "approved_provider"
                            for config in (
                                model_routes.capable,
                                model_routes.economy,
                            )
                        )
                    ),
                    "model_routing_enabled": model_routes is not None,
                    "persistence": runtime.persistence,
                    "telegram_enabled": telegram_config is not None,
                    "release_activation_required": activation_gate is not None,
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


def self_change_plan(args: argparse.Namespace) -> int:
    try:
        _reject_planner_container_authority()
        _require_private_directory(
            args.agent_home,
            label="coding-agent home",
            owner_uid=args.agent_uid,
        )
        _require_private_directory(
            args.codex_home,
            label="Codex home",
            owner_uid=args.agent_uid,
        )
        if args.local_provider is not None and args.openai_api_key_file is not None:
            raise ValueError("local Codex providers cannot receive an OpenAI API key")
        agent_environment = {
            key: os.environ[key]
            for key in _PLANNER_ENVIRONMENT
            if os.environ.get(key)
        }
        agent_environment.update(
            {
                "CODEX_HOME": str(args.codex_home),
                "HOME": str(args.agent_home),
            }
        )
        if args.openai_api_key_file is not None:
            agent_environment["OPENAI_API_KEY"] = _read_private_file(
                args.openai_api_key_file,
                label="Codex API key",
                minimum=20,
            )
        with _connect_self_change_database(
            args.dsn_file,
            application_name="melloa-self-change-planner",
            expected_role="melloa_change_planner",
        ) as connection:
            worker = SelfChangePlanningWorker(
                store=PostgresSelfChangeStore(connection),
                planner=CodexCliSourceChangePlanner(
                    repository=args.repository,
                    work_root=args.work_root,
                    codex_executable=args.codex_executable,
                    git_executable=args.git_executable,
                    model=args.model,
                    local_provider=args.local_provider,
                    agent_environment=agent_environment,
                    agent_uid=args.agent_uid,
                    agent_gid=args.agent_gid,
                ),
            )
            _run_worker(worker)
    except psycopg.Error:
        _exit_error("Self-change planning database is unavailable or unauthorized.")
    except (OSError, ValueError) as error:
        _exit_error(f"Self-change planning configuration rejected: {error}")
    return 0


def self_change_apply(args: argparse.Namespace) -> int:
    try:
        leaked_environment = [
            key for key in _MODEL_CREDENTIAL_ENVIRONMENT if os.environ.get(key)
        ]
        if leaked_environment:
            raise ValueError("self-change application must not receive model credentials")
        release_environment = {
            key: os.environ[key]
            for key in _RELEASE_ENVIRONMENT
            if os.environ.get(key)
        }
        verifier = ExternalSandboxSelfChangeVerifier(
            args.verifier_executable,
            environment={
                "MELLOA_VERIFIER_NODE_MODULES": str(args.verifier_node_modules),
                "MELLOA_VERIFIER_PYTHON_ENV": str(args.verifier_python_env),
            },
        )
        deployment = ServerReleaseDeployment(
            environment_file=args.server_environment_file,
            release_state_dir=args.release_state_dir,
            environment=release_environment,
        )
        with _connect_self_change_database(
            args.dsn_file,
            application_name="melloa-self-change-applier",
            expected_role="melloa_change_applier",
        ) as connection:
            worker = SelfChangeApplyingWorker(
                store=PostgresSelfChangeStore(connection),
                executor=GitSelfChangeReleaseExecutor(
                    repository=args.repository,
                    state_root=args.work_root,
                    git_executable=args.git_executable,
                    verifier=verifier,
                    deployment=deployment,
                ),
            )
            _run_worker(worker)
    except psycopg.Error:
        _exit_error("Self-change application database is unavailable or unauthorized.")
    except (OSError, ValueError) as error:
        _exit_error(f"Self-change application configuration rejected: {error}")
    return 0


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

    deployment_parser = subparsers.add_parser("deployment-check")
    deployment_parser.add_argument(
        "--status",
        dest="guardian_status",
        type=Path,
        required=True,
    )
    deployment_parser.add_argument(
        "--public-key",
        dest="guardian_public_key",
        type=Path,
        required=True,
    )
    deployment_parser.add_argument("--capable-model-config", type=Path, required=True)
    deployment_parser.add_argument("--economy-model-config", type=Path, required=True)
    deployment_parser.add_argument(
        "--model-credential-source-root",
        type=Path,
        default=Path("/run/melloa/model-credentials"),
    )
    deployment_parser.add_argument("--telegram-owner-config", type=Path, required=True)
    deployment_parser.add_argument("--telegram-bot-token-file", type=Path, required=True)
    deployment_parser.set_defaults(handler=deployment_check)

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--status", dest="guardian_status", type=Path, required=True)
    serve_parser.add_argument(
        "--public-key",
        dest="guardian_public_key",
        type=Path,
        required=True,
    )
    serve_parser.add_argument(
        "--expected-guardian-receipt",
        type=_sha256_digest,
        help="Require the core's first Guardian read to match this verified receipt.",
    )
    serve_parser.add_argument(
        "--owner-credential-file",
        type=Path,
        default=Path(os.environ.get("MELLOA_OWNER_CREDENTIAL_FILE", "")),
        required="MELLOA_OWNER_CREDENTIAL_FILE" not in os.environ,
    )
    serve_parser.add_argument("--model-config", type=Path)
    capable_model_path = os.environ.get("MELLOA_CAPABLE_MODEL_CONFIG")
    serve_parser.add_argument(
        "--capable-model-config",
        type=Path,
        default=None if capable_model_path is None else Path(capable_model_path),
    )
    economy_model_path = os.environ.get("MELLOA_ECONOMY_MODEL_CONFIG")
    serve_parser.add_argument(
        "--economy-model-config",
        type=Path,
        default=None if economy_model_path is None else Path(economy_model_path),
    )
    database_path = os.environ.get("MELLOA_DATABASE_DSN_FILE")
    serve_parser.add_argument(
        "--database-dsn-file",
        type=Path,
        default=None if database_path is None else Path(database_path),
    )
    telegram_config_path = os.environ.get("MELLOA_TELEGRAM_OWNER_CONFIG")
    serve_parser.add_argument(
        "--telegram-owner-config",
        type=Path,
        default=None if telegram_config_path is None else Path(telegram_config_path),
    )
    telegram_token_path = os.environ.get("MELLOA_TELEGRAM_BOT_TOKEN_FILE")
    serve_parser.add_argument(
        "--telegram-bot-token-file",
        type=Path,
        default=None if telegram_token_path is None else Path(telegram_token_path),
    )
    backup_status_path = os.environ.get("MELLOA_BACKUP_STATUS_FILE")
    serve_parser.add_argument(
        "--backup-status-file",
        type=Path,
        default=None if backup_status_path is None else Path(backup_status_path),
    )
    activation_path = os.environ.get("MELLOA_DEPLOYMENT_ACTIVATION_FILE")
    serve_parser.add_argument(
        "--deployment-activation-file",
        type=Path,
        default=None if activation_path is None else Path(activation_path),
    )
    source_revision = os.environ.get("MELLOA_SOURCE_REVISION")
    serve_parser.add_argument(
        "--source-revision",
        default=source_revision,
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

    plan_parser = subparsers.add_parser("self-change-plan")
    plan_parser.add_argument("--dsn-file", type=Path, required=True)
    plan_parser.add_argument("--repository", type=Path, required=True)
    plan_parser.add_argument("--work-root", type=Path, required=True)
    plan_parser.add_argument("--codex-executable", type=Path, required=True)
    plan_parser.add_argument("--git-executable", type=Path, default=Path("/usr/bin/git"))
    plan_parser.add_argument("--agent-uid", type=int, required=True)
    plan_parser.add_argument("--agent-gid", type=int, required=True)
    plan_parser.add_argument("--agent-home", type=Path, required=True)
    plan_parser.add_argument("--codex-home", type=Path, required=True)
    plan_parser.add_argument("--openai-api-key-file", type=Path)
    plan_parser.add_argument("--model")
    plan_parser.add_argument("--local-provider", choices=("ollama", "lmstudio"))
    plan_parser.set_defaults(handler=self_change_plan)

    apply_parser = subparsers.add_parser("self-change-apply")
    apply_parser.add_argument("--dsn-file", type=Path, required=True)
    apply_parser.add_argument("--repository", type=Path, required=True)
    apply_parser.add_argument("--work-root", type=Path, required=True)
    apply_parser.add_argument("--git-executable", type=Path, default=Path("/usr/bin/git"))
    apply_parser.add_argument("--verifier-executable", type=Path, required=True)
    apply_parser.add_argument("--verifier-python-env", type=Path, required=True)
    apply_parser.add_argument("--verifier-node-modules", type=Path, required=True)
    apply_parser.add_argument("--server-environment-file", type=Path, required=True)
    apply_parser.add_argument("--release-state-dir", type=Path, required=True)
    apply_parser.set_defaults(handler=self_change_apply)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()
