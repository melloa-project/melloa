CREATE TABLE melloa.self_changes (
    change_id text PRIMARY KEY CHECK (change_id ~ '^change_[0-9a-f]{32}$'),
    owner_id text NOT NULL REFERENCES melloa.owners(owner_id),
    request_text text NOT NULL CHECK (char_length(request_text) BETWEEN 10 AND 2000),
    request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    requested_update_id bigint NOT NULL UNIQUE CHECK (requested_update_id >= 0),
    state text NOT NULL CHECK (state IN (
        'requested', 'planning', 'proposal_ready', 'approved', 'applying',
        'deployed', 'failed', 'cancelled', 'rolled_back'
    )),
    base_revision text CHECK (base_revision ~ '^[0-9a-f]{40}$'),
    proposal_summary text CHECK (char_length(proposal_summary) BETWEEN 1 AND 2000),
    proposal_patch text CHECK (char_length(proposal_patch) BETWEEN 1 AND 60000),
    proposal_digest text CHECK (proposal_digest ~ '^sha256:[0-9a-f]{64}$'),
    approval_update_id bigint UNIQUE CHECK (approval_update_id >= 0),
    approved_digest text CHECK (approved_digest ~ '^sha256:[0-9a-f]{64}$'),
    candidate_revision text CHECK (candidate_revision ~ '^[0-9a-f]{40}$'),
    failure_reason text CHECK (
        failure_reason ~ '^[a-z][a-z0-9_.-]{1,127}$'
    ),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 10),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    available_at timestamptz NOT NULL,
    lease_owner text,
    lease_expires_at timestamptz,
    requested_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    approved_at timestamptz,
    deployed_at timestamptz,
    cancelled_update_id bigint UNIQUE CHECK (cancelled_update_id >= 0),
    cancelled_at timestamptz,
    rolled_back_at timestamptz,
    CHECK (updated_at >= requested_at),
    CHECK (available_at >= requested_at),
    CHECK (attempt_count <= max_attempts),
    CHECK (
        (state IN ('planning', 'applying')
            AND lease_owner IS NOT NULL
            AND lease_expires_at IS NOT NULL
            AND lease_expires_at > updated_at)
        OR
        (state NOT IN ('planning', 'applying')
            AND lease_owner IS NULL
            AND lease_expires_at IS NULL)
    ),
    CHECK (
        (base_revision IS NULL
            AND proposal_summary IS NULL
            AND proposal_patch IS NULL
            AND proposal_digest IS NULL)
        OR
        (base_revision IS NOT NULL
            AND proposal_summary IS NOT NULL
            AND proposal_patch IS NOT NULL
            AND proposal_digest IS NOT NULL)
    ),
    CHECK (
        state NOT IN ('proposal_ready', 'approved', 'applying', 'deployed', 'rolled_back')
        OR proposal_digest IS NOT NULL
    ),
    CHECK (
        (approval_update_id IS NULL AND approved_digest IS NULL AND approved_at IS NULL)
        OR
        (approval_update_id IS NOT NULL
            AND approved_digest IS NOT NULL
            AND approved_at IS NOT NULL
            AND approval_update_id > requested_update_id
            AND approved_digest = proposal_digest
            AND approved_at BETWEEN requested_at AND updated_at)
    ),
    CHECK (
        state NOT IN ('approved', 'applying', 'deployed', 'rolled_back')
        OR approved_digest IS NOT NULL
    ),
    CHECK (
        (state = 'deployed'
            AND candidate_revision IS NOT NULL
            AND deployed_at IS NOT NULL
            AND rolled_back_at IS NULL
            AND deployed_at BETWEEN requested_at AND updated_at)
        OR
        (state = 'rolled_back'
            AND candidate_revision IS NOT NULL
            AND deployed_at IS NOT NULL
            AND rolled_back_at IS NOT NULL
            AND deployed_at BETWEEN requested_at AND updated_at
            AND rolled_back_at BETWEEN deployed_at AND updated_at)
        OR
        (state NOT IN ('deployed', 'rolled_back')
            AND deployed_at IS NULL
            AND rolled_back_at IS NULL)
    ),
    CHECK ((state = 'failed') = (failure_reason IS NOT NULL)),
    CHECK (
        (state = 'cancelled'
            AND cancelled_update_id IS NOT NULL
            AND cancelled_update_id > requested_update_id
            AND cancelled_at BETWEEN requested_at AND updated_at)
        OR
        (state <> 'cancelled'
            AND cancelled_update_id IS NULL
            AND cancelled_at IS NULL)
    )
);

CREATE INDEX self_changes_owner_latest_idx
    ON melloa.self_changes (owner_id, requested_at DESC, change_id DESC);

CREATE INDEX self_changes_claim_idx
    ON melloa.self_changes (available_at, requested_at, change_id)
    WHERE state IN ('requested', 'planning', 'approved', 'applying');

CREATE TABLE melloa.self_change_events (
    event_sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    change_id text NOT NULL REFERENCES melloa.self_changes(change_id),
    event_type text NOT NULL CHECK (event_type IN (
        'self_change.requested',
        'self_change.planning_started',
        'self_change.planning_retry',
        'self_change.proposal_ready',
        'self_change.approved',
        'self_change.applying_started',
        'self_change.applying_retry',
        'self_change.deployed',
        'self_change.failed',
        'self_change.cancelled',
        'self_change.rolled_back'
    )),
    state text NOT NULL,
    telegram_update_id bigint UNIQUE CHECK (telegram_update_id >= 0),
    proposal_digest text CHECK (proposal_digest ~ '^sha256:[0-9a-f]{64}$'),
    revision text CHECK (revision ~ '^[0-9a-f]{40}$'),
    reason_code text CHECK (reason_code ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    occurred_at timestamptz NOT NULL,
    CHECK (
        (event_type = 'self_change.requested' AND state = 'requested')
        OR (event_type = 'self_change.planning_started' AND state = 'planning')
        OR (event_type = 'self_change.planning_retry' AND state = 'requested')
        OR (event_type = 'self_change.proposal_ready' AND state = 'proposal_ready')
        OR (event_type = 'self_change.approved' AND state = 'approved')
        OR (event_type = 'self_change.applying_started' AND state = 'applying')
        OR (event_type = 'self_change.applying_retry' AND state = 'approved')
        OR (event_type = 'self_change.deployed' AND state = 'deployed')
        OR (event_type = 'self_change.failed' AND state = 'failed')
        OR (event_type = 'self_change.cancelled' AND state = 'cancelled')
        OR (event_type = 'self_change.rolled_back' AND state = 'rolled_back')
    ),
    CHECK (
        (event_type IN (
            'self_change.requested', 'self_change.approved', 'self_change.cancelled'
        ) AND telegram_update_id IS NOT NULL)
        OR
        (event_type NOT IN (
            'self_change.requested', 'self_change.approved', 'self_change.cancelled'
        ) AND telegram_update_id IS NULL)
    ),
    CHECK (
        (event_type IN ('self_change.proposal_ready', 'self_change.approved')
            AND proposal_digest IS NOT NULL)
        OR
        (event_type NOT IN ('self_change.proposal_ready', 'self_change.approved')
            AND proposal_digest IS NULL)
    ),
    CHECK (
        (event_type IN ('self_change.deployed', 'self_change.rolled_back')
            AND revision IS NOT NULL)
        OR
        (event_type NOT IN ('self_change.deployed', 'self_change.rolled_back')
            AND revision IS NULL)
    ),
    CHECK (
        (event_type IN (
            'self_change.planning_retry',
            'self_change.applying_retry',
            'self_change.failed'
        )) = (reason_code IS NOT NULL)
    )
);

CREATE INDEX self_change_events_history_idx
    ON melloa.self_change_events (change_id, event_sequence);

CREATE TRIGGER self_change_events_append_only
BEFORE UPDATE OR DELETE ON melloa.self_change_events
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

ALTER TABLE melloa.telegram_deliveries
    ADD COLUMN control_text text,
    DROP CONSTRAINT telegram_deliveries_delivery_kind_check,
    ADD CONSTRAINT telegram_deliveries_delivery_kind_check
        CHECK (delivery_kind IN ('conversation', 'control', 'model_route', 'status')),
    DROP CONSTRAINT telegram_deliveries_content_check,
    ADD CONSTRAINT telegram_deliveries_control_text_length_check
        CHECK (control_text IS NULL OR char_length(control_text) BETWEEN 1 AND 70000),
    ADD CONSTRAINT telegram_deliveries_content_check CHECK (
        (delivery_kind = 'status'
            AND inbound_message_id IS NULL
            AND response_message_id IS NULL
            AND notice_code IS NULL
            AND control_text IS NULL
            AND state <> 'awaiting_reply')
        OR
        (delivery_kind = 'control'
            AND inbound_message_id IS NULL
            AND response_message_id IS NULL
            AND notice_code IS NULL
            AND control_text IS NOT NULL
            AND state <> 'awaiting_reply')
        OR
        (delivery_kind = 'model_route'
            AND inbound_message_id IS NULL
            AND response_message_id IS NULL
            AND notice_code IN (
                'telegram.model_route.capable',
                'telegram.model_route.economy'
            )
            AND control_text IS NULL
            AND state <> 'awaiting_reply')
        OR
        (delivery_kind = 'conversation'
            AND inbound_message_id IS NOT NULL
            AND control_text IS NULL
            AND (
                (state = 'awaiting_reply'
                    AND response_message_id IS NULL
                    AND notice_code IS NULL)
                OR
                (state <> 'awaiting_reply'
                    AND (response_message_id IS NULL) <> (notice_code IS NULL))
            ))
    );

GRANT SELECT, INSERT, UPDATE ON melloa.self_changes TO melloa_core;
GRANT SELECT, INSERT ON melloa.self_change_events TO melloa_core;
GRANT SELECT ON melloa.self_changes, melloa.self_change_events
    TO melloa_readonly, melloa_backup;
GRANT USAGE, SELECT ON SEQUENCE melloa.self_change_events_event_sequence_seq
    TO melloa_core;
GRANT SELECT ON SEQUENCE melloa.self_change_events_event_sequence_seq
    TO melloa_backup;
