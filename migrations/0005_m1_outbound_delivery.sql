CREATE TABLE melloa.outbound_deliveries (
    work_id text PRIMARY KEY REFERENCES melloa.jobs_outbox(work_id),
    thread_id text NOT NULL,
    message_id text NOT NULL,
    requested_by text NOT NULL REFERENCES melloa.owners(owner_id),
    client_adapter text NOT NULL,
    destination_ref text NOT NULL,
    action_hash text NOT NULL CHECK (action_hash ~ '^sha256:[0-9a-f]{64}$'),
    initial_policy_decision_id text NOT NULL REFERENCES melloa.policy_decisions(decision_id),
    created_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    UNIQUE (work_id, message_id),
    FOREIGN KEY (thread_id, message_id)
        REFERENCES melloa.conversation_messages(thread_id, message_id)
);

CREATE INDEX outbound_deliveries_thread_created_idx
    ON melloa.outbound_deliveries (thread_id, created_at, work_id);

CREATE INDEX outbound_deliveries_message_route_idx
    ON melloa.outbound_deliveries (
        message_id, client_adapter, destination_ref, created_at, work_id
    );

ALTER TABLE melloa.delivery_attempts
    ADD COLUMN outbound_work_id text REFERENCES melloa.outbound_deliveries(work_id);

CREATE UNIQUE INDEX delivery_attempts_outbound_work_attempt_idx
    ON melloa.delivery_attempts (outbound_work_id, attempt)
    WHERE outbound_work_id IS NOT NULL;

ALTER TABLE melloa.executed_actions
    ADD COLUMN outbound_work_id text REFERENCES melloa.outbound_deliveries(work_id),
    ADD COLUMN delivery_id text REFERENCES melloa.delivery_attempts(delivery_id),
    ADD CONSTRAINT executed_actions_outbound_receipt_pair CHECK (
        (outbound_work_id IS NULL AND delivery_id IS NULL)
        OR (outbound_work_id IS NOT NULL AND delivery_id IS NOT NULL)
    );

CREATE UNIQUE INDEX executed_actions_outbound_work_idx
    ON melloa.executed_actions (outbound_work_id)
    WHERE outbound_work_id IS NOT NULL;

CREATE TABLE melloa.delivery_work_resumptions (
    resumption_id text PRIMARY KEY,
    work_id text NOT NULL,
    message_id text NOT NULL,
    requested_by text NOT NULL REFERENCES melloa.owners(owner_id),
    prior_attempts integer NOT NULL CHECK (prior_attempts > 0),
    added_attempts integer NOT NULL CHECK (added_attempts BETWEEN 1 AND 100),
    authorization_request_id text NOT NULL,
    policy_decision_id text NOT NULL REFERENCES melloa.policy_decisions(decision_id),
    action_hash text NOT NULL CHECK (action_hash ~ '^sha256:[0-9a-f]{64}$'),
    requested_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    UNIQUE (work_id, prior_attempts),
    FOREIGN KEY (work_id, message_id)
        REFERENCES melloa.outbound_deliveries(work_id, message_id)
);

CREATE INDEX delivery_work_resumptions_work_time_idx
    ON melloa.delivery_work_resumptions (work_id, requested_at, resumption_id);

CREATE TABLE melloa.delivery_work_attempts (
    attempt_id text PRIMARY KEY,
    work_id text NOT NULL,
    message_id text NOT NULL,
    attempt integer NOT NULL CHECK (attempt > 0),
    authorization_request_id text NOT NULL,
    policy_decision_id text NOT NULL REFERENCES melloa.policy_decisions(decision_id),
    action_hash text NOT NULL CHECK (action_hash ~ '^sha256:[0-9a-f]{64}$'),
    outcome text NOT NULL CHECK (outcome IN ('succeeded', 'retry_scheduled', 'dead')),
    error_code text,
    started_at timestamptz NOT NULL,
    completed_at timestamptz NOT NULL,
    retry_at timestamptz,
    adapter_delivery_id text UNIQUE REFERENCES melloa.delivery_attempts(delivery_id),
    execution_action_id text UNIQUE REFERENCES melloa.executed_actions(action_id),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    UNIQUE (work_id, attempt),
    FOREIGN KEY (work_id, message_id)
        REFERENCES melloa.outbound_deliveries(work_id, message_id),
    CHECK (completed_at >= started_at),
    CHECK (
        (
            outcome = 'succeeded'
            AND error_code IS NULL
            AND retry_at IS NULL
            AND adapter_delivery_id IS NOT NULL
            AND execution_action_id IS NOT NULL
        )
        OR (
            outcome = 'retry_scheduled'
            AND error_code IS NOT NULL
            AND retry_at > completed_at
            AND adapter_delivery_id IS NULL
            AND execution_action_id IS NULL
        )
        OR (
            outcome = 'dead'
            AND error_code IS NOT NULL
            AND retry_at IS NULL
            AND adapter_delivery_id IS NULL
            AND execution_action_id IS NULL
        )
    )
);

CREATE INDEX delivery_work_attempts_work_completed_idx
    ON melloa.delivery_work_attempts (work_id, attempt, completed_at);

DO $triggers$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'outbound_deliveries',
        'delivery_work_resumptions',
        'delivery_work_attempts'
    ]
    LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_append_only '
            'BEFORE UPDATE OR DELETE ON melloa.%I '
            'FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation()',
            table_name,
            table_name
        );
    END LOOP;
END
$triggers$;

GRANT SELECT ON melloa.outbound_deliveries, melloa.delivery_work_resumptions,
    melloa.delivery_work_attempts
    TO melloa_readonly, melloa_backup, melloa_core, melloa_worker;

GRANT INSERT ON melloa.outbound_deliveries, melloa.delivery_work_resumptions
    TO melloa_core;

GRANT INSERT ON melloa.delivery_work_attempts
    TO melloa_core, melloa_worker;

GRANT SELECT ON melloa.owners, melloa.conversation_threads,
    melloa.conversation_messages, melloa.policy_decisions
    TO melloa_worker;

GRANT SELECT, INSERT ON melloa.delivery_attempts, melloa.executed_actions
    TO melloa_worker;
