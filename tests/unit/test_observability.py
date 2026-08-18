from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from melloa.application.telemetry import BestEffortTelemetry
from melloa.domain.observability import (
    M1_OWNER_API_AUDIT_CONTRACT,
    M1_OWNER_API_AUDIT_CONTRACT_SCOPE,
    AtomicityClaim,
    AuditContractCategory,
    AuditContractRow,
    AuditOrdering,
    AuditPresence,
    AuditTruthSource,
    DiagnosticComponent,
    DiagnosticReason,
    DiagnosticResult,
    DiagnosticSignal,
    DiagnosticSignalKind,
    Durability,
    ObservabilityContractError,
    OwnerVisibleDetection,
    RetryRepairBehavior,
    SameTransactionBoundary,
    SourceDisposition,
    SourceOutcomeOnAuditFailure,
    StableReplayPath,
    validate_audit_contract,
)
from melloa.ports.telemetry import TelemetrySink


def _row(
    category: AuditContractCategory = AuditContractCategory.MEMORY_CORRECT,
) -> AuditContractRow:
    return AuditContractRow(
        category=category,
        implementation="synthetic test row",
        source_disposition=SourceDisposition.ACCEPTED_MUTATION,
        ordering=AuditOrdering.SOURCE_BEFORE_AUDIT,
        atomicity=AtomicityClaim.NONE,
        audit_presence=AuditPresence.OWNER_API_EVENT,
        audit_truth_source=AuditTruthSource.EVENT_AUDIT_STORE,
        source_durability=(Durability.PROCESS_LOCAL,),
        audit_durability=(Durability.PROCESS_LOCAL,),
        source_outcome_on_audit_failure=SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
        retry_repair=RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
        owner_visible_detection=(OwnerVisibleDetection.API_ERROR,),
    )


def _contract_with_replacement(
    category: AuditContractCategory,
    replacement: dict[str, object],
) -> tuple[AuditContractRow, ...]:
    return tuple(
        row.model_copy(update=replacement) if row.category is category else row
        for row in M1_OWNER_API_AUDIT_CONTRACT
    )


def test_m1_audit_contract_is_exhaustive_for_named_owner_api_scope() -> None:
    rows = validate_audit_contract(M1_OWNER_API_AUDIT_CONTRACT)

    assert {row.category for row in rows} == set(AuditContractCategory)
    assert M1_OWNER_API_AUDIT_CONTRACT_SCOPE.scope_id == (
        "observability.m1-owner-api-audit-contract"
    )
    assert M1_OWNER_API_AUDIT_CONTRACT_SCOPE.excludes == (
        "automatic retention sweeps",
        "queue workers",
        "every repository mutation outside the named M1 owner/API audit-contract scope",
    )


@pytest.mark.parametrize(
    (
        "category",
        "source_disposition",
        "ordering",
        "failure_outcome",
        "repair",
        "replay_path",
    ),
    (
        (
            AuditContractCategory.PROCESS_LOCAL_SESSION_ISSUE,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.AUDIT_BEFORE_SOURCE,
            SourceOutcomeOnAuditFailure.SOURCE_NOT_MUTATED,
            RetryRepairBehavior.NOT_NEEDED,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.PROCESS_LOCAL_SESSION_REVOKE,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.AUDIT_BEFORE_SOURCE,
            SourceOutcomeOnAuditFailure.SOURCE_NOT_MUTATED,
            RetryRepairBehavior.IDEMPOTENT_REPLAY,
            StableReplayPath.CURRENT_SESSION_REVOCATION_REQUEST,
        ),
        (
            AuditContractCategory.PROCESS_LOCAL_SESSION_REVOKE_OTHERS,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.AUDIT_BEFORE_SOURCE,
            SourceOutcomeOnAuditFailure.PARTIAL_AUDIT_SOURCE_UNCHANGED,
            RetryRepairBehavior.MANUAL_RECONCILIATION,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.POSTGRESQL_SESSION_ISSUE,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_AND_AUDIT_SAME_TRANSACTION,
            SourceOutcomeOnAuditFailure.SOURCE_ROLLED_BACK,
            RetryRepairBehavior.NOT_NEEDED,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.POSTGRESQL_SESSION_REVOKE,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_AND_AUDIT_SAME_TRANSACTION,
            SourceOutcomeOnAuditFailure.SOURCE_ROLLED_BACK,
            RetryRepairBehavior.NOT_NEEDED,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.POSTGRESQL_SESSION_REVOKE_OTHERS,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_AND_AUDIT_SAME_TRANSACTION,
            SourceOutcomeOnAuditFailure.SOURCE_ROLLED_BACK,
            RetryRepairBehavior.NOT_NEEDED,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.CONVERSATION_THREAD_CREATE,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_ONLY_UNAUDITED,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS_WITHOUT_AUTOMATIC_REPAIR,
            RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.CONVERSATION_OWNER_MESSAGE_ACCEPT,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
            RetryRepairBehavior.IDEMPOTENT_REPLAY,
            StableReplayPath.OWNER_MESSAGE_IDEMPOTENCY_KEY,
        ),
        (
            AuditContractCategory.CONVERSATION_OWNER_MESSAGE_RESUME,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
            RetryRepairBehavior.RESUME_REPLAY,
            StableReplayPath.OWNER_MESSAGE_ID,
        ),
        (
            AuditContractCategory.DELIVERY_OWNER_ENQUEUE,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
            RetryRepairBehavior.IDEMPOTENT_REPLAY,
            StableReplayPath.DELIVERY_IDEMPOTENCY_KEY,
        ),
        (
            AuditContractCategory.DELIVERY_OWNER_RESUME,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
            RetryRepairBehavior.RESUME_REPLAY,
            StableReplayPath.DELIVERY_WORK_ID,
        ),
        (
            AuditContractCategory.MEMORY_CONTENT_DELETE,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
            RetryRepairBehavior.IDEMPOTENT_REPLAY,
            StableReplayPath.MEMORY_DELETION_TOMBSTONE,
        ),
        (
            AuditContractCategory.MEMORY_CORRECT,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS_WITHOUT_AUTOMATIC_REPAIR,
            RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.MEMORY_DISPUTE,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS_WITHOUT_AUTOMATIC_REPAIR,
            RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.MEMORY_RETRACT,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS_WITHOUT_AUTOMATIC_REPAIR,
            RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.TELEGRAM_PAIRING_CONFIRM,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
            RetryRepairBehavior.IDEMPOTENT_REPLAY,
            StableReplayPath.TELEGRAM_PAIRING_ID,
        ),
        (
            AuditContractCategory.TELEGRAM_PAIRING_REVOKE,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
            RetryRepairBehavior.IDEMPOTENT_REPLAY,
            StableReplayPath.TELEGRAM_PAIRING_ID,
        ),
        (
            AuditContractCategory.EXPORT_PREVIEW_GENERATE,
            SourceDisposition.ACCEPTED_MUTATION,
            AuditOrdering.SOURCE_BEFORE_AUDIT,
            SourceOutcomeOnAuditFailure.EPHEMERAL_ARCHIVE_DISCARDED,
            RetryRepairBehavior.FRESH_RETRY,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.INVALID_LOGIN_DENIAL,
            SourceDisposition.NO_SOURCE_DENIAL,
            AuditOrdering.AUDIT_ONLY_NO_SOURCE,
            SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION,
            RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.MISSING_SESSION_DENIAL,
            SourceDisposition.NO_SOURCE_DENIAL,
            AuditOrdering.AUDIT_ONLY_NO_SOURCE,
            SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION,
            RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.EXPIRED_SESSION_DENIAL,
            SourceDisposition.NO_SOURCE_DENIAL,
            AuditOrdering.AUDIT_ONLY_NO_SOURCE,
            SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION,
            RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.CSRF_DENIAL,
            SourceDisposition.NO_SOURCE_DENIAL,
            AuditOrdering.AUDIT_ONLY_NO_SOURCE,
            SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION,
            RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
            StableReplayPath.NONE,
        ),
        (
            AuditContractCategory.RECENT_AUTH_DENIAL,
            SourceDisposition.NO_SOURCE_DENIAL,
            AuditOrdering.AUDIT_ONLY_NO_SOURCE,
            SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION,
            RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
            StableReplayPath.NONE,
        ),
    ),
)
def test_contract_rows_encode_current_failure_semantics(
    category: AuditContractCategory,
    source_disposition: SourceDisposition,
    ordering: AuditOrdering,
    failure_outcome: SourceOutcomeOnAuditFailure,
    repair: RetryRepairBehavior,
    replay_path: StableReplayPath,
) -> None:
    row = next(item for item in M1_OWNER_API_AUDIT_CONTRACT if item.category is category)

    assert row.source_disposition is source_disposition
    assert row.ordering is ordering
    assert row.source_outcome_on_audit_failure is failure_outcome
    assert row.retry_repair is repair
    assert row.stable_replay_path is replay_path


def test_contract_distinguishes_process_local_postgres_and_ephemeral_durability() -> None:
    by_category = {row.category: row for row in M1_OWNER_API_AUDIT_CONTRACT}

    assert by_category[AuditContractCategory.PROCESS_LOCAL_SESSION_ISSUE].source_durability == (
        Durability.PROCESS_LOCAL,
    )
    postgres_categories = {
        AuditContractCategory.POSTGRESQL_SESSION_ISSUE,
        AuditContractCategory.POSTGRESQL_SESSION_REVOKE,
        AuditContractCategory.POSTGRESQL_SESSION_REVOKE_OTHERS,
    }
    assert all(
        by_category[category].atomicity is AtomicityClaim.SAME_TRANSACTION
        for category in postgres_categories
    )
    assert all(
        by_category[category].source_durability == (Durability.POSTGRESQL,)
        for category in postgres_categories
    )
    assert by_category[AuditContractCategory.EXPORT_PREVIEW_GENERATE].source_durability == (
        Durability.EPHEMERAL_FILESYSTEM,
    )


def test_contract_distinguishes_accepted_mutations_from_no_source_denials() -> None:
    denials = tuple(
        row
        for row in M1_OWNER_API_AUDIT_CONTRACT
        if row.source_disposition is SourceDisposition.NO_SOURCE_DENIAL
    )

    assert {row.category for row in denials} == {
        AuditContractCategory.INVALID_LOGIN_DENIAL,
        AuditContractCategory.MISSING_SESSION_DENIAL,
        AuditContractCategory.EXPIRED_SESSION_DENIAL,
        AuditContractCategory.CSRF_DENIAL,
        AuditContractCategory.RECENT_AUTH_DENIAL,
    }
    assert all(row.source_durability == () for row in denials)
    assert all(row.ordering is AuditOrdering.AUDIT_ONLY_NO_SOURCE for row in denials)
    assert all(row.retry_repair is RetryRepairBehavior.NO_AUTOMATIC_REPAIR for row in denials)
    assert all(
        row.source_disposition is SourceDisposition.ACCEPTED_MUTATION and row.source_durability
        for row in M1_OWNER_API_AUDIT_CONTRACT
        if row not in denials
    )


def test_contract_validation_rejects_duplicate_missing_collapsed_and_overclaimed_rows() -> None:
    duplicate = (*M1_OWNER_API_AUDIT_CONTRACT, M1_OWNER_API_AUDIT_CONTRACT[0])
    with pytest.raises(ObservabilityContractError, match="duplicate"):
        validate_audit_contract(duplicate)

    with pytest.raises(ObservabilityContractError, match="missing"):
        validate_audit_contract(M1_OWNER_API_AUDIT_CONTRACT[:-1])

    collapsed = _contract_with_replacement(
        AuditContractCategory.PROCESS_LOCAL_SESSION_ISSUE,
        {"source_durability": (Durability.PROCESS_LOCAL, Durability.POSTGRESQL)},
    )
    with pytest.raises(ObservabilityContractError, match="collapsed or overclaimed"):
        validate_audit_contract(collapsed)

    overclaimed = _contract_with_replacement(
        AuditContractCategory.CONVERSATION_THREAD_CREATE,
        {
            "audit_presence": AuditPresence.OWNER_API_EVENT,
            "audit_truth_source": AuditTruthSource.EVENT_AUDIT_STORE,
            "audit_durability": (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        },
    )
    with pytest.raises(ObservabilityContractError, match="collapsed or overclaimed"):
        validate_audit_contract(overclaimed)

    expanded_scope = M1_OWNER_API_AUDIT_CONTRACT_SCOPE.model_copy(
        update={"includes": (*M1_OWNER_API_AUDIT_CONTRACT_SCOPE.includes, "all mutations")}
    )
    with pytest.raises(ObservabilityContractError, match="overclaims"):
        validate_audit_contract(M1_OWNER_API_AUDIT_CONTRACT, scope=expanded_scope)


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        ({"audit_truth_source": AuditTruthSource.TELEMETRY_DIAGNOSTIC}, "telemetry"),
        (
            {
                "atomicity": AtomicityClaim.SAME_TRANSACTION,
                "ordering": AuditOrdering.SOURCE_AND_AUDIT_SAME_TRANSACTION,
            },
            "transaction boundary",
        ),
        (
            {
                "retry_repair": RetryRepairBehavior.IDEMPOTENT_REPLAY,
                "stable_replay_path": StableReplayPath.NONE,
            },
            "stable replay path",
        ),
        (
            {
                "audit_presence": AuditPresence.NONE,
                "audit_truth_source": AuditTruthSource.NONE,
                "audit_durability": (Durability.POSTGRESQL,),
            },
            "unaudited",
        ),
        (
            {
                "source_outcome_on_audit_failure": (
                    SourceOutcomeOnAuditFailure.PARTIAL_AUDIT_SOURCE_UNCHANGED
                ),
                "ordering": AuditOrdering.SOURCE_AND_AUDIT_SAME_TRANSACTION,
                "atomicity": AtomicityClaim.SAME_TRANSACTION,
                "same_transaction_boundary": (
                    SameTransactionBoundary.POSTGRES_OWNER_SESSION_TRANSACTION
                ),
            },
            "partial-audit gap",
        ),
    ),
)
def test_contract_validation_rejects_false_audit_semantics(
    replacement: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ObservabilityContractError, match=message):
        validate_audit_contract(
            _contract_with_replacement(AuditContractCategory.MEMORY_CONTENT_DELETE, replacement)
        )


def test_diagnostic_signal_rejects_unbounded_or_sensitive_shapes() -> None:
    signal = DiagnosticSignal(
        kind=DiagnosticSignalKind.OPERATION_OBSERVED,
        component=DiagnosticComponent.CONVERSATION_SERVICE,
        result=DiagnosticResult.ACCEPTED,
        reason=DiagnosticReason.SOURCE_OPERATION_COMPLETED,
    )
    assert signal.model_dump() == {
        "kind": "operation-observed",
        "component": "conversation-service",
        "result": "accepted",
        "reason": "source-operation-completed",
    }
    assert set(DiagnosticSignal.model_fields) == {
        "kind",
        "component",
        "result",
        "reason",
    }
    assert set(DiagnosticSignalKind) == {DiagnosticSignalKind.OPERATION_OBSERVED}
    assert set(DiagnosticResult) == {DiagnosticResult.ACCEPTED}
    assert set(DiagnosticReason) == {DiagnosticReason.SOURCE_OPERATION_COMPLETED}

    forbidden_payloads = (
        {"labels": {"owner_id": "owner_00000000000000000000000000000001"}},
        {"attributes": {"exception": "stack trace with a path"}},
        {"owner_id": "owner_00000000000000000000000000000001"},
        {"session_id": "session_00000000000000000000000000000001"},
        {"message_id": "message_00000000000000000000000000000001"},
        {"prompt": "private prompt"},
        {"exception_text": "private exception"},
        {"url": "https://example.test/private"},
        {"path": "/private/path"},
        {"credentials": "secret"},
        {"destination": "owner phone"},
        {"provider_response": "raw provider body"},
    )
    base = signal.model_dump()
    for payload in forbidden_payloads:
        with pytest.raises(ValidationError):
            DiagnosticSignal.model_validate({**base, **payload})

    with pytest.raises(ValidationError):
        DiagnosticSignal.model_validate({**base, "component": "arbitrary-component"})


def test_telemetry_sink_protocol_has_no_audit_api() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(TelemetrySink)
        if inspect.isfunction(value) and not name.startswith("_")
    }

    assert public_methods == {"emit"}
    assert all("audit" not in name and "append" not in name for name in public_methods)

    helper_methods = {
        name
        for name, value in inspect.getmembers(BestEffortTelemetry)
        if (inspect.isfunction(value) or isinstance(value, property)) and not name.startswith("_")
    }
    assert helper_methods == {
        "emit",
        "failed_emissions",
        "observe_accepted_operation",
    }
    assert all("audit" not in name and "append" not in name for name in helper_methods)


class _ThrowingSink:
    def emit(self, _signal: DiagnosticSignal) -> None:
        raise RuntimeError("sink is unavailable")


def test_best_effort_telemetry_cannot_block_source_or_forge_audit_evidence() -> None:
    telemetry = BestEffortTelemetry(_ThrowingSink())
    source_mutations: list[str] = []
    audit_evidence: list[str] = []

    result = telemetry.observe_accepted_operation(
        lambda: source_mutations.append("accepted") or "source-result",
        component=DiagnosticComponent.OWNER_API,
    )

    assert result == "source-result"
    assert source_mutations == ["accepted"]
    assert audit_evidence == []
    assert telemetry.failed_emissions == 1
