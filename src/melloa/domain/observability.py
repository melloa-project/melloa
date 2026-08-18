"""Static audit-truth and bounded diagnostic signal contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from melloa.domain.base import ContractModel, NonEmptyText, QualifiedName


class AuditContractCategory(StrEnum):
    PROCESS_LOCAL_SESSION_ISSUE = "process-local-session-issue"
    PROCESS_LOCAL_SESSION_REVOKE = "process-local-session-revoke"
    PROCESS_LOCAL_SESSION_REVOKE_OTHERS = "process-local-session-revoke-others"
    POSTGRESQL_SESSION_ISSUE = "postgresql-session-issue"
    POSTGRESQL_SESSION_REVOKE = "postgresql-session-revoke"
    POSTGRESQL_SESSION_REVOKE_OTHERS = "postgresql-session-revoke-others"
    CONVERSATION_THREAD_CREATE = "conversation-thread-create"
    CONVERSATION_OWNER_MESSAGE_ACCEPT = "conversation-owner-message-accept"
    CONVERSATION_OWNER_MESSAGE_RESUME = "conversation-owner-message-resume"
    DELIVERY_OWNER_ENQUEUE = "delivery-owner-enqueue"
    DELIVERY_OWNER_RESUME = "delivery-owner-resume"
    MEMORY_CONTENT_DELETE = "memory-content-delete"
    MEMORY_CORRECT = "memory-correct"
    MEMORY_DISPUTE = "memory-dispute"
    MEMORY_RETRACT = "memory-retract"
    TELEGRAM_PAIRING_CONFIRM = "telegram-pairing-confirm"
    TELEGRAM_PAIRING_REVOKE = "telegram-pairing-revoke"
    EXPORT_PREVIEW_GENERATE = "export-preview-generate"
    INVALID_LOGIN_DENIAL = "invalid-login-denial"
    MISSING_SESSION_DENIAL = "missing-session-denial"
    EXPIRED_SESSION_DENIAL = "expired-session-denial"
    CSRF_DENIAL = "csrf-denial"
    RECENT_AUTH_DENIAL = "recent-auth-denial"


class AuditOrdering(StrEnum):
    AUDIT_BEFORE_SOURCE = "audit-before-source"
    SOURCE_AND_AUDIT_SAME_TRANSACTION = "source-and-audit-same-transaction"
    SOURCE_BEFORE_AUDIT = "source-before-audit"
    AUDIT_ONLY_NO_SOURCE = "audit-only-no-source"
    SOURCE_ONLY_UNAUDITED = "source-only-unaudited"


class SourceDisposition(StrEnum):
    ACCEPTED_MUTATION = "accepted-mutation"
    NO_SOURCE_DENIAL = "no-source-denial"


class AuditPresence(StrEnum):
    NONE = "none"
    SECURITY_DENIAL_EVENT = "security-denial-event"
    OWNER_API_EVENT = "owner-api-event"
    SESSION_LIFECYCLE_EVENT = "session-lifecycle-event"


class AuditTruthSource(StrEnum):
    NONE = "none"
    EVENT_AUDIT_STORE = "event-audit-store"
    TELEMETRY_DIAGNOSTIC = "telemetry-diagnostic"


class Durability(StrEnum):
    PROCESS_LOCAL = "process-local"
    POSTGRESQL = "postgresql"
    EPHEMERAL_FILESYSTEM = "ephemeral-filesystem"


class SourceOutcomeOnAuditFailure(StrEnum):
    NO_SOURCE_MUTATION = "no-source-mutation"
    SOURCE_NOT_MUTATED = "source-not-mutated"
    SOURCE_ROLLED_BACK = "source-rolled-back"
    SOURCE_PERSISTS = "source-persists"
    SOURCE_PERSISTS_WITHOUT_AUTOMATIC_REPAIR = "source-persists-without-automatic-repair"
    PARTIAL_AUDIT_SOURCE_UNCHANGED = "partial-audit-source-unchanged"
    EPHEMERAL_ARCHIVE_DISCARDED = "ephemeral-archive-discarded"


class AtomicityClaim(StrEnum):
    NONE = "none"
    SAME_TRANSACTION = "same-transaction"


class SameTransactionBoundary(StrEnum):
    NONE = "none"
    POSTGRES_OWNER_SESSION_TRANSACTION = "postgres-owner-session-transaction"


class RetryRepairBehavior(StrEnum):
    NOT_NEEDED = "not-needed"
    IDEMPOTENT_REPLAY = "idempotent-replay"
    RESUME_REPLAY = "resume-replay"
    FRESH_RETRY = "fresh-retry"
    NO_AUTOMATIC_REPAIR = "no-automatic-repair"
    MANUAL_RECONCILIATION = "manual-reconciliation"


class StableReplayPath(StrEnum):
    NONE = "none"
    CURRENT_SESSION_REVOCATION_REQUEST = "current-session-revocation-request"
    OWNER_MESSAGE_IDEMPOTENCY_KEY = "owner-message-idempotency-key"
    OWNER_MESSAGE_ID = "owner-message-id"
    DELIVERY_IDEMPOTENCY_KEY = "delivery-idempotency-key"
    DELIVERY_WORK_ID = "delivery-work-id"
    MEMORY_DELETION_TOMBSTONE = "memory-deletion-tombstone"
    TELEGRAM_PAIRING_ID = "telegram-pairing-id"


class OwnerVisibleDetection(StrEnum):
    API_ERROR = "api-error"
    RETRY_RETURNS_DUPLICATE = "retry-returns-duplicate"
    INSPECTION_VIEW = "inspection-view"
    TIMELINE_AUDIT_PROJECTION = "timeline-audit-projection"
    ACTIVE_SESSION_LIST = "active-session-list"
    MEMORY_INSPECTION = "memory-inspection"
    TELEGRAM_STATUS = "telegram-status"
    EXPORT_DOWNLOAD_SUPPRESSED = "export-download-suppressed"
    SECURITY_DENIAL_RESPONSE = "security-denial-response"
    NONE = "none"


class AuditContractScope(ContractModel):
    scope_id: QualifiedName
    includes: tuple[NonEmptyText, ...]
    excludes: tuple[NonEmptyText, ...]


class AuditContractRow(ContractModel):
    category: AuditContractCategory
    implementation: NonEmptyText
    source_disposition: SourceDisposition
    ordering: AuditOrdering
    atomicity: AtomicityClaim
    same_transaction_boundary: SameTransactionBoundary = SameTransactionBoundary.NONE
    audit_presence: AuditPresence
    audit_truth_source: AuditTruthSource
    source_durability: tuple[Durability, ...] = ()
    audit_durability: tuple[Durability, ...] = ()
    source_outcome_on_audit_failure: SourceOutcomeOnAuditFailure
    retry_repair: RetryRepairBehavior
    stable_replay_path: StableReplayPath = StableReplayPath.NONE
    owner_visible_detection: tuple[OwnerVisibleDetection, ...] = Field(min_length=1)


class ObservabilityContractError(ValueError):
    """The static observability contract contradicts required M1 semantics."""


M1_OWNER_API_AUDIT_CONTRACT_SCOPE = AuditContractScope(
    scope_id="observability.m1-owner-api-audit-contract",
    includes=(
        "owner authentication session issue, revoke, and revoke-others",
        "owner API conversation, delivery, memory, Telegram, and export mutations",
        "owner-visible authentication and browser-mutation denials",
    ),
    excludes=(
        "automatic retention sweeps",
        "queue workers",
        "every repository mutation outside the named M1 owner/API audit-contract scope",
    ),
)


def validate_audit_contract(
    rows: tuple[AuditContractRow, ...],
    *,
    scope: AuditContractScope = M1_OWNER_API_AUDIT_CONTRACT_SCOPE,
) -> tuple[AuditContractRow, ...]:
    if scope != M1_OWNER_API_AUDIT_CONTRACT_SCOPE:
        raise ObservabilityContractError(
            "contract scope is collapsed or overclaims current M1 owner/API behavior"
        )

    categories = tuple(row.category for row in rows)
    duplicate_categories = {category for category in categories if categories.count(category) > 1}
    if duplicate_categories:
        duplicate_text = ", ".join(sorted(category.value for category in duplicate_categories))
        raise ObservabilityContractError(f"duplicate audit contract categories: {duplicate_text}")

    expected_categories = set(AuditContractCategory)
    missing = expected_categories - set(categories)
    extra = set(categories) - expected_categories
    if missing or extra:
        missing_text = ", ".join(sorted(category.value for category in missing))
        extra_text = ", ".join(sorted(category.value for category in extra))
        raise ObservabilityContractError(
            f"audit contract category mismatch; missing={missing_text}; extra={extra_text}"
        )

    for row in rows:
        _validate_contract_row(row)
        expected = _EXPECTED_CURRENT_AUDIT_TRUTH[row.category]
        if row != expected:
            changed_fields = ", ".join(
                field_name
                for field_name in AuditContractRow.model_fields
                if getattr(row, field_name) != getattr(expected, field_name)
            )
            raise ObservabilityContractError(
                f"{row.category.value} does not match current audit truth; "
                f"collapsed or overclaimed fields={changed_fields}"
            )
    return rows


def _validate_contract_row(row: AuditContractRow) -> None:
    if row.audit_truth_source is AuditTruthSource.TELEMETRY_DIAGNOSTIC:
        raise ObservabilityContractError("telemetry cannot be audit truth")

    if row.atomicity is AtomicityClaim.SAME_TRANSACTION:
        if row.same_transaction_boundary is SameTransactionBoundary.NONE:
            raise ObservabilityContractError(
                f"{row.category.value} claims atomicity without a transaction boundary"
            )
        if row.ordering is not AuditOrdering.SOURCE_AND_AUDIT_SAME_TRANSACTION:
            raise ObservabilityContractError(
                f"{row.category.value} claims transaction atomicity with non-transaction ordering"
            )

    if row.same_transaction_boundary is not SameTransactionBoundary.NONE:
        if row.atomicity is not AtomicityClaim.SAME_TRANSACTION:
            raise ObservabilityContractError(
                f"{row.category.value} has a transaction boundary but no atomicity claim"
            )

    if (
        row.retry_repair
        in {RetryRepairBehavior.IDEMPOTENT_REPLAY, RetryRepairBehavior.RESUME_REPLAY}
        and row.stable_replay_path is StableReplayPath.NONE
    ):
        raise ObservabilityContractError(
            f"{row.category.value} claims replay repair without a stable replay path"
        )

    if row.audit_presence is AuditPresence.NONE:
        if row.audit_truth_source is not AuditTruthSource.NONE or row.audit_durability:
            raise ObservabilityContractError(
                f"{row.category.value} is unaudited but claims audit evidence"
            )

    if row.source_disposition is SourceDisposition.NO_SOURCE_DENIAL:
        if row.source_durability:
            raise ObservabilityContractError(
                f"{row.category.value} denial cannot claim source durability"
            )
        if row.ordering is not AuditOrdering.AUDIT_ONLY_NO_SOURCE:
            raise ObservabilityContractError(
                f"{row.category.value} no-source denial has mutation ordering"
            )
        if (
            row.source_outcome_on_audit_failure
            is not SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION
        ):
            raise ObservabilityContractError(
                f"{row.category.value} denial cannot claim a source mutation"
            )
    elif not row.source_durability:
        raise ObservabilityContractError(
            f"{row.category.value} accepted mutation has no source durability"
        )

    if (
        row.source_outcome_on_audit_failure
        is SourceOutcomeOnAuditFailure.PARTIAL_AUDIT_SOURCE_UNCHANGED
        and row.atomicity is not AtomicityClaim.NONE
    ):
        raise ObservabilityContractError(
            f"{row.category.value} has a partial-audit gap and cannot be atomic"
        )

    if (
        row.source_outcome_on_audit_failure
        is SourceOutcomeOnAuditFailure.PARTIAL_AUDIT_SOURCE_UNCHANGED
        and row.ordering is not AuditOrdering.AUDIT_BEFORE_SOURCE
    ):
        raise ObservabilityContractError(
            f"{row.category.value} partial audit gap must remain audit-before-source"
        )

    if (
        row.ordering is AuditOrdering.AUDIT_ONLY_NO_SOURCE
        and row.source_outcome_on_audit_failure
        is not SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION
    ):
        raise ObservabilityContractError(
            f"{row.category.value} audit-only row must have no source mutation"
        )


def _row(
    category: AuditContractCategory,
    implementation: str,
    source_disposition: SourceDisposition,
    ordering: AuditOrdering,
    audit_presence: AuditPresence,
    audit_truth_source: AuditTruthSource,
    source_durability: tuple[Durability, ...],
    audit_durability: tuple[Durability, ...],
    source_outcome_on_audit_failure: SourceOutcomeOnAuditFailure,
    retry_repair: RetryRepairBehavior,
    owner_visible_detection: tuple[OwnerVisibleDetection, ...],
    *,
    atomicity: AtomicityClaim = AtomicityClaim.NONE,
    same_transaction_boundary: SameTransactionBoundary = SameTransactionBoundary.NONE,
    stable_replay_path: StableReplayPath = StableReplayPath.NONE,
) -> AuditContractRow:
    return AuditContractRow(
        category=category,
        implementation=implementation,
        source_disposition=source_disposition,
        ordering=ordering,
        atomicity=atomicity,
        same_transaction_boundary=same_transaction_boundary,
        audit_presence=audit_presence,
        audit_truth_source=audit_truth_source,
        source_durability=source_durability,
        audit_durability=audit_durability,
        source_outcome_on_audit_failure=source_outcome_on_audit_failure,
        retry_repair=retry_repair,
        stable_replay_path=stable_replay_path,
        owner_visible_detection=owner_visible_detection,
    )


_DECLARED_M1_OWNER_API_AUDIT_CONTRACT: tuple[AuditContractRow, ...] = (
    _row(
        AuditContractCategory.PROCESS_LOCAL_SESSION_ISSUE,
        "InMemoryOwnerSessionManager.issue appends audit before storing the session.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.AUDIT_BEFORE_SOURCE,
        AuditPresence.SESSION_LIFECYCLE_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL,),
        (Durability.PROCESS_LOCAL,),
        SourceOutcomeOnAuditFailure.SOURCE_NOT_MUTATED,
        RetryRepairBehavior.NOT_NEEDED,
        (OwnerVisibleDetection.API_ERROR,),
    ),
    _row(
        AuditContractCategory.PROCESS_LOCAL_SESSION_REVOKE,
        "InMemoryOwnerSessionManager.revoke appends audit before deleting the session.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.AUDIT_BEFORE_SOURCE,
        AuditPresence.SESSION_LIFECYCLE_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL,),
        (Durability.PROCESS_LOCAL,),
        SourceOutcomeOnAuditFailure.SOURCE_NOT_MUTATED,
        RetryRepairBehavior.IDEMPOTENT_REPLAY,
        (OwnerVisibleDetection.API_ERROR, OwnerVisibleDetection.ACTIVE_SESSION_LIST),
        stable_replay_path=StableReplayPath.CURRENT_SESSION_REVOCATION_REQUEST,
    ),
    _row(
        AuditContractCategory.PROCESS_LOCAL_SESSION_REVOKE_OTHERS,
        (
            "Process-local revoke-others appends per-target audit before deleting any "
            "target; a later append failure can leave earlier audit rows while all "
            "source sessions remain active."
        ),
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.AUDIT_BEFORE_SOURCE,
        AuditPresence.SESSION_LIFECYCLE_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL,),
        (Durability.PROCESS_LOCAL,),
        SourceOutcomeOnAuditFailure.PARTIAL_AUDIT_SOURCE_UNCHANGED,
        RetryRepairBehavior.MANUAL_RECONCILIATION,
        (OwnerVisibleDetection.API_ERROR, OwnerVisibleDetection.ACTIVE_SESSION_LIST),
    ),
    _row(
        AuditContractCategory.POSTGRESQL_SESSION_ISSUE,
        "PostgresOwnerSessionManager.issue inserts source and audit in one transaction.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_AND_AUDIT_SAME_TRANSACTION,
        AuditPresence.SESSION_LIFECYCLE_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.POSTGRESQL,),
        (Durability.POSTGRESQL,),
        SourceOutcomeOnAuditFailure.SOURCE_ROLLED_BACK,
        RetryRepairBehavior.NOT_NEEDED,
        (OwnerVisibleDetection.API_ERROR,),
        atomicity=AtomicityClaim.SAME_TRANSACTION,
        same_transaction_boundary=SameTransactionBoundary.POSTGRES_OWNER_SESSION_TRANSACTION,
    ),
    _row(
        AuditContractCategory.POSTGRESQL_SESSION_REVOKE,
        "PostgresOwnerSessionManager.revoke inserts source and audit in one transaction.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_AND_AUDIT_SAME_TRANSACTION,
        AuditPresence.SESSION_LIFECYCLE_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.POSTGRESQL,),
        (Durability.POSTGRESQL,),
        SourceOutcomeOnAuditFailure.SOURCE_ROLLED_BACK,
        RetryRepairBehavior.NOT_NEEDED,
        (OwnerVisibleDetection.API_ERROR,),
        atomicity=AtomicityClaim.SAME_TRANSACTION,
        same_transaction_boundary=SameTransactionBoundary.POSTGRES_OWNER_SESSION_TRANSACTION,
    ),
    _row(
        AuditContractCategory.POSTGRESQL_SESSION_REVOKE_OTHERS,
        (
            "PostgresOwnerSessionManager.revoke_other_sessions inserts all source "
            "revocations and audits in one transaction."
        ),
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_AND_AUDIT_SAME_TRANSACTION,
        AuditPresence.SESSION_LIFECYCLE_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.POSTGRESQL,),
        (Durability.POSTGRESQL,),
        SourceOutcomeOnAuditFailure.SOURCE_ROLLED_BACK,
        RetryRepairBehavior.NOT_NEEDED,
        (OwnerVisibleDetection.API_ERROR,),
        atomicity=AtomicityClaim.SAME_TRANSACTION,
        same_transaction_boundary=SameTransactionBoundary.POSTGRES_OWNER_SESSION_TRANSACTION,
    ),
    _row(
        AuditContractCategory.CONVERSATION_THREAD_CREATE,
        "ConversationService.create_thread persists the thread without an API audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_ONLY_UNAUDITED,
        AuditPresence.NONE,
        AuditTruthSource.NONE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS_WITHOUT_AUTOMATIC_REPAIR,
        RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
        (OwnerVisibleDetection.NONE,),
    ),
    _row(
        AuditContractCategory.CONVERSATION_OWNER_MESSAGE_ACCEPT,
        "Owner message accept mutates conversation source before API audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
        RetryRepairBehavior.IDEMPOTENT_REPLAY,
        (
            OwnerVisibleDetection.API_ERROR,
            OwnerVisibleDetection.RETRY_RETURNS_DUPLICATE,
            OwnerVisibleDetection.TIMELINE_AUDIT_PROJECTION,
        ),
        stable_replay_path=StableReplayPath.OWNER_MESSAGE_IDEMPOTENCY_KEY,
    ),
    _row(
        AuditContractCategory.CONVERSATION_OWNER_MESSAGE_RESUME,
        "Owner message resume mutates replay state before API audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
        RetryRepairBehavior.RESUME_REPLAY,
        (
            OwnerVisibleDetection.API_ERROR,
            OwnerVisibleDetection.RETRY_RETURNS_DUPLICATE,
            OwnerVisibleDetection.TIMELINE_AUDIT_PROJECTION,
        ),
        stable_replay_path=StableReplayPath.OWNER_MESSAGE_ID,
    ),
    _row(
        AuditContractCategory.DELIVERY_OWNER_ENQUEUE,
        "Owner delivery enqueue mutates delivery work before API audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
        RetryRepairBehavior.IDEMPOTENT_REPLAY,
        (
            OwnerVisibleDetection.API_ERROR,
            OwnerVisibleDetection.RETRY_RETURNS_DUPLICATE,
            OwnerVisibleDetection.TIMELINE_AUDIT_PROJECTION,
        ),
        stable_replay_path=StableReplayPath.DELIVERY_IDEMPOTENCY_KEY,
    ),
    _row(
        AuditContractCategory.DELIVERY_OWNER_RESUME,
        "Owner delivery resume mutates work resumption state before API audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
        RetryRepairBehavior.RESUME_REPLAY,
        (
            OwnerVisibleDetection.API_ERROR,
            OwnerVisibleDetection.RETRY_RETURNS_DUPLICATE,
            OwnerVisibleDetection.TIMELINE_AUDIT_PROJECTION,
        ),
        stable_replay_path=StableReplayPath.DELIVERY_WORK_ID,
    ),
    _row(
        AuditContractCategory.MEMORY_CONTENT_DELETE,
        "Memory content deletion writes tombstone/rebuild source before audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
        RetryRepairBehavior.IDEMPOTENT_REPLAY,
        (
            OwnerVisibleDetection.API_ERROR,
            OwnerVisibleDetection.MEMORY_INSPECTION,
            OwnerVisibleDetection.TIMELINE_AUDIT_PROJECTION,
        ),
        stable_replay_path=StableReplayPath.MEMORY_DELETION_TOMBSTONE,
    ),
    _row(
        AuditContractCategory.MEMORY_CORRECT,
        "Memory correction advances assertion version before audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS_WITHOUT_AUTOMATIC_REPAIR,
        RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
        (OwnerVisibleDetection.API_ERROR, OwnerVisibleDetection.MEMORY_INSPECTION),
    ),
    _row(
        AuditContractCategory.MEMORY_DISPUTE,
        "Memory dispute advances assertion state version before audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS_WITHOUT_AUTOMATIC_REPAIR,
        RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
        (OwnerVisibleDetection.API_ERROR, OwnerVisibleDetection.MEMORY_INSPECTION),
    ),
    _row(
        AuditContractCategory.MEMORY_RETRACT,
        "Memory retract advances assertion state version before audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS_WITHOUT_AUTOMATIC_REPAIR,
        RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
        (OwnerVisibleDetection.API_ERROR, OwnerVisibleDetection.MEMORY_INSPECTION),
    ),
    _row(
        AuditContractCategory.TELEGRAM_PAIRING_CONFIRM,
        "Telegram pairing confirmation persists pairing source before audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
        RetryRepairBehavior.IDEMPOTENT_REPLAY,
        (OwnerVisibleDetection.API_ERROR, OwnerVisibleDetection.TELEGRAM_STATUS),
        stable_replay_path=StableReplayPath.TELEGRAM_PAIRING_ID,
    ),
    _row(
        AuditContractCategory.TELEGRAM_PAIRING_REVOKE,
        "Telegram pairing revocation persists revoked pairing source before audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.SOURCE_PERSISTS,
        RetryRepairBehavior.IDEMPOTENT_REPLAY,
        (OwnerVisibleDetection.API_ERROR, OwnerVisibleDetection.TELEGRAM_STATUS),
        stable_replay_path=StableReplayPath.TELEGRAM_PAIRING_ID,
    ),
    _row(
        AuditContractCategory.EXPORT_PREVIEW_GENERATE,
        "Export preview writes and validates an ephemeral archive before audit append.",
        SourceDisposition.ACCEPTED_MUTATION,
        AuditOrdering.SOURCE_BEFORE_AUDIT,
        AuditPresence.OWNER_API_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (Durability.EPHEMERAL_FILESYSTEM,),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.EPHEMERAL_ARCHIVE_DISCARDED,
        RetryRepairBehavior.FRESH_RETRY,
        (
            OwnerVisibleDetection.API_ERROR,
            OwnerVisibleDetection.EXPORT_DOWNLOAD_SUPPRESSED,
        ),
    ),
    _row(
        AuditContractCategory.INVALID_LOGIN_DENIAL,
        "Invalid owner credential appends a security denial audit and issues no session.",
        SourceDisposition.NO_SOURCE_DENIAL,
        AuditOrdering.AUDIT_ONLY_NO_SOURCE,
        AuditPresence.SECURITY_DENIAL_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION,
        RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
        (OwnerVisibleDetection.SECURITY_DENIAL_RESPONSE,),
    ),
    _row(
        AuditContractCategory.MISSING_SESSION_DENIAL,
        "Missing owner session appends a security denial audit and performs no mutation.",
        SourceDisposition.NO_SOURCE_DENIAL,
        AuditOrdering.AUDIT_ONLY_NO_SOURCE,
        AuditPresence.SECURITY_DENIAL_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION,
        RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
        (OwnerVisibleDetection.SECURITY_DENIAL_RESPONSE,),
    ),
    _row(
        AuditContractCategory.EXPIRED_SESSION_DENIAL,
        "Expired owner session appends a security denial audit and performs no mutation.",
        SourceDisposition.NO_SOURCE_DENIAL,
        AuditOrdering.AUDIT_ONLY_NO_SOURCE,
        AuditPresence.SECURITY_DENIAL_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION,
        RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
        (OwnerVisibleDetection.SECURITY_DENIAL_RESPONSE,),
    ),
    _row(
        AuditContractCategory.CSRF_DENIAL,
        "CSRF failure appends a browser-mutation denial audit before any source mutation.",
        SourceDisposition.NO_SOURCE_DENIAL,
        AuditOrdering.AUDIT_ONLY_NO_SOURCE,
        AuditPresence.SECURITY_DENIAL_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION,
        RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
        (OwnerVisibleDetection.SECURITY_DENIAL_RESPONSE,),
    ),
    _row(
        AuditContractCategory.RECENT_AUTH_DENIAL,
        (
            "Recent-auth failure appends a sensitive-mutation denial audit before "
            "any source mutation."
        ),
        SourceDisposition.NO_SOURCE_DENIAL,
        AuditOrdering.AUDIT_ONLY_NO_SOURCE,
        AuditPresence.SECURITY_DENIAL_EVENT,
        AuditTruthSource.EVENT_AUDIT_STORE,
        (),
        (Durability.PROCESS_LOCAL, Durability.POSTGRESQL),
        SourceOutcomeOnAuditFailure.NO_SOURCE_MUTATION,
        RetryRepairBehavior.NO_AUTOMATIC_REPAIR,
        (OwnerVisibleDetection.SECURITY_DENIAL_RESPONSE,),
    ),
)

_EXPECTED_CURRENT_AUDIT_TRUTH = {row.category: row for row in _DECLARED_M1_OWNER_API_AUDIT_CONTRACT}

M1_OWNER_API_AUDIT_CONTRACT: tuple[AuditContractRow, ...] = validate_audit_contract(
    _DECLARED_M1_OWNER_API_AUDIT_CONTRACT
)


class DiagnosticSignalKind(StrEnum):
    OPERATION_OBSERVED = "operation-observed"


class DiagnosticComponent(StrEnum):
    OWNER_API = "owner-api"
    SESSION_MANAGER = "session-manager"
    CONVERSATION_SERVICE = "conversation-service"
    DELIVERY_SERVICE = "delivery-service"
    MEMORY_SERVICE = "memory-service"
    TELEGRAM_SERVICE = "telegram-service"
    EXPORT_SERVICE = "export-service"


class DiagnosticResult(StrEnum):
    ACCEPTED = "accepted"


class DiagnosticReason(StrEnum):
    SOURCE_OPERATION_COMPLETED = "source-operation-completed"


class DiagnosticSignal(ContractModel):
    kind: DiagnosticSignalKind
    component: DiagnosticComponent
    result: DiagnosticResult
    reason: DiagnosticReason


__all__ = [
    "M1_OWNER_API_AUDIT_CONTRACT",
    "M1_OWNER_API_AUDIT_CONTRACT_SCOPE",
    "AtomicityClaim",
    "AuditContractCategory",
    "AuditContractRow",
    "AuditContractScope",
    "AuditOrdering",
    "AuditPresence",
    "AuditTruthSource",
    "DiagnosticComponent",
    "DiagnosticReason",
    "DiagnosticResult",
    "DiagnosticSignal",
    "DiagnosticSignalKind",
    "Durability",
    "ObservabilityContractError",
    "OwnerVisibleDetection",
    "RetryRepairBehavior",
    "SameTransactionBoundary",
    "SourceDisposition",
    "SourceOutcomeOnAuditFailure",
    "StableReplayPath",
    "validate_audit_contract",
]
