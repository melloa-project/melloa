from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.operations import InMemoryOperationsReader
from melloa.application.inspection import InspectionOwnershipError
from melloa.application.operations import OwnerOperationsService
from melloa.apps.core import create_app
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.classification import Sensitivity
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.operations import (
    ComponentHealth,
    HealthCategory,
    HealthState,
    MediaItemMetadata,
    MediaRetentionState,
    MediaSourceStatus,
    MissingMediaInterval,
    OwnerExportReadinessReport,
    OwnerHealthReport,
    OwnerMediaCatalog,
    aggregate_health_state,
)
from tests.conftest import record_id

_BOOTSTRAP_TOKEN = "synthetic-owner-bootstrap-token-value-0001"


def _principal(fixed_time, owner_number: int = 1) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=record_id("owner", owner_number),
        session_id=record_id("session", owner_number),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )


def _component(fixed_time, *, component_id: str = "application.core") -> ComponentHealth:
    return ComponentHealth(
        component_id=component_id,
        category=HealthCategory.APPLICATION,
        state=HealthState.HEALTHY,
        required=True,
        observed_at=fixed_time,
        summary="Private core healthy.",
        version="0.1.0",
    )


def _source(fixed_time) -> MediaSourceStatus:
    return MediaSourceStatus(
        capability_id="camera.synthetic-room",
        installed=True,
        capture_enabled=True,
        health_state=HealthState.HEALTHY,
        observed_at=fixed_time + timedelta(minutes=2),
        status_reason="camera.synthetic-ready",
        last_capture_at=fixed_time,
    )


def _media(fixed_time) -> MediaItemMetadata:
    return MediaItemMetadata(
        media_id=record_id("media", 1),
        owner_id=record_id("owner", 1),
        source_capability_id="camera.synthetic-room",
        event_id=record_id("event", 1),
        media_type="image/jpeg",
        content_hash="sha256:" + "1" * 64,
        sensitivity=Sensitivity.PERSONAL,
        captured_from=fixed_time,
        captured_to=fixed_time + timedelta(seconds=5),
        interpretation_confidence=0.75,
        retention_policy="retention.synthetic-short",
        retained_at=fixed_time + timedelta(seconds=6),
        expires_at=fixed_time + timedelta(days=1),
        size_bytes=1024,
        retention_state=MediaRetentionState.RETAINED,
        disclosure_record_ids=(record_id("disclosure", 1),),
    )


def _guardian(fixed_time) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NO_ACTIONS,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic-operations",
        ),
        receipt_hash="sha256:" + "2" * 64,
    )


def test_health_and_media_contracts_reject_inconsistent_metadata(fixed_time) -> None:
    component = _component(fixed_time)
    with pytest.raises(ValidationError, match="component IDs must be unique"):
        OwnerHealthReport(
            owner_id=record_id("owner", 1),
            generated_at=fixed_time,
            overall_state=HealthState.HEALTHY,
            components=(component, component),
        )
    backup = ComponentHealth(
        component_id="backup.fixture",
        category=HealthCategory.BACKUP,
        state=HealthState.DISABLED,
        required=False,
        observed_at=fixed_time,
        summary="Fixture backup disabled.",
    )
    with pytest.raises(ValidationError, match="deterministic category/ID order"):
        OwnerHealthReport(
            owner_id=record_id("owner", 1),
            generated_at=fixed_time,
            overall_state=HealthState.HEALTHY,
            components=(backup, component),
        )
    with pytest.raises(ValidationError, match="overall health"):
        OwnerHealthReport(
            owner_id=record_id("owner", 1),
            generated_at=fixed_time,
            overall_state=HealthState.DEGRADED,
            components=(component,),
        )
    with pytest.raises(ValidationError, match="uninstalled media sources"):
        MediaSourceStatus(
            capability_id="camera.not-installed",
            installed=False,
            capture_enabled=True,
            health_state=HealthState.HEALTHY,
            observed_at=fixed_time,
            status_reason="camera.invalid-fixture",
        )
    with pytest.raises(ValidationError, match="enabled media capture"):
        MediaSourceStatus(
            capability_id="camera.disabled",
            installed=True,
            capture_enabled=True,
            health_state=HealthState.DISABLED,
            observed_at=fixed_time,
            status_reason="camera.invalid-fixture",
        )
    with pytest.raises(ValidationError, match="cannot follow"):
        MediaSourceStatus.model_validate(
            {
                **_source(fixed_time).model_dump(),
                "last_capture_at": fixed_time + timedelta(minutes=3),
            }
        )
    with pytest.raises(ValidationError, match="must end after"):
        MissingMediaInterval(
            started_at=fixed_time,
            ended_at=fixed_time,
            reason_code="camera.missing-heartbeat",
        )
    first_gap = MissingMediaInterval(
        started_at=fixed_time,
        ended_at=fixed_time + timedelta(minutes=1),
        reason_code="camera.missing-heartbeat",
    )
    second_gap = MissingMediaInterval(
        started_at=fixed_time + timedelta(minutes=2),
        ended_at=fixed_time + timedelta(minutes=3),
        reason_code="camera.missing-heartbeat",
    )
    with pytest.raises(ValidationError, match="chronological order"):
        MediaSourceStatus.model_validate(
            {
                **_source(fixed_time).model_dump(),
                "missing_intervals": (second_gap, first_gap),
            }
        )
    overlapping_gap = MissingMediaInterval(
        started_at=fixed_time + timedelta(seconds=30),
        ended_at=fixed_time + timedelta(minutes=2),
        reason_code="camera.missing-heartbeat",
    )
    with pytest.raises(ValidationError, match="cannot overlap"):
        MediaSourceStatus.model_validate(
            {
                **_source(fixed_time).model_dump(),
                "missing_intervals": (first_gap, overlapping_gap),
            }
        )
    with pytest.raises(ValidationError, match="cannot precede"):
        MediaItemMetadata.model_validate(
            {
                **_media(fixed_time).model_dump(),
                "captured_to": fixed_time - timedelta(seconds=1),
            }
        )
    with pytest.raises(ValidationError, match="retained before capture"):
        MediaItemMetadata.model_validate(
            {
                **_media(fixed_time).model_dump(),
                "retained_at": fixed_time,
            }
        )
    with pytest.raises(ValidationError, match="expiry must follow"):
        MediaItemMetadata.model_validate(
            {
                **_media(fixed_time).model_dump(),
                "expires_at": fixed_time + timedelta(seconds=6),
            }
        )
    with pytest.raises(ValidationError, match="disclosure record IDs must be unique"):
        MediaItemMetadata.model_validate(
            {
                **_media(fixed_time).model_dump(),
                "disclosure_record_ids": (
                    record_id("disclosure", 1),
                    record_id("disclosure", 1),
                ),
            }
        )
    with pytest.raises(ValidationError, match="unknown source"):
        OwnerMediaCatalog(
            owner_id=record_id("owner", 1),
            generated_at=fixed_time,
            capture_enabled=False,
            sources=(),
            items=(_media(fixed_time),),
        )


def test_export_readiness_contract_rejects_misleading_status(fixed_time) -> None:
    report = OwnerExportReadinessReport(
        owner_id=record_id("owner", 1),
        generated_at=fixed_time,
        cli_command="melloa export-mvp --output-dir <export-dir>",
        validation_command="melloa import-validate --bundle-dir <export-dir>",
        encrypted=False,
        includes_sql_snapshot=False,
        includes_blobs=False,
        coverage=(
            {
                "group_id": "export.conversation-records",
                "included": True,
                "estimated_records": 1,
                "artifact_path": "conversations/*.jsonl",
                "summary": "Canonical conversation records.",
                "status_reason": "export.coverage.conversation-jsonl",
            },
        ),
        validation_checks=(
            {
                "check_id": "export.validation.checksums",
                "implemented": True,
                "summary": "Checksums are verified before records are trusted.",
                "status_reason": "export.validation.checksum-verification",
            },
            {
                "check_id": "export.validation.restore-execution",
                "implemented": False,
                "summary": "Database restore execution remains pending.",
                "status_reason": "export.validation.restore-execution-pending",
            },
        ),
        limitations=(
            "export.blobs-not-included",
            "export.preview-unencrypted",
            "export.sql-snapshot-not-included",
        ),
    )
    assert report.format_id == "melloa.canonical-owner-export"

    with pytest.raises(ValidationError, match="relative and contained"):
        OwnerExportReadinessReport.model_validate(
            {
                **report.model_dump(),
                "coverage": (
                    {
                        **report.coverage[0].model_dump(),
                        "artifact_path": "../secret",
                    },
                ),
            }
        )
    with pytest.raises(ValidationError, match="excluded export groups"):
        OwnerExportReadinessReport.model_validate(
            {
                **report.model_dump(),
                "coverage": (
                    {
                        "group_id": "export.blobs",
                        "included": False,
                        "estimated_records": 1,
                        "summary": "Blobs are excluded.",
                        "status_reason": "export.coverage.blobs-not-included",
                    },
                ),
            }
        )
    with pytest.raises(ValidationError, match="deterministic check order"):
        OwnerExportReadinessReport.model_validate(
            {
                **report.model_dump(),
                "validation_checks": (
                    report.validation_checks[1].model_dump(),
                    report.validation_checks[0].model_dump(),
                ),
            }
        )
    with pytest.raises(ValidationError, match="preview limitation"):
        OwnerExportReadinessReport.model_validate(
            {
                **report.model_dump(),
                "limitations": (
                    "export.blobs-not-included",
                    "export.sql-snapshot-not-included",
                ),
            }
        )
    with pytest.raises(ValidationError, match="deterministic group order"):
        OwnerExportReadinessReport.model_validate(
            {
                **report.model_dump(),
                "coverage": (
                    {
                        "group_id": "export.model-activity",
                        "included": True,
                        "artifact_path": "inspection/model-activity.jsonl",
                        "summary": "Model activity evidence.",
                        "status_reason": "export.coverage.model-activity",
                    },
                    report.coverage[0].model_dump(),
                ),
            }
        )


def test_health_aggregation_distinguishes_required_optional_and_disabled(fixed_time) -> None:
    unavailable = _component(fixed_time).model_copy(
        update={"state": HealthState.UNAVAILABLE}
    )
    assert aggregate_health_state((unavailable,)) is HealthState.UNAVAILABLE
    optional_unavailable = unavailable.model_copy(update={"required": False})
    assert aggregate_health_state((optional_unavailable,)) is HealthState.DEGRADED
    disabled = unavailable.model_copy(
        update={"state": HealthState.DISABLED, "required": False}
    )
    assert aggregate_health_state((disabled,)) is HealthState.DISABLED


def test_owner_operations_service_sorts_and_scopes_reports(fixed_time) -> None:
    reader = InMemoryOperationsReader(
        record_id("owner", 1),
        components=(
            ComponentHealth(
                component_id="storage.fixture",
                category=HealthCategory.STORAGE,
                state=HealthState.DEGRADED,
                required=True,
                observed_at=fixed_time,
                summary="Ephemeral fixture storage.",
            ),
            _component(fixed_time),
        ),
        media_sources=(_source(fixed_time),),
        media_items=(_media(fixed_time),),
    )
    service = OwnerOperationsService(
        owner_id=record_id("owner", 1),
        reader=reader,
        clock=lambda: fixed_time + timedelta(minutes=3),
    )

    health = service.health(_principal(fixed_time))
    assert health.overall_state is HealthState.DEGRADED
    assert health.components[0].category is HealthCategory.APPLICATION
    media = service.media(_principal(fixed_time))
    assert media.capture_enabled is True
    assert media.content_endpoint_available is False
    assert media.items[0].disclosure_record_ids == (record_id("disclosure", 1),)
    export = service.export_readiness(_principal(fixed_time))
    assert export.encrypted is False
    assert export.includes_sql_snapshot is False
    assert export.includes_blobs is False
    assert export.coverage[0].group_id == "export.assertion-inspections"
    assert export.coverage[0].estimated_records == 0
    delivery_coverage = next(
        item for item in export.coverage if item.group_id == "export.delivery-records"
    )
    assert delivery_coverage.estimated_records == 0
    assert delivery_coverage.artifact_path == "conversations/deliveries.jsonl"
    retention_coverage = next(
        item for item in export.coverage if item.group_id == "export.retention-report"
    )
    assert retention_coverage.estimated_records == 0
    assert retention_coverage.artifact_path == "inspection/retention.jsonl"
    assert export.coverage[-2].group_id == "export.schemas-checksums"
    assert export.coverage[-2].estimated_records == 14
    assert export.validation_checks[0].check_id == "export.validation.checksums"
    assert export.validation_checks[0].implemented is True
    assert export.validation_checks[-1].check_id == "export.validation.schemas"
    assert any(not check.implemented for check in export.validation_checks)
    assert "export.preview-unencrypted" in export.limitations
    assert reader.media_sources(record_id("owner", 2)) == ()
    assert reader.media_items(record_id("owner", 2)) == ()
    with pytest.raises(InspectionOwnershipError):
        service.health(_principal(fixed_time, 2))
    with pytest.raises(InspectionOwnershipError):
        service.export_readiness(_principal(fixed_time, 2))
    with pytest.raises(ValueError, match="another owner's records"):
        InMemoryOperationsReader(
            record_id("owner", 2),
            components=(_component(fixed_time),),
            media_items=(_media(fixed_time),),
        )


def test_operational_inspection_api_is_authenticated_and_fail_closed(fixed_time) -> None:
    tokens = iter(("session-token", "csrf-token"))
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    operations = OwnerOperationsService(
        owner_id=record_id("owner", 1),
        reader=InMemoryOperationsReader(
            record_id("owner", 1),
            components=(_component(fixed_time),),
            media_sources=(_source(fixed_time),),
            media_items=(_media(fixed_time),),
        ),
        clock=lambda: fixed_time,
    )
    client = TestClient(
        create_app(_guardian(fixed_time), sessions, operations_service=operations),
        base_url="https://testserver",
    )

    health_endpoint = "/api/v1/inspection/health"
    media_endpoint = "/api/v1/inspection/media"
    export_endpoint = "/api/v1/inspection/export"
    assert client.get(health_endpoint).status_code == 401
    assert client.get(media_endpoint).status_code == 401
    assert client.get(export_endpoint).status_code == 401
    assert client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    ).status_code == 200
    assert client.get(health_endpoint).json()["overall_state"] == "healthy"
    assert client.get(media_endpoint).json()["items"][0]["media_id"] == record_id("media", 1)
    export_payload = client.get(export_endpoint).json()
    assert export_payload["encrypted"] is False
    assert export_payload["coverage"][0]["group_id"] == "export.assertion-inspections"
    assert export_payload["coverage"][0]["estimated_records"] == 0
    assert export_payload["validation_checks"][0]["check_id"] == (
        "export.validation.checksums"
    )
    assert export_payload["validation_checks"][2]["implemented"] is False

    absent = TestClient(
        create_app(_guardian(fixed_time), sessions),
        base_url="https://testserver",
    )
    absent.cookies.update(client.cookies)
    unavailable = absent.get(health_endpoint)
    assert unavailable.status_code == 503
    assert absent.get(export_endpoint).status_code == 503
    assert unavailable.json()["detail"] == (
        "Owner health and media inspection are not configured."
    )

    foreign = OwnerOperationsService(
        owner_id=record_id("owner", 2),
        reader=InMemoryOperationsReader(
            record_id("owner", 2),
            components=(_component(fixed_time),),
        ),
        clock=lambda: fixed_time,
    )
    concealed = TestClient(
        create_app(_guardian(fixed_time), sessions, operations_service=foreign),
        base_url="https://testserver",
    )
    concealed.cookies.update(client.cookies)
    assert concealed.get(media_endpoint).status_code == 404
    assert concealed.get(export_endpoint).status_code == 404
