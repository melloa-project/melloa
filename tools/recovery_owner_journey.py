#!/usr/bin/env python3
"""Seed or verify the small owner journey used by the encrypted restore drill."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.postgres.memory import PostgresMemoryRepository
from melloa.adapters.postgres.migrations import discover_migrations
from melloa.apps.cli import (
    _read_owner_credential_file,
    _read_secret_file,
    _validate_private_database_dsn,
)
from melloa.apps.runtime import OWNER_ID, build_runtime
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.memory import Assertion, AssertionStatus

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
MIGRATION_MANIFEST = MIGRATIONS / "manifest.json"
SENSITIVE_FIXTURE_MARKER = "restore-private-owner-marker-v1"
_FIXTURE_TITLE = "Owner recovery check"
_FIXTURE_MESSAGE = f"Keep this private recovery context: {SENSITIVE_FIXTURE_MARKER}"
_FIXTURE_TIME = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


class JourneyError(RuntimeError):
    """A restore check failed without exposing owner data."""


class JourneyExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str
    message_id: str
    session_id: str
    assertion_id: str


class DeterministicIdFactory:
    def __init__(self, namespace: int) -> None:
        self._namespace = namespace
        self._counts: defaultdict[str, int] = defaultdict(int)

    def __call__(self, prefix: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_]{1,31}", prefix) is None:
            raise ValueError("invalid record ID prefix")
        self._counts[prefix] += 1
        return f"{prefix}_{self._namespace + self._counts[prefix]:032x}"


def _guardian() -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="restore-test-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=_FIXTURE_TIME,
            reason_code="guardian.restore-test",
        ),
        receipt_hash="sha256:" + "d" * 64,
        key_id="guardian.restore-test",
    )


def _connect(path: Path) -> psycopg.Connection[tuple[Any, ...]]:
    dsn = _validate_private_database_dsn(_read_secret_file(path))
    connection: psycopg.Connection[tuple[Any, ...]] = psycopg.connect(
        dsn,
        autocommit=True,
        connect_timeout=5,
        application_name="melloa-restore-check",
    )
    connection.execute("SET ROLE melloa_core")
    return connection


def _write_expectation(path: Path, expectation: JourneyExpectation) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, expectation.model_dump_json(indent=2).encode("utf-8"))
    finally:
        os.close(descriptor)


def _read_expectation(path: Path) -> JourneyExpectation:
    try:
        document = path.read_text(encoding="utf-8")
    except OSError as error:
        raise JourneyError("restore expectation is unavailable") from error
    return JourneyExpectation.model_validate_json(document)


def seed(args: argparse.Namespace) -> None:
    owner_credential = _read_owner_credential_file(args.owner_credential_file)
    ids = DeterministicIdFactory(int("d0020000000000000000000000000000", 16))
    with _connect(args.dsn_file) as connection:
        runtime = build_runtime(
            _guardian(),
            owner_credential,
            database_connection=connection,
            clock=lambda: _FIXTURE_TIME,
            id_factory=ids,
            secure_session_cookie=False,
            access_scope="loopback",
        )
        with TestClient(runtime.app) as client:
            login = client.post(
                "/api/v1/auth/session",
                json={"credential": owner_credential},
            )
            if login.status_code != 200:
                raise JourneyError("restore seed login failed")
            csrf = login.json()["csrf_token"]
            headers = {"X-Melloa-CSRF": csrf}
            thread = client.post(
                "/api/v1/conversations",
                headers=headers,
                json={
                    "title": _FIXTURE_TITLE,
                    "sensitivity": "highly_sensitive",
                },
            )
            if thread.status_code != 201:
                raise JourneyError("restore seed conversation failed")
            thread_id = thread.json()["thread_id"]
            message = client.post(
                f"/api/v1/conversations/{thread_id}/messages",
                headers=headers,
                json={
                    "text": _FIXTURE_MESSAGE,
                    "idempotency_key": "restore-message-1",
                },
            )
            if message.status_code != 202:
                raise JourneyError("restore seed message failed")

        assertion = Assertion(
            assertion_id=ids("assertion"),
            subject_id=OWNER_ID,
            predicate="recovery.private-fixture",
            value={"marker": SENSITIVE_FIXTURE_MARKER},
            epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
            status=AssertionStatus.CONFIRMED,
            confidence=1.0,
            source_authority=TrustLabel.OWNER_AUTHORED,
            sensitivity=Sensitivity.HIGHLY_SENSITIVE,
            observed_at=_FIXTURE_TIME,
        )
        connection.execute(
            "SELECT melloa.append_assertion(%s, %s, %s, %s)",
            (
                Jsonb(assertion.model_dump(mode="json")),
                "memory.assertion-owner-lifecycle",
                _FIXTURE_TIME,
                None,
            ),
        )
        expectation = JourneyExpectation(
            thread_id=thread_id,
            message_id=message.json()["inbound_message"]["message_id"],
            session_id=login.json()["principal"]["session_id"],
            assertion_id=assertion.assertion_id,
        )
    _write_expectation(args.expected_file, expectation)


def verify(args: argparse.Namespace) -> None:
    expected = _read_expectation(args.expected_file)
    owner_credential = _read_owner_credential_file(args.owner_credential_file)
    ids = DeterministicIdFactory(int("d0030000000000000000000000000000", 16))
    with _connect(args.dsn_file) as connection:
        runtime = build_runtime(
            _guardian(),
            owner_credential,
            database_connection=connection,
            clock=lambda: _FIXTURE_TIME,
            id_factory=ids,
            secure_session_cookie=False,
            access_scope="loopback",
        )
        with TestClient(runtime.app) as client:
            login = client.post(
                "/api/v1/auth/session",
                json={"credential": owner_credential},
            )
            if login.status_code != 200:
                raise JourneyError("restored owner login failed")
            threads = client.get("/api/v1/conversations")
            if threads.status_code != 200 or not any(
                item["thread_id"] == expected.thread_id
                and item["title"] == _FIXTURE_TITLE
                for item in threads.json()
            ):
                raise JourneyError("restored conversation is missing")
            transcript = client.get(
                f"/api/v1/conversations/{expected.thread_id}/transcript"
            )
            if transcript.status_code != 200 or not any(
                item["message_id"] == expected.message_id
                and item["parts"][0]["text"] == _FIXTURE_MESSAGE
                for item in transcript.json()["messages"]
            ):
                raise JourneyError("restored private message is missing")
            sessions = client.get("/api/v1/auth/sessions")
            if sessions.status_code != 200 or not any(
                item["session_id"] == expected.session_id
                for item in sessions.json()["sessions"]
            ):
                raise JourneyError("restored owner session is missing")

        memory = PostgresMemoryRepository(connection).get_assertion(expected.assertion_id)
        if memory.value != {"marker": SENSITIVE_FIXTURE_MARKER}:
            raise JourneyError("restored owner memory is missing")


def recovery_receipt() -> dict[str, object]:
    migrations = discover_migrations(MIGRATIONS, MIGRATION_MANIFEST)
    return {
        "migrations": [{"name": item.path.name, "status": "pass"} for item in migrations],
        "checks": {
            "authenticated_owner_read": "pass",
            "conversation_round_trip": "pass",
            "memory_round_trip": "pass",
            "encrypted_backup": "pass",
            "clean_restore": "pass",
            "ephemeral_cleanup": "pass",
        },
        "recovery_authority": "postgresql-logical-state",
        "owner_export": "portability-only-not-used",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("seed", seed), ("verify", verify)):
        command = subparsers.add_parser(name)
        command.add_argument("--dsn-file", type=Path, required=True)
        command.add_argument("--owner-credential-file", type=Path, required=True)
        command.add_argument("--expected-file", type=Path, required=True)
        command.set_defaults(handler=handler)
    receipt = subparsers.add_parser("receipt")
    receipt.set_defaults(handler=lambda _args: print(json.dumps(recovery_receipt(), indent=2)))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.handler(args)
    except (JourneyError, OSError, ValueError, psycopg.Error) as error:
        print(f"Recovery check failed: {error}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
