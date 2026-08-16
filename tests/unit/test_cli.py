from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from melloa.adapters.postgres.migrations import MigrationStatus
from melloa.apps import cli


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
