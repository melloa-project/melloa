from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.delivery import InMemoryDeliveryStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.retention import (
    AuditBackedRetentionReader,
    DeliveryBackedRetentionReader,
    InMemoryRetentionReader,
    MemoryBackedRetentionReader,
    TelegramQuarantineBackedRetentionReader,
)
from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.adapters.fakes.telegram import (
    InMemoryTelegramAttachmentQuarantine,
    SyntheticTelegramAttachmentPayload,
)
from melloa.application.retention import (
    OwnerRetentionService,
    RetentionInspectionUnavailableError,
    RetentionOwnershipError,
)
from melloa.apps.core import create_app
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import canonical_json_bytes
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.memory import Assertion, AssertionStatus
from melloa.domain.retention import (
    BackupExpiryDisclosure,
    BackupExpiryState,
    OwnerRetentionReport,
    RetentionDeletionControl,
    RetentionDeletionScope,
    RetentionDurationBounds,
    RetentionExternalCopyState,
    RetentionInventoryCoverage,
    RetentionInventoryStatus,
    RetentionMode,
    RetentionPolicyStatus,
)
from melloa.domain.telegram import (
    TelegramAttachmentIntakeRequest,
    TelegramAttachmentKind,
    TelegramAttachmentReference,
)
from melloa.ports.memory import AssertionContentDeletionWrite
from tests.conftest import record_id
from tests.unit.test_delivery_work import failed_attempt, work

_BOOTSTRAP_TOKEN = "synthetic-owner-bootstrap-token-value-0001"


def principal(fixed_time: datetime, owner_number: int = 1) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=record_id("owner", owner_number),
        session_id=record_id("session", owner_number),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )


def policy(
    policy_id: str = "retention.synthetic-automatic",
    *,
    automatic: bool = True,
) -> RetentionPolicyStatus:
    return RetentionPolicyStatus(
        policy_id=policy_id,
        data_category="data.synthetic",
        summary="Synthetic retention policy without private content.",
        mode=(
            RetentionMode.AUTOMATIC_EXPIRY
            if automatic
            else RetentionMode.OWNER_LIFECYCLE
        ),
        duration_bounds=(
            RetentionDurationBounds(
                minimum_seconds=3_600,
                default_seconds=86_400,
                maximum_seconds=604_800,
            )
            if automatic
            else None
        ),
        automatic_expiry=automatic,
        deletion_control=(
            RetentionDeletionControl.AUTOMATIC_ONLY
            if automatic
            else RetentionDeletionControl.NOT_IMPLEMENTED
        ),
        tombstone_retained=True,
        derived_rebuild_required=False,
        external_copy_state=RetentionExternalCopyState.NONE,
        status_reason="retention.synthetic",
    )


def inventory(
    policy_id: str = "retention.synthetic-automatic",
) -> RetentionInventoryStatus:
    return RetentionInventoryStatus(
        policy_id=policy_id,
        coverage=RetentionInventoryCoverage.COMPLETE,
        retained_objects=0,
        retained_bytes=0,
        overdue_objects=0,
        pending_deletions=0,
        deletion_receipts=1,
        status_reason="retention.inventory.empty",
    )


def backup() -> BackupExpiryDisclosure:
    return BackupExpiryDisclosure(
        state=BackupExpiryState.NOT_CONFIGURED,
        status_reason="retention.backup.not_configured",
    )


def guardian(fixed_time: datetime) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NO_ACTIONS,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic-retention-inspection",
        ),
        receipt_hash="sha256:" + "8" * 64,
    )


def memory_assertion(
    fixed_time: datetime,
    *,
    assertion_number: int = 1,
    owner_number: int = 1,
) -> Assertion:
    return Assertion(
        assertion_id=record_id("assertion", assertion_number),
        subject_id=record_id("owner", owner_number),
        predicate="owner.preference.synthetic",
        value={"fixture": True, "number": assertion_number},
        epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.PERSONAL,
        observed_at=fixed_time,
    )


def test_retention_contracts_reject_misleading_policy_and_inventory(
    fixed_time: datetime,
) -> None:
    with pytest.raises(ValidationError, match="minimum <= default <= maximum"):
        RetentionDurationBounds(
            minimum_seconds=100,
            default_seconds=50,
            maximum_seconds=200,
        )
    automatic_policy = policy().model_dump()
    automatic_policy["duration_bounds"] = None
    with pytest.raises(ValidationError, match="bounded retention duration"):
        RetentionPolicyStatus(**automatic_policy)
    automatic_policy = policy().model_dump()
    automatic_policy["automatic_expiry"] = False
    automatic_policy["deletion_control"] = RetentionDeletionControl.NOT_IMPLEMENTED
    with pytest.raises(ValidationError, match="must expire automatically"):
        RetentionPolicyStatus(**automatic_policy)
    with pytest.raises(ValidationError, match="at least one scope"):
        RetentionPolicyStatus(
            **{
                **policy(automatic=False).model_dump(),
                "deletion_control": RetentionDeletionControl.OWNER_REQUEST,
            }
        )
    with pytest.raises(ValidationError, match="deterministic order"):
        RetentionPolicyStatus(
            **{
                **policy(automatic=False).model_dump(),
                "deletion_control": RetentionDeletionControl.OWNER_REQUEST,
                "owner_deletion_scopes": (
                    RetentionDeletionScope.TIME_RANGE,
                    RetentionDeletionScope.RAW_OBJECT,
                ),
            }
        )
    with pytest.raises(ValidationError, match="every count"):
        RetentionInventoryStatus(
            policy_id="retention.synthetic-automatic",
            coverage=RetentionInventoryCoverage.COMPLETE,
            retained_objects=0,
            status_reason="retention.inventory.invalid",
        )
    with pytest.raises(ValidationError, match="cannot claim measurements"):
        RetentionInventoryStatus(
            policy_id="retention.synthetic-automatic",
            coverage=RetentionInventoryCoverage.UNAVAILABLE,
            retained_objects=0,
            status_reason="retention.inventory.invalid",
        )
    with pytest.raises(ValidationError, match="cannot exceed"):
        RetentionInventoryStatus(
            **{
                **inventory().model_dump(),
                "retained_objects": 1,
                "overdue_objects": 2,
                "oldest_retained_at": fixed_time,
            }
        )


def test_backup_and_report_contracts_require_honest_complete_coverage(
    fixed_time: datetime,
) -> None:
    with pytest.raises(ValidationError, match="maximum retention"):
        BackupExpiryDisclosure(
            state=BackupExpiryState.CONFIGURED,
            status_reason="retention.backup.configured",
        )
    with pytest.raises(ValidationError, match="cannot claim a horizon"):
        BackupExpiryDisclosure(
            state=BackupExpiryState.UNKNOWN,
            status_reason="retention.backup.unknown",
            latest_snapshot_at=fixed_time,
        )
    with pytest.raises(ValidationError, match="every reported policy"):
        OwnerRetentionReport(
            owner_id=record_id("owner", 1),
            generated_at=fixed_time,
            policies=(policy(),),
            inventory=(inventory("retention.other"),),
            backup_expiry=backup(),
        )


def test_retention_service_sorts_scopes_and_conceals_other_owners(
    fixed_time: datetime,
) -> None:
    first_policy = policy("retention.a", automatic=False)
    second_policy = policy("retention.z")
    reader = InMemoryRetentionReader(
        record_id("owner", 1),
        policies=(second_policy, first_policy),
        inventory=(inventory("retention.z"), inventory("retention.a")),
        backup_expiry=backup(),
    )
    service = OwnerRetentionService(
        owner_id=record_id("owner", 1),
        reader=reader,
        clock=lambda: fixed_time,
    )

    report = service.report(principal(fixed_time))

    assert tuple(item.policy_id for item in report.policies) == (
        "retention.a",
        "retention.z",
    )
    assert report.backup_expiry.state is BackupExpiryState.NOT_CONFIGURED
    assert reader.policies(record_id("owner", 2)) == ()
    assert reader.inventory(record_id("owner", 2)) == ()
    assert reader.backup_expiry(record_id("owner", 2)) is None
    with pytest.raises(RetentionOwnershipError):
        service.report(principal(fixed_time, 2))
    with pytest.raises(ValueError, match="cover every policy"):
        InMemoryRetentionReader(
            record_id("owner", 1),
            policies=(first_policy,),
            inventory=(inventory("retention.z"),),
            backup_expiry=backup(),
        )


def test_memory_backed_retention_reader_counts_canonical_assertion_content(
    fixed_time: datetime,
) -> None:
    owner_id = record_id("owner", 1)
    owned = memory_assertion(fixed_time)
    foreign = memory_assertion(
        fixed_time + timedelta(minutes=1),
        assertion_number=2,
        owner_number=2,
    )
    repository = InMemoryMemoryRepository((owned, foreign))
    reader = MemoryBackedRetentionReader(
        InMemoryRetentionReader(
            owner_id,
            policies=(policy("retention.owner-memory", automatic=False),),
            inventory=(inventory("retention.owner-memory"),),
            backup_expiry=backup(),
        ),
        repository,
    )

    item = reader.inventory(owner_id)[0]

    assert item.policy_id == "retention.owner-memory"
    assert item.coverage is RetentionInventoryCoverage.COMPLETE
    assert item.retained_objects == 1
    assert item.retained_bytes == len(canonical_json_bytes(owned.value))
    assert item.deletion_receipts == 0
    assert item.oldest_retained_at == fixed_time

    repository.delete_assertion_content(
        AssertionContentDeletionWrite(
            assertion_id=owned.assertion_id,
            owner_id=owner_id,
            tombstone_id=record_id("deletion", 1),
            rebuild_work_id=record_id("work", 1),
            deleted_by_record_id=owner_id,
            deleted_at=fixed_time + timedelta(minutes=2),
            reason_code="memory.assertion-content-owner-deleted",
        )
    )
    after_delete = reader.inventory(owner_id)[0]

    assert after_delete.retained_objects == 0
    assert after_delete.retained_bytes == 0
    assert after_delete.deletion_receipts == 1
    assert after_delete.oldest_retained_at is None
    assert reader.inventory(record_id("owner", 2)) == ()


def test_audit_backed_retention_reader_counts_append_store(
    event,
    audit_content,
) -> None:
    owner_id = record_id("owner", 1)
    store = InMemoryEventAuditStore()
    reader = AuditBackedRetentionReader(
        InMemoryRetentionReader(
            owner_id,
            policies=(policy("retention.audit-ledger", automatic=False),),
            inventory=(inventory("retention.audit-ledger"),),
            backup_expiry=backup(),
        ),
        owner_id,
        store,
    )

    empty = reader.inventory(owner_id)[0]
    assert empty.coverage is RetentionInventoryCoverage.COMPLETE
    assert empty.retained_objects == 0
    assert empty.retained_bytes == 0
    assert empty.status_reason == "retention.inventory.audit_event_store"

    store.append_event(event, audit_content)
    item = reader.inventory(owner_id)[0]

    assert item.policy_id == "retention.audit-ledger"
    assert item.coverage is RetentionInventoryCoverage.COMPLETE
    assert item.retained_objects == 1
    assert item.retained_bytes is not None and item.retained_bytes > 0
    assert item.deletion_receipts == 0
    assert item.oldest_retained_at == audit_content.occurred_at
    assert reader.inventory(record_id("owner", 2)) == ()


def test_delivery_backed_retention_reader_counts_owner_delivery_history(
    fixed_time: datetime,
) -> None:
    owner_id = record_id("owner", 1)
    delivery_store = InMemoryDeliveryStore()
    delivery_work = work(fixed_time)
    delivery_store.enqueue(delivery_work, max_attempts=1)
    claim = delivery_store.claim_work(
        delivery_work.work_id,
        lease_owner=record_id("worker", 1),
        now=fixed_time,
        lease_expires_at=fixed_time + timedelta(seconds=1),
    )
    assert claim is not None
    delivery_store.record_failure(
        claim,
        failed_attempt(
            delivery_work,
            attempt=1,
            started_at=fixed_time,
            terminal=True,
        ),
    )
    reader = DeliveryBackedRetentionReader(
        InMemoryRetentionReader(
            owner_id,
            policies=(policy("retention.owner-delivery", automatic=False),),
            inventory=(inventory("retention.owner-delivery"),),
            backup_expiry=backup(),
        ),
        delivery_store,
    )

    item = reader.inventory(owner_id)[0]

    assert item.policy_id == "retention.owner-delivery"
    assert item.coverage is RetentionInventoryCoverage.COMPLETE
    assert item.retained_objects == 2
    assert item.retained_bytes is not None and item.retained_bytes > 0
    assert item.deletion_receipts == 0
    assert item.oldest_retained_at == fixed_time
    assert item.status_reason == "retention.inventory.owner_delivery"
    assert reader.inventory(record_id("owner", 2)) == ()


def test_telegram_quarantine_backed_retention_reader_counts_backend_inventory(
    fixed_time: datetime,
) -> None:
    owner_id = record_id("owner", 1)
    backend = InMemoryTelegramAttachmentQuarantine(
        {
            "unique-file-1": SyntheticTelegramAttachmentPayload(
                content=b"abc",
                media_type="text/plain",
            )
        },
        owner_id=owner_id,
        allowed_kinds=frozenset({TelegramAttachmentKind.DOCUMENT}),
        allowed_media_types=frozenset({"text/plain"}),
        max_attachment_bytes=16,
        max_quarantine_bytes=16,
        retention_ttl=timedelta(hours=1),
        clock=lambda: fixed_time,
    )
    reader = TelegramQuarantineBackedRetentionReader(
        InMemoryRetentionReader(
            owner_id,
            policies=(policy("retention.telegram-quarantine"),),
            inventory=(inventory("retention.telegram-quarantine"),),
            backup_expiry=backup(),
        ),
        backend,
    )

    backend.handle(
        TelegramAttachmentIntakeRequest(
            adapter_id="telegram.synthetic",
            update_id=1,
            update_fingerprint="sha256:" + "1" * 64,
            received_at=fixed_time,
            attachments=(
                TelegramAttachmentReference(
                    kind=TelegramAttachmentKind.DOCUMENT,
                    file_id="provider-file-1",
                    file_unique_id="unique-file-1",
                    declared_size_bytes=3,
                    media_type="text/plain; charset=utf-8",
                    file_name="note.txt",
                ),
            ),
        )
    )
    item = reader.inventory(owner_id)[0]

    assert item.policy_id == "retention.telegram-quarantine"
    assert item.coverage is RetentionInventoryCoverage.COMPLETE
    assert item.retained_objects == 1
    assert item.retained_bytes == 3
    assert item.deletion_receipts == 0
    assert item.oldest_retained_at == fixed_time

    backend.sweep_expired(as_of=fixed_time + timedelta(hours=1), limit=10)
    after_expiry = reader.inventory(owner_id)[0]

    assert after_expiry.retained_objects == 0
    assert after_expiry.retained_bytes == 0
    assert after_expiry.deletion_receipts == 1
    assert after_expiry.oldest_retained_at is None
    assert reader.inventory(record_id("owner", 2)) == ()


class IncompleteRetentionReader:
    def policies(self, _owner_id: str) -> tuple[RetentionPolicyStatus, ...]:
        return (policy(),)

    def inventory(self, _owner_id: str) -> tuple[RetentionInventoryStatus, ...]:
        return (inventory(),)

    def backup_expiry(self, _owner_id: str) -> None:
        return None


def test_retention_inspection_api_is_authenticated_and_fail_closed(
    fixed_time: datetime,
) -> None:
    tokens = iter(("session-token", "csrf-token"))
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    retention = OwnerRetentionService(
        owner_id=record_id("owner", 1),
        reader=InMemoryRetentionReader(
            record_id("owner", 1),
            policies=(policy(),),
            inventory=(inventory(),),
            backup_expiry=backup(),
        ),
        clock=lambda: fixed_time,
    )
    client = TestClient(
        create_app(
            guardian(fixed_time),
            sessions,
            retention_service=retention,
        ),
        base_url="https://testserver",
    )
    endpoint = "/api/v1/retention"

    assert client.get(endpoint).status_code == 401
    assert client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    ).status_code == 200
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json()["policies"][0]["deletion_control"] == "automatic-only"
    assert response.json()["backup_expiry"]["state"] == "not-configured"

    absent = TestClient(
        create_app(guardian(fixed_time), sessions),
        base_url="https://testserver",
    )
    absent.cookies.update(client.cookies)
    unavailable = absent.get(endpoint)
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == "Owner retention inspection is not configured."

    foreign = TestClient(
        create_app(
            guardian(fixed_time),
            sessions,
            retention_service=OwnerRetentionService(
                owner_id=record_id("owner", 2),
                reader=InMemoryRetentionReader(
                    record_id("owner", 2),
                    policies=(policy(),),
                    inventory=(inventory(),),
                    backup_expiry=backup(),
                ),
                clock=lambda: fixed_time,
            ),
        ),
        base_url="https://testserver",
    )
    foreign.cookies.update(client.cookies)
    assert foreign.get(endpoint).status_code == 404

    incomplete = TestClient(
        create_app(
            guardian(fixed_time),
            sessions,
            retention_service=OwnerRetentionService(
                owner_id=record_id("owner", 1),
                reader=IncompleteRetentionReader(),
                clock=lambda: fixed_time,
            ),
        ),
        base_url="https://testserver",
    )
    incomplete.cookies.update(client.cookies)
    result = incomplete.get(endpoint)
    assert result.status_code == 503
    assert result.json()["code"] == "retention_inspection_unavailable"
    with pytest.raises(RetentionInspectionUnavailableError):
        OwnerRetentionService(
            owner_id=record_id("owner", 1),
            reader=IncompleteRetentionReader(),
            clock=lambda: fixed_time,
        ).report(principal(fixed_time))
