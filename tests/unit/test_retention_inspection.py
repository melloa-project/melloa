from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.retention import InMemoryRetentionReader
from melloa.application.retention import (
    OwnerRetentionService,
    RetentionInspectionUnavailableError,
    RetentionOwnershipError,
)
from melloa.apps.core import create_app
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
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
from tests.conftest import record_id

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
