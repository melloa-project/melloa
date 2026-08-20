from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock

from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.application.owner_status import OwnerModelRoutes, OwnerStatusReporter
from melloa.domain.conversation import ConversationProcessingState
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.models import ModelGatewayHealth, ModelHealthState, ModelRoute
from melloa.ports.telegram import TelegramDeliverySummary
from tests.conftest import record_id


def _guardian(fixed_time, mode=GuardianMode.NORMAL):
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="owner-status-guardian",
            mode=mode,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.test",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def test_owner_status_reports_release_model_backlog_guardian_and_backup(
    fixed_time,
    tmp_path,
) -> None:
    marker = tmp_path / "backup-status.json"
    marker.write_text(
        """{
          "contract_version": "1.0.0",
          "result": "success",
          "checked_at": "2026-08-16T12:00:00Z",
          "completed_at": "2026-08-16T11:40:00Z"
        }""",
        encoding="utf-8",
    )
    marker.chmod(0o600)
    telegram = Mock()
    telegram.delivery_summary.return_value = TelegramDeliverySummary(
        awaiting_reply=0,
        ready=0,
        running=0,
        sent=8,
        dead=0,
    )
    reporter = OwnerStatusReporter(
        guardian_reader=_guardian(fixed_time),
        conversation_store=InMemoryConversationStore(),
        telegram_store=telegram,
        thread_id=record_id("thread", 1),
        model_id="owner-model-v1",
        model_health=lambda: ModelGatewayHealth(
            state=ModelHealthState.HEALTHY,
            checked_at=fixed_time,
            latency_ms=10,
            reason_code="model.endpoint_ready",
        ),
        backup_status_file=marker,
        clock=lambda: fixed_time,
    )

    assert reporter.render() == "\n".join(
        (
            "Melli status",
            "Overall: healthy",
            "Release: v0.2.0 preview",
            "Model: owner-model-v1 — healthy",
            "Backlog: 0 replies, 0 deliveries; 0 failed",
            "Guardian: normal",
            "Backup: healthy (0h 20m old)",
        )
    )


def test_owner_status_fails_closed_when_dependencies_are_unhealthy(
    fixed_time,
    tmp_path,
) -> None:
    conversation = Mock()
    conversation.list_reply_processing.return_value = (
        Mock(state=ConversationProcessingState.READY),
        Mock(state=ConversationProcessingState.DEAD),
    )
    telegram = Mock()
    telegram.delivery_summary.return_value = TelegramDeliverySummary(
        awaiting_reply=1,
        ready=1,
        running=0,
        sent=0,
        dead=2,
    )
    reporter = OwnerStatusReporter(
        guardian_reader=_guardian(fixed_time, GuardianMode.READ_ONLY),
        conversation_store=conversation,
        telegram_store=telegram,
        thread_id=record_id("thread", 1),
        model_id="unavailable-model",
        model_health=lambda: ModelGatewayHealth(
            state=ModelHealthState.UNAVAILABLE,
            checked_at=fixed_time,
            latency_ms=None,
            reason_code="model.endpoint_unavailable",
        ),
        backup_status_file=tmp_path / "missing.json",
        clock=lambda: fixed_time,
        backup_stale_after=timedelta(hours=1),
    )

    status = reporter.render()

    assert "Overall: degraded" in status
    assert "Model: unavailable-model — unavailable" in status
    assert "Backlog: 1 replies, 2 deliveries; 3 failed" in status
    assert "Guardian: read-only" in status
    assert "Backup: missing" in status


def test_owner_status_rejects_writable_or_stale_backup_marker(fixed_time, tmp_path) -> None:
    marker = tmp_path / "backup-status.json"
    marker.write_text(
        """{
          "contract_version": "1.0.0",
          "result": "success",
          "checked_at": "2026-08-16T12:00:00Z",
          "completed_at": "2026-08-14T12:00:00Z"
        }""",
        encoding="utf-8",
    )
    marker.chmod(0o622)
    telegram = Mock()
    telegram.delivery_summary.return_value = TelegramDeliverySummary(0, 0, 0, 0, 0)
    reporter = OwnerStatusReporter(
        guardian_reader=_guardian(fixed_time),
        conversation_store=InMemoryConversationStore(),
        telegram_store=telegram,
        thread_id=record_id("thread", 1),
        model_id=None,
        model_health=None,
        backup_status_file=marker,
        clock=lambda: fixed_time,
    )

    assert "Backup: invalid" in reporter.render()

    marker.chmod(0o600)
    assert "Backup: stale (48h 0m old)" in reporter.render()


def test_owner_status_reports_selected_route_and_both_targets(fixed_time) -> None:
    telegram = Mock()
    telegram.delivery_summary.return_value = TelegramDeliverySummary(0, 0, 0, 0, 0)
    reporter = OwnerStatusReporter(
        guardian_reader=_guardian(fixed_time),
        conversation_store=InMemoryConversationStore(),
        telegram_store=telegram,
        thread_id=record_id("thread", 1),
        model_id=None,
        model_health=None,
        model_routes=OwnerModelRoutes(
            capable_model_id="capable-v1",
            economy_model_id="economy-v1",
            health=lambda _route: ModelGatewayHealth(
                state=ModelHealthState.HEALTHY,
                checked_at=fixed_time,
                latency_ms=5,
                reason_code="model.endpoint_ready",
            ),
            selected=lambda: ModelRoute.CAPABLE,
        ),
        backup_status_file=None,
        clock=lambda: fixed_time,
    )

    status = reporter.render()

    assert "Route: capable" in status
    assert "Models: economy economy-v1 — healthy; capable capable-v1 — healthy" in status
