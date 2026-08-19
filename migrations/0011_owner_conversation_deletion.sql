CREATE TABLE melloa.conversation_deletions (
    deletion_id text PRIMARY KEY,
    thread_id text NOT NULL UNIQUE,
    owner_id text NOT NULL REFERENCES melloa.owners(owner_id),
    deleted_at timestamptz NOT NULL,
    active_data_deleted boolean NOT NULL CHECK (active_data_deleted),
    backup_expiry_state text NOT NULL CHECK (backup_expiry_state = 'unknown'),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    CHECK (document ->> 'deletion_id' = deletion_id),
    CHECK (document ->> 'thread_id' = thread_id),
    CHECK (document ->> 'owner_id' = owner_id),
    CHECK ((document ->> 'active_data_deleted')::boolean = active_data_deleted),
    CHECK (document ->> 'backup_expiry_state' = backup_expiry_state)
);

CREATE INDEX conversation_deletions_owner_deleted_idx
    ON melloa.conversation_deletions (owner_id, deleted_at, thread_id);

CREATE TRIGGER conversation_deletions_append_only
BEFORE UPDATE OR DELETE ON melloa.conversation_deletions
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

-- Disclosure evidence deliberately survives deletion without retaining model output,
-- owner messages, or retrieved memory values.
ALTER TABLE melloa.model_disclosures
    DROP CONSTRAINT model_disclosures_result_id_fkey,
    DROP CONSTRAINT model_disclosures_retrieval_manifest_id_fkey;

-- The application role still has no direct DELETE privilege. These tables are mutable
-- only through the bounded SECURITY DEFINER function below.
DROP TRIGGER conversation_messages_append_only ON melloa.conversation_messages;
DROP TRIGGER conversation_turns_append_only ON melloa.conversation_turns;
DROP TRIGGER model_runs_append_only ON melloa.model_runs;
DROP TRIGGER retrieval_manifests_append_only ON melloa.retrieval_manifests;
DROP TRIGGER conversation_inbound_idempotency_append_only
    ON melloa.conversation_inbound_idempotency;
DROP TRIGGER conversation_turn_triggers_append_only
    ON melloa.conversation_turn_triggers;

CREATE FUNCTION melloa.delete_conversation(
    p_deletion_id text,
    p_thread_id text,
    p_owner_id text,
    p_deleted_at timestamptz
)
RETURNS TABLE (deletion_document jsonb)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, melloa
AS $function$
DECLARE
    thread_owner_id text;
    deletion jsonb;
    model_result_ids text[];
    manifest_ids text[];
BEGIN
    SELECT owner_id
      INTO thread_owner_id
      FROM melloa.conversation_threads
     WHERE thread_id = p_thread_id
     FOR UPDATE;

    IF thread_owner_id IS NULL OR thread_owner_id <> p_owner_id THEN
        RAISE EXCEPTION 'conversation not found'
            USING ERRCODE = 'P0002';
    END IF;

    SELECT COALESCE(array_agg(DISTINCT record_id), ARRAY[]::text[])
      INTO model_result_ids
      FROM (
            SELECT jsonb_array_elements_text(turn.document -> 'model_run_ids') AS record_id
              FROM melloa.conversation_turns AS turn
             WHERE turn.thread_id = p_thread_id
            UNION
            SELECT attempt -> 'model_result_summary' ->> 'result_id' AS record_id
              FROM melloa.jobs_outbox AS work
              CROSS JOIN LATERAL jsonb_array_elements(
                  COALESCE(work.payload -> 'attempts', '[]'::jsonb)
              ) AS attempts(attempt)
             WHERE work.work_type = 'conversation.owner_reply'
               AND work.payload ->> 'thread_id' = p_thread_id
      ) AS records
     WHERE record_id IS NOT NULL;

    SELECT COALESCE(array_agg(DISTINCT record_id), ARRAY[]::text[])
      INTO manifest_ids
      FROM (
            SELECT turn.retrieval_manifest_id AS record_id
              FROM melloa.conversation_turns AS turn
             WHERE turn.thread_id = p_thread_id
            UNION
            SELECT attempt ->> 'retrieval_manifest_id' AS record_id
              FROM melloa.jobs_outbox AS work
              CROSS JOIN LATERAL jsonb_array_elements(
                  COALESCE(work.payload -> 'attempts', '[]'::jsonb)
              ) AS attempts(attempt)
             WHERE work.work_type = 'conversation.owner_reply'
               AND work.payload ->> 'thread_id' = p_thread_id
      ) AS records
     WHERE record_id IS NOT NULL;

    DELETE FROM melloa.conversation_turn_triggers
     WHERE thread_id = p_thread_id;

    DELETE FROM melloa.conversation_inbound_idempotency
     WHERE thread_id = p_thread_id;

    UPDATE melloa.jobs_outbox
       SET state = 'cancelled',
           available_at = p_deleted_at,
           updated_at = GREATEST(updated_at, p_deleted_at),
           lease_owner = NULL,
           lease_expires_at = NULL
     WHERE work_type = 'conversation.owner_reply'
       AND payload ->> 'thread_id' = p_thread_id;

    DELETE FROM melloa.conversation_turns
     WHERE thread_id = p_thread_id;

    DELETE FROM melloa.conversation_messages
     WHERE thread_id = p_thread_id;

    DELETE FROM melloa.conversation_threads
     WHERE thread_id = p_thread_id;

    DELETE FROM melloa.model_runs
     WHERE result_id = ANY(model_result_ids);

    DELETE FROM melloa.retrieval_manifests
     WHERE manifest_id = ANY(manifest_ids);

    deletion := jsonb_build_object(
        'contract_version', '1.0.0',
        'deletion_id', p_deletion_id,
        'thread_id', p_thread_id,
        'owner_id', p_owner_id,
        'deleted_at', p_deleted_at,
        'active_data_deleted', true,
        'backup_expiry_state', 'unknown'
    );

    INSERT INTO melloa.conversation_deletions (
        deletion_id,
        thread_id,
        owner_id,
        deleted_at,
        active_data_deleted,
        backup_expiry_state,
        document
    ) VALUES (
        p_deletion_id,
        p_thread_id,
        p_owner_id,
        p_deleted_at,
        true,
        'unknown',
        deletion
    );

    deletion_document := deletion;
    RETURN NEXT;
END
$function$;

REVOKE ALL ON FUNCTION melloa.delete_conversation(
    text, text, text, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION melloa.delete_conversation(
    text, text, text, timestamptz
) TO melloa_core;

GRANT SELECT ON melloa.conversation_deletions
    TO melloa_readonly, melloa_backup, melloa_core;
