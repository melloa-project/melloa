from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from melloa.adapters.models.openai_compatible import OpenAICompatibleModelConfig
from melloa.adapters.postgres.migrations import MigrationStatus
from melloa.apps import cli

_OWNER_CREDENTIAL = "owner-cli-test-credential-value-0001"


def _model_config(model_id: str) -> OpenAICompatibleModelConfig:
    return OpenAICompatibleModelConfig(
        display_name=model_id,
        provider_id="provider.cli-test",
        model_id=model_id,
        base_url="http://127.0.0.1:11434/v1",
    )


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("10.0.0.8", True),
        ("100.100.1.2", True),
        ("0.0.0.0", False),
        ("8.8.8.8", False),
        ("example.com", False),
    ],
)
def test_serve_bind_is_private(value: str, accepted: bool) -> None:
    if accepted:
        assert cli._private_bind_address(value) == value
    else:
        with pytest.raises(argparse.ArgumentTypeError):
            cli._private_bind_address(value)


def test_private_configuration_files_reject_weak_permissions_and_symlinks(tmp_path) -> None:
    credential = tmp_path / "owner-credential"
    credential.write_text(_OWNER_CREDENTIAL, encoding="utf-8")
    credential.chmod(0o600)
    assert cli._read_owner_credential_file(credential) == _OWNER_CREDENTIAL

    credential.chmod(0o644)
    with pytest.raises(SystemExit) as weak:
        cli._read_owner_credential_file(credential)
    assert weak.value.code == 2

    credential.chmod(0o600)
    linked = tmp_path / "linked-credential"
    linked.symlink_to(credential)
    with pytest.raises(SystemExit) as symlink:
        cli._read_owner_credential_file(linked)
    assert symlink.value.code == 2

    telegram_config = tmp_path / "telegram-owner.json"
    telegram_config.write_text(
        '{"owner_user_id":1234,"owner_chat_id":5678}',
        encoding="utf-8",
    )
    telegram_config.chmod(0o600)
    assert cli._read_telegram_owner_config(telegram_config).owner_chat_id == 5678

    telegram_token = tmp_path / "telegram-token"
    token = "123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456"
    telegram_token.write_text(token, encoding="utf-8")
    telegram_token.chmod(0o600)
    assert cli._read_telegram_bot_token(telegram_token) == token


@pytest.mark.parametrize(
    "dsn",
    [
        "host=localhost dbname=melloa",
        "host=127.0.0.1 dbname=melloa",
        "host=10.0.0.4 dbname=melloa",
        "host=/run/postgresql dbname=melloa",
    ],
)
def test_database_dsn_accepts_only_direct_private_targets(dsn: str) -> None:
    assert cli._validate_private_database_dsn(dsn) == dsn


@pytest.mark.parametrize(
    "dsn",
    [
        "host=8.8.8.8 dbname=melloa",
        "host=0.0.0.0 dbname=melloa",
        "host=database.example.com dbname=melloa",
        "service=owner-db",
    ],
)
def test_database_dsn_rejects_public_or_indirect_targets(dsn: str) -> None:
    with pytest.raises(ValueError):
        cli._validate_private_database_dsn(dsn)


def test_serve_builds_one_runtime_without_printing_owner_secret(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    credential = tmp_path / "owner-credential"
    credential.write_text(_OWNER_CREDENTIAL, encoding="utf-8")
    credential.chmod(0o600)
    application = object()
    captured: dict[str, object] = {}

    def build(reader, token, model_config, **kwargs):
        captured.update(
            reader=reader,
            token=token,
            model_config=model_config,
            runtime_kwargs=kwargs,
        )
        return SimpleNamespace(app=application, persistence="process-only")

    monkeypatch.setattr(cli, "build_runtime", build)
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, **kwargs: captured.update(app=app, uvicorn_kwargs=kwargs),
    )
    args = argparse.Namespace(
        guardian_status=tmp_path / "guardian-status.json",
        guardian_public_key=tmp_path / "guardian-public.pem",
        owner_credential_file=credential,
        model_config=None,
        database_dsn_file=None,
        host="127.0.0.1",
        port=8080,
    )

    assert cli.serve(args) == 0
    assert captured["token"] == _OWNER_CREDENTIAL
    assert captured["model_config"] is None
    assert captured["app"] is application
    assert captured["runtime_kwargs"] == {
        "model_routes": None,
        "database_connection": None,
        "access_scope": "loopback",
        "telegram_config": None,
        "telegram_bot_token": None,
        "backup_status_file": None,
        "background_activation": None,
    }
    assert captured["uvicorn_kwargs"] == {
        "host": "127.0.0.1",
        "port": 8080,
        "access_log": False,
    }
    output = capsys.readouterr().out
    assert '"persistence": "process-only"' in output
    assert '"model_configured": false' in output
    assert '"model_routing_enabled": false' in output
    assert '"telegram_enabled": false' in output
    assert _OWNER_CREDENTIAL not in output


def test_serve_wires_private_telegram_files_without_printing_personal_values(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    credential = tmp_path / "owner-credential"
    credential.write_text(_OWNER_CREDENTIAL, encoding="utf-8")
    credential.chmod(0o600)
    dsn_file = tmp_path / "database-dsn"
    dsn_file.write_text("host=127.0.0.1 dbname=melloa", encoding="utf-8")
    dsn_file.chmod(0o600)
    telegram_config = tmp_path / "telegram-owner.json"
    telegram_config.write_text(
        '{"owner_user_id":1234,"owner_chat_id":5678}',
        encoding="utf-8",
    )
    telegram_config.chmod(0o600)
    telegram_token = tmp_path / "telegram-token"
    token = "123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456"
    telegram_token.write_text(token, encoding="utf-8")
    telegram_token.chmod(0o600)
    capable_model_path = tmp_path / "capable-model.json"
    economy_model_path = tmp_path / "economy-model.json"
    capable_model = _model_config("capable-cli-v1")
    economy_model = _model_config("economy-cli-v1")
    backup_status = tmp_path / "backup-status.json"
    captured: dict[str, object] = {}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(cli.psycopg, "connect", lambda *_args, **_kwargs: Connection())
    monkeypatch.setattr(
        cli,
        "load_openai_compatible_model_config",
        lambda path: {
            capable_model_path: capable_model,
            economy_model_path: economy_model,
        }[path],
    )

    def build(reader, owner_token, configured_model, **kwargs):
        captured.update(
            reader=reader,
            owner_token=owner_token,
            configured_model=configured_model,
            runtime_kwargs=kwargs,
        )
        return SimpleNamespace(app=object(), persistence="postgresql")

    monkeypatch.setattr(cli, "build_runtime", build)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_args, **_kwargs: None)
    args = argparse.Namespace(
        guardian_status=tmp_path / "guardian-status.json",
        guardian_public_key=tmp_path / "guardian-public.pem",
        owner_credential_file=credential,
        model_config=None,
        capable_model_config=capable_model_path,
        economy_model_config=economy_model_path,
        database_dsn_file=dsn_file,
        telegram_owner_config=telegram_config,
        telegram_bot_token_file=telegram_token,
        backup_status_file=backup_status,
        host="127.0.0.1",
        port=8080,
    )

    assert cli.serve(args) == 0
    assert captured["owner_token"] == _OWNER_CREDENTIAL
    assert captured["configured_model"] is None
    runtime_kwargs = captured["runtime_kwargs"]
    assert isinstance(runtime_kwargs, dict)
    assert runtime_kwargs["model_routes"].capable is capable_model
    assert runtime_kwargs["model_routes"].economy is economy_model
    assert runtime_kwargs["telegram_config"].owner_user_id == 1234
    assert runtime_kwargs["telegram_config"].owner_chat_id == 5678
    assert runtime_kwargs["telegram_bot_token"] == token
    assert runtime_kwargs["backup_status_file"] == backup_status
    output = capsys.readouterr().out
    assert '"telegram_enabled": true' in output
    assert '"model_routing_enabled": true' in output
    assert token not in output
    assert "1234" not in output
    assert "5678" not in output


def test_serve_rejects_partial_model_route_configuration(tmp_path: Path, capsys) -> None:
    credential = tmp_path / "owner-credential"
    credential.write_text(_OWNER_CREDENTIAL, encoding="utf-8")
    credential.chmod(0o600)
    args = argparse.Namespace(
        guardian_status=tmp_path / "guardian-status.json",
        guardian_public_key=tmp_path / "guardian-public.pem",
        owner_credential_file=credential,
        model_config=None,
        capable_model_config=tmp_path / "capable-model.json",
        economy_model_config=None,
        database_dsn_file=None,
        host="127.0.0.1",
        port=8080,
    )

    with pytest.raises(SystemExit) as failure:
        cli.serve(args)

    assert failure.value.code == 2
    assert "must be supplied together" in capsys.readouterr().err


def test_migrate_dispatches_without_printing_dsn(tmp_path, monkeypatch, capsys) -> None:
    dsn_file = tmp_path / "dsn"
    private_dsn = "host=127.0.0.1 password=must-not-print"
    dsn_file.write_text(private_dsn, encoding="utf-8")
    dsn_file.chmod(0o600)
    captured: dict[str, object] = {}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def connect(dsn, **kwargs):
        captured.update(dsn=dsn, kwargs=kwargs)
        return Connection()

    monkeypatch.setattr(cli.psycopg, "connect", connect)
    monkeypatch.setattr(cli, "discover_migrations", lambda *_args: ())
    monkeypatch.setattr(
        cli,
        "migration_status",
        lambda *_args: MigrationStatus(applied=("0001_owner_baseline",), pending=()),
    )

    assert cli.migrate(
        argparse.Namespace(dsn_file=dsn_file, migration_command="check")
    ) == 0
    assert captured["dsn"] == private_dsn
    assert captured["kwargs"] == {"autocommit": True}
    output = capsys.readouterr().out
    assert "0001_owner_baseline" in output
    assert "must-not-print" not in output


def test_parser_exposes_only_current_operator_commands() -> None:
    parser = cli.build_parser()
    guardian = parser.parse_args(
        [
            "guardian-status",
            "--status",
            "/run/guardian/status.json",
            "--public-key",
            "/etc/guardian/public.pem",
        ]
    )
    serve = parser.parse_args(
        [
            "serve",
            "--status",
            "/run/guardian/status.json",
            "--public-key",
            "/etc/guardian/public.pem",
            "--expected-guardian-receipt",
            "sha256:" + "0" * 64,
            "--owner-credential-file",
            "/run/melloa/owner-credential",
            "--capable-model-config",
            "/etc/melloa/capable-model.json",
            "--economy-model-config",
            "/etc/melloa/economy-model.json",
            "--telegram-owner-config",
            "/etc/melloa/telegram-owner.json",
            "--telegram-bot-token-file",
            "/run/credentials/telegram-token",
            "--backup-status-file",
            "/var/lib/melloa/backup-status.json",
            "--deployment-activation-file",
            "/var/lib/melloa/release/active-revision",
            "--source-revision",
            "abc123",
        ]
    )
    migrate = parser.parse_args(
        ["migrate", "check", "--dsn-file", "/run/melloa/database-dsn"]
    )

    assert guardian.handler is cli.guardian_status
    assert serve.handler is cli.serve
    assert serve.expected_guardian_receipt == "sha256:" + "0" * 64
    assert serve.capable_model_config == Path("/etc/melloa/capable-model.json")
    assert serve.economy_model_config == Path("/etc/melloa/economy-model.json")
    assert serve.telegram_owner_config == Path("/etc/melloa/telegram-owner.json")
    assert serve.telegram_bot_token_file == Path("/run/credentials/telegram-token")
    assert serve.backup_status_file == Path("/var/lib/melloa/backup-status.json")
    assert serve.deployment_activation_file == Path(
        "/var/lib/melloa/release/active-revision"
    )
    assert serve.source_revision == "abc123"
    assert migrate.handler is cli.migrate
    with pytest.raises(SystemExit):
        parser.parse_args(["serve-mvp"])
