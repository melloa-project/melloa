CREATE TABLE melloa.retrieval_manifests (
    manifest_id text PRIMARY KEY,
    requester_id text NOT NULL,
    subject_id text NOT NULL,
    purpose text NOT NULL,
    query_hash text NOT NULL CHECK (query_hash ~ '^sha256:[0-9a-f]{64}$'),
    external_disclosure boolean NOT NULL,
    created_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object')
);

CREATE INDEX retrieval_manifests_subject_created_idx
    ON melloa.retrieval_manifests (subject_id, created_at DESC, manifest_id);

ALTER TABLE melloa.conversation_messages
    ADD CONSTRAINT conversation_messages_thread_message_unique
    UNIQUE (thread_id, message_id);

ALTER TABLE melloa.conversation_turns
    ADD CONSTRAINT conversation_turns_thread_turn_unique
    UNIQUE (thread_id, turn_id);

ALTER TABLE melloa.conversation_turns
    ADD COLUMN retrieval_manifest_id text REFERENCES melloa.retrieval_manifests(manifest_id);

CREATE INDEX conversation_turns_retrieval_manifest_idx
    ON melloa.conversation_turns (retrieval_manifest_id)
    WHERE retrieval_manifest_id IS NOT NULL;

CREATE TABLE melloa.conversation_inbound_idempotency (
    thread_id text NOT NULL,
    idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 256),
    message_id text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (thread_id, idempotency_key),
    FOREIGN KEY (thread_id, message_id)
        REFERENCES melloa.conversation_messages(thread_id, message_id)
);

CREATE TABLE melloa.conversation_turn_triggers (
    message_id text PRIMARY KEY,
    thread_id text NOT NULL,
    turn_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (thread_id, message_id)
        REFERENCES melloa.conversation_messages(thread_id, message_id),
    FOREIGN KEY (thread_id, turn_id)
        REFERENCES melloa.conversation_turns(thread_id, turn_id)
);

CREATE INDEX conversation_turn_triggers_turn_idx
    ON melloa.conversation_turn_triggers (turn_id, message_id);

CREATE TABLE melloa.model_disclosures (
    result_id text PRIMARY KEY REFERENCES melloa.model_runs(result_id),
    retrieval_manifest_id text NOT NULL REFERENCES melloa.retrieval_manifests(manifest_id),
    purpose text NOT NULL,
    evidence_ids text[] NOT NULL,
    disclosed_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object')
);

CREATE INDEX model_disclosures_disclosed_at_idx
    ON melloa.model_disclosures (disclosed_at DESC, result_id);

CREATE TABLE melloa.assertion_current_state (
    assertion_id text PRIMARY KEY REFERENCES melloa.assertions(assertion_id),
    current_status text NOT NULL CHECK (
        current_status IN (
            'provisional', 'active', 'confirmed', 'disputed',
            'superseded', 'retracted', 'expired'
        )
    ),
    preferred_assertion_id text REFERENCES melloa.assertions(assertion_id),
    changed_by_record_id text NOT NULL,
    changed_at timestamptz NOT NULL,
    version bigint NOT NULL CHECK (version > 0),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    CHECK (preferred_assertion_id IS NULL OR preferred_assertion_id <> assertion_id)
);

CREATE INDEX assertion_current_state_preferred_idx
    ON melloa.assertion_current_state (preferred_assertion_id)
    WHERE preferred_assertion_id IS NOT NULL;

INSERT INTO melloa.assertion_current_state (
    assertion_id,
    current_status,
    preferred_assertion_id,
    changed_by_record_id,
    changed_at,
    version,
    document
)
SELECT
    assertion_id,
    assertion_status,
    NULL,
    assertion_id,
    observed_at,
    1,
    jsonb_build_object(
        'assertion_id', assertion_id,
        'current_status', assertion_status,
        'preferred_assertion_id', NULL,
        'changed_by_record_id', assertion_id,
        'changed_at', observed_at,
        'version', 1
    )
FROM melloa.assertions;

CREATE FUNCTION melloa.initialize_assertion_current_state()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    INSERT INTO melloa.assertion_current_state (
        assertion_id,
        current_status,
        preferred_assertion_id,
        changed_by_record_id,
        changed_at,
        version,
        document
    ) VALUES (
        NEW.assertion_id,
        NEW.assertion_status,
        NULL,
        NEW.assertion_id,
        NEW.observed_at,
        1,
        jsonb_build_object(
            'assertion_id', NEW.assertion_id,
            'current_status', NEW.assertion_status,
            'preferred_assertion_id', NULL,
            'changed_by_record_id', NEW.assertion_id,
            'changed_at', NEW.observed_at,
            'version', 1
        )
    );
    RETURN NEW;
END
$function$;

CREATE TRIGGER assertions_initialize_current_state
AFTER INSERT ON melloa.assertions
FOR EACH ROW EXECUTE FUNCTION melloa.initialize_assertion_current_state();

DO $triggers$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'retrieval_manifests',
        'conversation_inbound_idempotency',
        'conversation_turn_triggers',
        'model_disclosures'
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

GRANT SELECT ON melloa.retrieval_manifests, melloa.conversation_inbound_idempotency,
    melloa.conversation_turn_triggers, melloa.model_disclosures, melloa.assertion_current_state
    TO melloa_readonly, melloa_backup;
GRANT SELECT, INSERT ON melloa.retrieval_manifests, melloa.conversation_inbound_idempotency,
    melloa.conversation_turn_triggers, melloa.model_disclosures
    TO melloa_core;
GRANT SELECT, INSERT, UPDATE ON melloa.assertion_current_state TO melloa_core;
