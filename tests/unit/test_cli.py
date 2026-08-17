from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg
import pytest

from melloa.adapters.postgres.migrations import MigrationStatus
from melloa.apps import cli
from melloa.apps.synthetic import RuntimePersistenceStatus
from melloa.domain.models import ProcessingLocation


@pytest.mark.parametrize(
    "address",
    ["localhost", "127.0.0.1", "10.1.2.3", "100.64.1.2", "::1", "fd00::1"],
)
def test_private_bind_accepts_only_local_or_private_addresses(address) -> None:
    assert cli._private_bind_address(address) == address


@pytest.mark.parametrize("address", ["0.0.0.0", "::", "8.8.8.8", "example.com", "224.0.0.1"])
def test_private_bind_rejects_public_unspecified_and_hostnames(address) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        cli._private_bind_address(address)


def test_secret_file_requires_private_permissions(tmp_path) -> None:
    dsn_file = tmp_path / "dsn"
    dsn_file.write_text("host=localhost dbname=melloa", encoding="utf-8")
    dsn_file.chmod(0o600)
    assert cli._read_secret_file(dsn_file) == "host=localhost dbname=melloa"

    dsn_file.chmod(0o644)
    with pytest.raises(SystemExit):
        cli._read_secret_file(dsn_file)

    dsn_file.chmod(0o600)
    symlink = tmp_path / "dsn-link"
    symlink.symlink_to(dsn_file)
    with pytest.raises(SystemExit):
        cli._read_secret_file(symlink)


def test_doctor_reports_no_public_ingress(capsys) -> None:
    assert cli.doctor(argparse.Namespace()) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["public_ingress_configured"] is False


def test_migrate_check_uses_secret_file_without_printing_dsn(tmp_path, monkeypatch, capsys) -> None:
    dsn_file = tmp_path / "dsn"
    dsn_file.write_text("host=private.example password=not-printed", encoding="utf-8")
    dsn_file.chmod(0o600)

    class ConnectionContext:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(cli.psycopg, "connect", lambda *_args, **_kwargs: ConnectionContext())
    monkeypatch.setattr(cli, "discover_migrations", lambda *_args: ())
    monkeypatch.setattr(
        cli,
        "migration_status",
        lambda *_args: MigrationStatus(applied=("0001_m0_foundation",), pending=()),
    )
    args = argparse.Namespace(dsn_file=dsn_file, migration_command="check")
    assert cli.migrate(args) == 0
    output = capsys.readouterr().out
    assert "0001_m0_foundation" in output
    assert "not-printed" not in output


def test_migrate_apply_dispatches_apply(tmp_path, monkeypatch) -> None:
    dsn_file = tmp_path / "dsn"
    dsn_file.write_text("host=localhost", encoding="utf-8")
    dsn_file.chmod(0o600)
    applied = False

    class ConnectionContext:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    def apply(*_args):
        nonlocal applied
        applied = True
        return MigrationStatus(applied=("0001_m0_foundation",), pending=())

    monkeypatch.setattr(cli.psycopg, "connect", lambda *_args, **_kwargs: ConnectionContext())
    monkeypatch.setattr(cli, "discover_migrations", lambda *_args: ())
    monkeypatch.setattr(cli, "apply_migrations", apply)
    args = argparse.Namespace(dsn_file=dsn_file, migration_command="apply")
    assert cli.migrate(args) == 0
    assert applied is True


def test_serve_uses_injected_read_only_paths(monkeypatch, tmp_path) -> None:
    status_path = tmp_path / "status.json"
    public_key_path = tmp_path / "public.pem"
    captured = {}
    monkeypatch.setattr(cli, "create_app", lambda reader: (reader, "app"))
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, **kwargs: captured.update(app=app, **kwargs),
    )
    args = argparse.Namespace(
        guardian_status=status_path,
        guardian_public_key=public_key_path,
        host="127.0.0.1",
        port=8080,
    )
    assert cli.serve(args) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["access_log"] is False


def test_owner_credential_file_requires_private_permissions_and_valid_length(tmp_path) -> None:
    credential_file = tmp_path / "owner-credential"
    credential_file.write_text("synthetic-owner-bootstrap-token-value-0001", encoding="utf-8")
    credential_file.chmod(0o600)
    assert cli._read_owner_credential_file(credential_file) == (
        "synthetic-owner-bootstrap-token-value-0001"
    )

    credential_file.chmod(0o644)
    with pytest.raises(SystemExit):
        cli._read_owner_credential_file(credential_file)

    credential_file.chmod(0o600)
    credential_file.write_text("too-short", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli._read_owner_credential_file(credential_file)


def test_serve_synthetic_wires_explicit_process_local_runtime(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    credential_file = tmp_path / "owner-credential"
    bootstrap_token = "synthetic-owner-bootstrap-token-value-0001"
    credential_file.write_text(bootstrap_token, encoding="utf-8")
    credential_file.chmod(0o600)
    captured = {}
    application = object()
    runtime = argparse.Namespace(
        app=application,
        seed_assertion_id="assertion_00000000000000000000000000000001",
    )

    def build(reader, token):
        captured.update(reader=reader, token=token)
        return runtime

    monkeypatch.setattr(cli, "build_synthetic_runtime", build)
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, **kwargs: captured.update(app=app, **kwargs),
    )
    args = argparse.Namespace(
        guardian_status=tmp_path / "status.json",
        guardian_public_key=tmp_path / "public.pem",
        owner_credential_file=credential_file,
        host="127.0.0.1",
        port=8000,
    )

    assert cli.serve_synthetic(args) == 0
    assert captured["token"] == bootstrap_token
    assert captured["app"] is application
    assert captured["host"] == "127.0.0.1"
    assert captured["access_log"] is False
    output = capsys.readouterr().out
    assert "synthetic-in-memory" in output
    assert "process-only" in output
    assert bootstrap_token not in output


def test_parser_exposes_explicit_synthetic_runtime() -> None:
    arguments = cli.build_parser().parse_args(
        [
            "serve-synthetic",
            "--status",
            "/run/guardian/status.json",
            "--public-key",
            "/etc/guardian/public.pem",
            "--owner-credential-file",
            "/run/melloa/owner-credential",
        ]
    )
    assert arguments.handler is cli.serve_synthetic
    assert arguments.owner_credential_file == Path("/run/melloa/owner-credential")
    assert arguments.host == "127.0.0.1"
    assert arguments.port == 8000


def test_parser_exposes_optional_mvp_database_file() -> None:
    arguments = cli.build_parser().parse_args(
        [
            "serve-mvp",
            "--status",
            "/run/guardian/status.json",
            "--public-key",
            "/etc/guardian/public.pem",
            "--owner-credential-file",
            "/run/melloa/owner-credential",
            "--database-dsn-file",
            "/run/melloa/core-dsn",
        ]
    )

    assert arguments.handler is cli.serve_mvp
    assert arguments.database_dsn_file == Path("/run/melloa/core-dsn")


def test_serve_mvp_loads_repeatable_routes_without_printing_credentials(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    credential_file = tmp_path / "owner-credential"
    bootstrap_token = "synthetic-owner-bootstrap-token-value-0001"
    credential_file.write_text(bootstrap_token, encoding="utf-8")
    credential_file.chmod(0o600)
    route_path = tmp_path / "route.json"
    route_path.write_text("{}", encoding="utf-8")
    cli_agent_route_path = tmp_path / "codex-route.json"
    cli_agent_route_path.write_text("{}", encoding="utf-8")
    route_config = argparse.Namespace(
        route_id="model.local.test",
        processing_location=ProcessingLocation.DEVICE,
    )
    cli_agent_route_config = argparse.Namespace(
        route_id="model.codex.test",
        processing_location=ProcessingLocation.APPROVED_PROVIDER,
    )
    application = object()
    runtime = argparse.Namespace(
        app=application,
        model_route_ids=(
            "model.local.test",
            "model.codex.test",
            "model.fake.deterministic",
        ),
        seed_assertion_id="assertion_00000000000000000000000000000001",
        persistence=RuntimePersistenceStatus(
            mode="process-only-preview",
            durable_state=(),
            ephemeral_state=("authentication sessions",),
        ),
    )
    captured = {}

    monkeypatch.setattr(
        cli,
        "load_openai_compatible_route_config",
        lambda path: route_config if path == route_path else None,
    )
    monkeypatch.setattr(
        cli,
        "load_codex_cli_route_config",
        lambda path: cli_agent_route_config if path == cli_agent_route_path else None,
    )

    def build(
        reader,
        token,
        routes,
        telegram_config,
        *,
        cli_agent_route_configs,
    ):
        captured.update(
            reader=reader,
            token=token,
            routes=routes,
            telegram_config=telegram_config,
            cli_agent_route_configs=cli_agent_route_configs,
        )
        return runtime

    monkeypatch.setattr(cli, "build_mvp_runtime", build)
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, **kwargs: captured.update(app=app, **kwargs),
    )
    args = argparse.Namespace(
        guardian_status=tmp_path / "status.json",
        guardian_public_key=tmp_path / "public.pem",
        owner_credential_file=credential_file,
        model_route_config=[route_path],
        cli_agent_route_config=[cli_agent_route_path],
        host="127.0.0.1",
        port=8000,
    )

    assert cli.serve_mvp(args) == 0
    assert captured["token"] == bootstrap_token
    assert captured["routes"] == (route_config,)
    assert captured["cli_agent_route_configs"] == (cli_agent_route_config,)
    assert captured["telegram_config"] is None
    assert captured["app"] is application
    output = capsys.readouterr().out
    assert "owner-console-mvp-preview" in output
    assert "model.local.test" in output
    assert "model.codex.test" in output
    assert '"external_disclosure": true' in output
    assert '"sandbox": "read-only"' in output
    assert '"approval_policy": "never"' in output
    assert '"melloa_authority": "none"' in output
    assert '"usage_metadata": "unreported"' in output
    assert bootstrap_token not in output


def test_serve_mvp_wires_optional_private_postgres_and_closes_connections(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    credential_file = tmp_path / "owner-credential"
    bootstrap_token = "synthetic-owner-bootstrap-token-value-0001"
    credential_file.write_text(bootstrap_token, encoding="utf-8")
    credential_file.chmod(0o600)
    dsn_file = tmp_path / "core-dsn"
    database_secret = "private-database-password-must-not-be-printed"
    dsn_file.write_text(
        f"host=127.0.0.1 dbname=melloa password={database_secret}",
        encoding="utf-8",
    )
    dsn_file.chmod(0o600)
    connections = [object(), object(), object(), object(), object()]
    contexts = []
    connect_calls = []

    class ConnectionContext:
        closed = False

        def __init__(self, connection) -> None:
            self.connection = connection

        def __enter__(self):
            return self.connection

        def __exit__(self, *_args):
            self.closed = True
            return False

    def connect(dsn, **kwargs):
        context = ConnectionContext(connections[len(contexts)])
        contexts.append(context)
        connect_calls.append((dsn, kwargs))
        return context

    durable_stores = object()
    application = object()
    runtime = argparse.Namespace(
        app=application,
        model_route_ids=("model.fake.deterministic",),
        seed_assertion_id="assertion_00000000000000000000000000000001",
        persistence=RuntimePersistenceStatus(
            mode="postgresql-partial-preview",
            durable_state=("canonical conversations",),
            ephemeral_state=("authentication sessions",),
        ),
    )
    captured = {}

    monkeypatch.setattr(cli.psycopg, "connect", connect)
    monkeypatch.setattr(cli, "_guardian_reader", lambda _args: object())
    monkeypatch.setattr(
        cli,
        "build_postgres_mvp_stores",
        lambda *configured_connections, **kwargs: (
            captured.update(connections=configured_connections, store_kwargs=kwargs)
            or durable_stores
        ),
    )

    def build(
        reader,
        token,
        routes,
        telegram_config,
        *,
        cli_agent_route_configs,
        durable_stores,
    ):
        captured.update(
            reader=reader,
            token=token,
            routes=routes,
            telegram_config=telegram_config,
            cli_agent_route_configs=cli_agent_route_configs,
            durable_stores=durable_stores,
        )
        return runtime

    monkeypatch.setattr(cli, "build_mvp_runtime", build)
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, **kwargs: captured.update(app=app, **kwargs),
    )
    args = argparse.Namespace(
        guardian_status=tmp_path / "status.json",
        guardian_public_key=tmp_path / "public.pem",
        owner_credential_file=credential_file,
        database_dsn_file=dsn_file,
        model_route_config=[],
        cli_agent_route_config=[],
        telegram_bot_token_file=None,
        host="127.0.0.1",
        port=8000,
    )

    assert cli.serve_mvp(args) == 0
    assert captured["connections"] == tuple(connections)
    assert captured["durable_stores"] is durable_stores
    assert captured["app"] is application
    assert captured["store_kwargs"] == {
        "telegram_adapter_id": "client.telegram.synthetic"
    }
    assert len(connect_calls) == 5
    assert all(call[1]["autocommit"] is True for call in connect_calls)
    assert all("statement_timeout=5000" in call[1]["options"] for call in connect_calls)
    assert all(context.closed for context in contexts)
    startup = capsys.readouterr().out
    assert '"mode": "postgresql-partial-preview"' in startup
    assert '"assembled_records": "postgresql"' in startup
    assert '"coverage": "partial"' in startup
    assert '"delivery_records": "postgresql"' in startup
    assert '"pairing_offsets_ingestion": "postgresql"' in startup
    assert database_secret not in startup
    assert str(dsn_file) not in startup


def test_serve_mvp_redacts_database_connection_failures(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    credential_file = tmp_path / "owner-credential"
    credential_file.write_text(
        "synthetic-owner-bootstrap-token-value-0001",
        encoding="utf-8",
    )
    credential_file.chmod(0o600)
    dsn_file = tmp_path / "core-dsn"
    private_marker = "database-private-marker-must-not-be-printed"
    dsn_file.write_text(
        f"host=127.0.0.1 password={private_marker}",
        encoding="utf-8",
    )
    dsn_file.chmod(0o600)
    monkeypatch.setattr(
        cli.psycopg,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            psycopg.OperationalError(private_marker)
        ),
    )
    args = argparse.Namespace(
        guardian_status=tmp_path / "status.json",
        guardian_public_key=tmp_path / "public.pem",
        owner_credential_file=credential_file,
        database_dsn_file=dsn_file,
        model_route_config=[],
        cli_agent_route_config=[],
        telegram_bot_token_file=None,
        host="127.0.0.1",
        port=8000,
    )

    with pytest.raises(SystemExit) as captured:
        cli.serve_mvp(args)

    assert captured.value.code == 2
    error = capsys.readouterr().err
    assert "database unavailable or incompatible" in error
    assert private_marker not in error


def test_serve_mvp_wires_telegram_without_printing_token_or_path(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    credential_file = tmp_path / "owner-credential"
    bootstrap_token = "synthetic-owner-bootstrap-token-value-0001"
    credential_file.write_text(bootstrap_token, encoding="utf-8")
    credential_file.chmod(0o600)
    telegram_token_file = tmp_path / "telegram-bot-token"
    telegram_token = "123456789:telegram-token-must-never-be-printed"
    telegram_token_file.write_text(telegram_token, encoding="utf-8")
    telegram_token_file.chmod(0o600)
    application = object()
    runtime = argparse.Namespace(
        app=application,
        model_route_ids=("model.fake.deterministic",),
        seed_assertion_id="assertion_00000000000000000000000000000001",
        persistence=RuntimePersistenceStatus(
            mode="process-only-preview",
            durable_state=(),
            ephemeral_state=("authentication sessions",),
        ),
    )
    captured = {}

    def build(
        reader,
        token,
        routes,
        telegram_config,
        *,
        cli_agent_route_configs,
    ):
        captured.update(
            reader=reader,
            token=token,
            routes=routes,
            telegram_config=telegram_config,
            cli_agent_route_configs=cli_agent_route_configs,
        )
        return runtime

    monkeypatch.setattr(cli, "build_mvp_runtime", build)
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, **kwargs: captured.update(app=app, **kwargs),
    )
    args = argparse.Namespace(
        guardian_status=tmp_path / "status.json",
        guardian_public_key=tmp_path / "public.pem",
        owner_credential_file=credential_file,
        model_route_config=[],
        telegram_bot_token_file=telegram_token_file,
        telegram_api_base_url="https://api.telegram.org",
        host="127.0.0.1",
        port=8000,
    )

    assert cli.serve_mvp(args) == 0
    assert captured["telegram_config"].token_file == telegram_token_file
    assert captured["telegram_config"].api_base_url == "https://api.telegram.org"
    assert captured["cli_agent_route_configs"] == ()
    assert captured["app"] is application
    startup = capsys.readouterr().out
    assert '"configured": true' in startup
    assert '"adapter_id": "client.telegram.bot-api"' in startup
    assert telegram_token not in startup
    assert str(telegram_token_file) not in startup


def test_serve_mvp_redacts_token_when_telegram_startup_is_rejected(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    credential_file = tmp_path / "owner-credential"
    credential_file.write_text(
        "synthetic-owner-bootstrap-token-value-0001",
        encoding="utf-8",
    )
    credential_file.chmod(0o600)
    telegram_token_file = tmp_path / "telegram-bot-token"
    telegram_token = "123456789:telegram-token-must-never-be-printed"
    telegram_token_file.write_text(telegram_token, encoding="utf-8")
    telegram_token_file.chmod(0o640)
    monkeypatch.setattr(cli, "_guardian_reader", lambda _args: object())
    args = argparse.Namespace(
        guardian_status=tmp_path / "status.json",
        guardian_public_key=tmp_path / "public.pem",
        owner_credential_file=credential_file,
        model_route_config=[],
        telegram_bot_token_file=telegram_token_file,
        telegram_api_base_url="https://api.telegram.org",
        host="127.0.0.1",
        port=8000,
    )

    with pytest.raises(SystemExit) as captured:
        cli.serve_mvp(args)

    assert captured.value.code == 2
    error = capsys.readouterr().err
    assert "mode must be exactly 0600" in error
    assert telegram_token not in error


def test_serve_mvp_rejects_unsafe_cli_agent_config_without_a_traceback(
    tmp_path,
    capsys,
) -> None:
    credential_file = tmp_path / "owner-credential"
    credential_file.write_text(
        "synthetic-owner-bootstrap-token-value-0001",
        encoding="utf-8",
    )
    credential_file.chmod(0o600)
    route_config = tmp_path / "codex-route.json"
    private_marker = "private-config-marker-must-not-be-printed"
    route_config.write_text(private_marker, encoding="utf-8")
    route_config.chmod(0o666)
    args = argparse.Namespace(
        guardian_status=tmp_path / "status.json",
        guardian_public_key=tmp_path / "public.pem",
        owner_credential_file=credential_file,
        model_route_config=[],
        cli_agent_route_config=[route_config],
        telegram_bot_token_file=None,
        host="127.0.0.1",
        port=8000,
    )

    with pytest.raises(SystemExit) as captured:
        cli.serve_mvp(args)

    assert captured.value.code == 2
    error = capsys.readouterr().err
    assert "MVP configuration rejected" in error
    assert "non-writable regular file" in error
    assert private_marker not in error


def test_parser_exposes_mvp_runtime_and_repeatable_route_configs() -> None:
    arguments = cli.build_parser().parse_args(
        [
            "serve-mvp",
            "--status",
            "/run/guardian/status.json",
            "--public-key",
            "/etc/guardian/public.pem",
            "--owner-credential-file",
            "/run/melloa/owner-credential",
            "--model-route-config",
            "config/routes/ollama-qwen.example.json",
            "--model-route-config",
            "/run/melloa/second-route.json",
            "--cli-agent-route-config",
            "config/routes/codex-cli.example.json",
            "--cli-agent-route-config",
            "/run/melloa/second-codex-route.json",
        ]
    )
    assert arguments.handler is cli.serve_mvp
    assert arguments.model_route_config == [
        Path("config/routes/ollama-qwen.example.json"),
        Path("/run/melloa/second-route.json"),
    ]
    assert arguments.cli_agent_route_config == [
        Path("config/routes/codex-cli.example.json"),
        Path("/run/melloa/second-codex-route.json"),
    ]
    assert arguments.host == "127.0.0.1"
    assert arguments.port == 8000


def test_parser_exposes_telegram_bot_api_configuration(monkeypatch) -> None:
    monkeypatch.delenv("MELLOA_TELEGRAM_BOT_TOKEN_FILE", raising=False)
    monkeypatch.delenv("MELLOA_TELEGRAM_API_BASE_URL", raising=False)
    arguments = cli.build_parser().parse_args(
        [
            "serve-mvp",
            "--status",
            "/run/guardian/status.json",
            "--public-key",
            "/etc/guardian/public.pem",
            "--owner-credential-file",
            "/run/melloa/owner-credential",
            "--telegram-bot-token-file",
            "/run/melloa/telegram-token",
            "--telegram-api-base-url",
            "http://127.0.0.1:8081",
        ]
    )

    assert arguments.telegram_bot_token_file == Path("/run/melloa/telegram-token")
    assert arguments.telegram_api_base_url == "http://127.0.0.1:8081"


def test_export_mvp_writes_validated_bundle_without_printing_owner_credential(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    credential_file = tmp_path / "owner-credential"
    bootstrap_token = "synthetic-owner-bootstrap-token-value-0001"
    credential_file.write_text(bootstrap_token, encoding="utf-8")
    credential_file.chmod(0o600)
    output_dir = tmp_path / "bundle"
    captured = {}
    runtime = argparse.Namespace(
        owner_id="owner_00000000000000000000000000000001",
        intelligence_id="intelligence_00000000000000000000000000000001",
        conversation_service=object(),
        delivery_service=object(),
        memory_service=object(),
        memory_store=object(),
        persistence=RuntimePersistenceStatus(
            mode="process-only-preview",
            durable_state=(),
            ephemeral_state=("authentication sessions",),
        ),
    )

    class GuardianReader:
        def read_status(self):
            captured["guardian_verified"] = True
            return object()

    class ExportService:
        def __init__(self, **kwargs):
            captured["service_kwargs"] = kwargs

        def write_bundle(self, output, *, schema_root):
            captured["output"] = output
            captured["schema_root"] = schema_root
            return argparse.Namespace(
                export_id="export_00000000000000000000000000000001",
                files=(object(), object()),
            )

    monkeypatch.setattr(cli, "_guardian_reader", lambda _args: GuardianReader())
    monkeypatch.setattr(cli, "build_mvp_runtime", lambda reader, token, **_kwargs: runtime)
    monkeypatch.setattr(cli, "OwnerExportService", ExportService)
    monkeypatch.setattr(
        cli,
        "validate_bundle",
        lambda output: argparse.Namespace(
            valid=True,
            record_counts={"assertions/inspections.jsonl": 1},
        ),
    )
    args = argparse.Namespace(
        guardian_status=tmp_path / "status.json",
        guardian_public_key=tmp_path / "public.pem",
        owner_credential_file=credential_file,
        database_dsn_file=None,
        output_dir=output_dir,
    )

    assert cli.export_mvp(args) == 0
    assert captured["guardian_verified"] is True
    assert captured["service_kwargs"]["delivery"] is runtime.delivery_service
    assert captured["service_kwargs"]["memory_repository"] is runtime.memory_store
    assert captured["output"] == output_dir
    output = capsys.readouterr().out
    assert "export_00000000000000000000000000000001" in output
    assert "assertions/inspections.jsonl" in output
    assert bootstrap_token not in output


def test_parser_exposes_mvp_export_and_import_validation() -> None:
    export_args = cli.build_parser().parse_args(
        [
            "export-mvp",
            "--status",
            "/run/guardian/status.json",
            "--public-key",
            "/etc/guardian/public.pem",
            "--owner-credential-file",
            "/run/melloa/owner-credential",
            "--output-dir",
            "/run/melloa/export-20260816",
        ]
    )
    assert export_args.handler is cli.export_mvp
    assert export_args.output_dir == Path("/run/melloa/export-20260816")

    import_args = cli.build_parser().parse_args(
        [
            "import-validate",
            "--bundle-dir",
            "/run/melloa/export-20260816",
        ]
    )
    assert import_args.handler is cli.import_validate
    assert import_args.bundle_dir == Path("/run/melloa/export-20260816")


def test_parser_accepts_path_only_telegram_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "MELLOA_TELEGRAM_BOT_TOKEN_FILE",
        "/run/melloa/telegram-token",
    )
    monkeypatch.setenv("MELLOA_TELEGRAM_API_BASE_URL", "http://[::1]:8081")
    arguments = cli.build_parser().parse_args(
        [
            "serve-mvp",
            "--status",
            "/run/guardian/status.json",
            "--public-key",
            "/etc/guardian/public.pem",
            "--owner-credential-file",
            "/run/melloa/owner-credential",
        ]
    )

    assert arguments.telegram_bot_token_file == Path("/run/melloa/telegram-token")
    assert arguments.telegram_api_base_url == "http://[::1]:8081"


def test_parser_requires_explicit_guardian_paths() -> None:
    parser = cli.build_parser()
    arguments = parser.parse_args(
        [
            "guardian-status",
            "--status",
            "/run/guardian/status.json",
            "--public-key",
            "/etc/guardian/public.pem",
        ]
    )
    assert arguments.guardian_status == Path("/run/guardian/status.json")
