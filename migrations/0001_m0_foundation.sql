CREATE SCHEMA IF NOT EXISTS melloa;
REVOKE ALL ON SCHEMA melloa FROM PUBLIC;

CREATE TABLE melloa.schema_migrations (
    version text PRIMARY KEY,
    sha256 text NOT NULL CHECK (sha256 ~ '^sha256:[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION melloa.reject_append_only_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END
$function$;

CREATE TABLE melloa.owners (
    owner_id text PRIMARY KEY,
    contract_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'suspended', 'retired')),
    created_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object')
);

CREATE TABLE melloa.persistent_intelligences (
    intelligence_id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES melloa.owners(owner_id),
    contract_version text NOT NULL,
    role_description text NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'suspended', 'retired')),
    created_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object')
);

CREATE TABLE melloa.intelligence_names (
    name_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    intelligence_id text NOT NULL REFERENCES melloa.persistent_intelligences(intelligence_id),
    display_name text NOT NULL,
    chosen_by text NOT NULL,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE UNIQUE INDEX intelligence_one_current_name
    ON melloa.intelligence_names (intelligence_id)
    WHERE valid_to IS NULL;

CREATE TABLE melloa.canonical_events (
    event_id text PRIMARY KEY,
    event_type text NOT NULL,
    schema_version text NOT NULL,
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    epistemic_status text NOT NULL,
    confidence double precision CHECK (confidence BETWEEN 0.0 AND 1.0),
    sensitivity text NOT NULL,
    trust_label text NOT NULL,
    correlation_id text,
    causation_id text,
    payload_hash text NOT NULL CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    inserted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (causation_id IS NULL OR causation_id <> event_id),
    CHECK (
        epistemic_status NOT IN ('interpretation', 'belief')
        OR confidence IS NOT NULL
    )
);

CREATE INDEX canonical_events_occurred_at_idx ON melloa.canonical_events (occurred_at DESC);
CREATE INDEX canonical_events_type_idx ON melloa.canonical_events (event_type, occurred_at DESC);

CREATE TABLE melloa.provenance_edges (
    edge_id text PRIMARY KEY,
    from_id text NOT NULL,
    to_id text NOT NULL,
    relation text NOT NULL CHECK (
        relation IN ('derived_from', 'supports', 'contradicts', 'supersedes', 'corrects', 'cites')
    ),
    producer_id text NOT NULL,
    created_at timestamptz NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    CHECK (from_id <> to_id)
);

CREATE INDEX provenance_edges_from_idx ON melloa.provenance_edges (from_id, relation);
CREATE INDEX provenance_edges_to_idx ON melloa.provenance_edges (to_id, relation);

CREATE TABLE melloa.assertions (
    assertion_id text PRIMARY KEY,
    subject_id text NOT NULL,
    predicate text NOT NULL,
    epistemic_status text NOT NULL,
    assertion_status text NOT NULL,
    confidence double precision NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    sensitivity text NOT NULL,
    source_authority text NOT NULL,
    observed_at timestamptz NOT NULL,
    valid_from timestamptz,
    valid_to timestamptz,
    correction_target_id text REFERENCES melloa.assertions(assertion_id),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from),
    CHECK (
        (epistemic_status = 'correction' AND correction_target_id IS NOT NULL)
        OR (epistemic_status <> 'correction' AND correction_target_id IS NULL)
    )
);

CREATE INDEX assertions_subject_predicate_idx
    ON melloa.assertions (subject_id, predicate, observed_at DESC);

CREATE TABLE melloa.audit_events (
    audit_sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_id text NOT NULL UNIQUE,
    event_type text NOT NULL,
    occurred_at timestamptz NOT NULL,
    actor_id text NOT NULL,
    action_name text NOT NULL,
    previous_hash text CHECK (previous_hash IS NULL OR previous_hash ~ '^sha256:[0-9a-f]{64}$'),
    record_hash text NOT NULL UNIQUE CHECK (record_hash ~ '^sha256:[0-9a-f]{64}$'),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    inserted_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION melloa.validate_audit_predecessor()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    expected_previous_hash text;
BEGIN
    PERFORM pg_advisory_xact_lock(5281102019001);
    SELECT record_hash
      INTO expected_previous_hash
      FROM melloa.audit_events
     ORDER BY audit_sequence DESC
     LIMIT 1;
    IF NEW.previous_hash IS DISTINCT FROM expected_previous_hash THEN
        RAISE EXCEPTION 'audit predecessor does not match current chain head' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER audit_events_validate_predecessor
BEFORE INSERT ON melloa.audit_events
FOR EACH ROW EXECUTE FUNCTION melloa.validate_audit_predecessor();

CREATE TABLE melloa.jobs_outbox (
    work_id text PRIMARY KEY,
    work_kind text NOT NULL CHECK (work_kind IN ('job', 'outbox')),
    work_type text NOT NULL,
    schema_version text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    state text NOT NULL DEFAULT 'ready' CHECK (
        state IN ('ready', 'running', 'completed', 'dead', 'cancelled')
    ),
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_owner text,
    lease_expires_at timestamptz,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    idempotency_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (state = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR state <> 'running'
    )
);

CREATE INDEX jobs_outbox_claim_idx
    ON melloa.jobs_outbox (available_at, work_id)
    WHERE state = 'ready';

CREATE TABLE melloa.conversation_threads (
    thread_id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES melloa.owners(owner_id),
    intelligence_id text NOT NULL REFERENCES melloa.persistent_intelligences(intelligence_id),
    title text NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'archived', 'closed')),
    sensitivity text NOT NULL,
    retention_policy text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    CHECK (updated_at >= created_at)
);

CREATE TABLE melloa.conversation_messages (
    message_id text PRIMARY KEY,
    thread_id text NOT NULL REFERENCES melloa.conversation_threads(thread_id),
    author_principal_id text NOT NULL,
    source_client text NOT NULL,
    sensitivity text NOT NULL,
    created_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object')
);

CREATE INDEX conversation_messages_thread_idx
    ON melloa.conversation_messages (thread_id, created_at, message_id);

CREATE TABLE melloa.conversation_turns (
    turn_id text PRIMARY KEY,
    thread_id text NOT NULL REFERENCES melloa.conversation_threads(thread_id),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE melloa.model_runs (
    result_id text PRIMARY KEY,
    request_id text NOT NULL,
    route_id text NOT NULL,
    provider_id text NOT NULL,
    model_id text NOT NULL,
    input_tokens bigint NOT NULL CHECK (input_tokens >= 0),
    output_tokens bigint NOT NULL CHECK (output_tokens >= 0),
    cost_gbp numeric(18, 6) NOT NULL CHECK (cost_gbp >= 0),
    external_disclosure boolean NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    CHECK (completed_at >= started_at)
);

DO $triggers$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'canonical_events',
        'provenance_edges',
        'assertions',
        'audit_events',
        'conversation_messages',
        'conversation_turns',
        'model_runs'
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

GRANT USAGE ON SCHEMA melloa TO melloa_migrate, melloa_core, melloa_worker, melloa_readonly, melloa_backup;
GRANT SELECT ON ALL TABLES IN SCHEMA melloa TO melloa_readonly, melloa_backup;
GRANT SELECT, INSERT ON melloa.owners, melloa.persistent_intelligences, melloa.intelligence_names
    TO melloa_core;
GRANT SELECT, INSERT ON melloa.canonical_events, melloa.provenance_edges, melloa.assertions
    TO melloa_core, melloa_worker;
GRANT SELECT, INSERT ON melloa.audit_events TO melloa_core;
GRANT SELECT, INSERT, UPDATE ON melloa.conversation_threads TO melloa_core;
GRANT SELECT, INSERT ON melloa.conversation_messages, melloa.conversation_turns
    TO melloa_core;
GRANT SELECT, INSERT ON melloa.model_runs TO melloa_core;
GRANT SELECT, INSERT, UPDATE ON melloa.jobs_outbox TO melloa_core, melloa_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA melloa TO melloa_core, melloa_worker;

ALTER DEFAULT PRIVILEGES IN SCHEMA melloa REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA melloa REVOKE ALL ON SEQUENCES FROM PUBLIC;
