CREATE TABLE melloa.assertion_content_deletions (
    tombstone_id text PRIMARY KEY,
    assertion_id text NOT NULL UNIQUE REFERENCES melloa.assertions(assertion_id),
    owner_id text NOT NULL,
    deleted_by_record_id text NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    retention_policy text NOT NULL CHECK (
        retention_policy ~ '^[a-z][a-z0-9_.-]{1,127}$'
    ),
    retained_at timestamptz NOT NULL,
    expires_at timestamptz,
    deleted_at timestamptz NOT NULL,
    reason_code text NOT NULL CHECK (
        reason_code ~ '^[a-z][a-z0-9_.-]{1,127}$'
    ),
    rebuild_work_id text NOT NULL UNIQUE,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    CHECK (expires_at IS NULL OR expires_at > retained_at),
    CHECK (deleted_at >= retained_at),
    CHECK (deleted_by_record_id = owner_id),
    CHECK (document ->> 'tombstone_id' = tombstone_id),
    CHECK (document ->> 'assertion_id' = assertion_id),
    CHECK (document ->> 'owner_id' = owner_id),
    CHECK (document ->> 'content_hash' = content_hash),
    CHECK ((document ->> 'size_bytes')::bigint = size_bytes),
    CHECK (document ->> 'retention_policy' = retention_policy),
    CHECK (document ->> 'reason_code' = reason_code),
    CHECK (document ->> 'rebuild_work_id' = rebuild_work_id)
);

CREATE INDEX assertion_content_deletions_owner_deleted_idx
    ON melloa.assertion_content_deletions (owner_id, deleted_at, assertion_id);

CREATE TABLE melloa.assertion_derived_rebuild_work (
    work_id text PRIMARY KEY,
    work_type text NOT NULL CHECK (
        work_type = 'memory.assertion-derived-rebuild'
    ),
    assertion_id text NOT NULL REFERENCES melloa.assertions(assertion_id),
    tombstone_id text NOT NULL UNIQUE REFERENCES melloa.assertion_content_deletions(tombstone_id),
    requested_by_record_id text NOT NULL,
    requested_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    CHECK (work_id <> assertion_id),
    CHECK (document ->> 'work_id' = work_id),
    CHECK (document ->> 'work_type' = work_type),
    CHECK (document ->> 'assertion_id' = assertion_id),
    CHECK (document ->> 'tombstone_id' = tombstone_id),
    CHECK (document ->> 'requested_by_record_id' = requested_by_record_id)
);

CREATE INDEX assertion_derived_rebuild_work_requested_idx
    ON melloa.assertion_derived_rebuild_work (requested_at, work_id);

CREATE TRIGGER assertion_content_deletions_append_only
BEFORE UPDATE OR DELETE ON melloa.assertion_content_deletions
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

CREATE TRIGGER assertion_derived_rebuild_work_append_only
BEFORE UPDATE OR DELETE ON melloa.assertion_derived_rebuild_work
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

CREATE FUNCTION melloa.delete_assertion_content(
    p_assertion_id text,
    p_owner_id text,
    p_tombstone_id text,
    p_rebuild_work_id text,
    p_deleted_by_record_id text,
    p_deleted_at timestamptz,
    p_reason_code text
)
RETURNS TABLE (
    tombstone_document jsonb,
    rebuild_work_document jsonb,
    created boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, melloa
AS $function$
DECLARE
    assertion_owner text;
    content_record record;
    tombstone jsonb;
    rebuild_work jsonb;
BEGIN
    IF p_deleted_by_record_id <> p_owner_id THEN
        RAISE EXCEPTION 'assertion content deletion owner mismatch'
            USING ERRCODE = '42501';
    END IF;

    SELECT subject_id
      INTO assertion_owner
      FROM melloa.assertions
     WHERE assertion_id = p_assertion_id;

    IF assertion_owner IS NULL OR assertion_owner <> p_owner_id THEN
        RAISE EXCEPTION 'assertion not found'
            USING ERRCODE = 'P0002';
    END IF;

    SELECT deletion.document, rebuild.document
      INTO tombstone, rebuild_work
      FROM melloa.assertion_content_deletions AS deletion
      JOIN melloa.assertion_derived_rebuild_work AS rebuild
        ON rebuild.work_id = deletion.rebuild_work_id
     WHERE deletion.assertion_id = p_assertion_id;

    IF tombstone IS NOT NULL THEN
        tombstone_document := tombstone;
        rebuild_work_document := rebuild_work;
        created := false;
        RETURN NEXT;
        RETURN;
    END IF;

    DELETE FROM melloa.assertion_contents
     WHERE assertion_id = p_assertion_id
     RETURNING
        content_hash, size_bytes, retention_policy, retained_at, expires_at
      INTO content_record;

    IF content_record IS NULL THEN
        RAISE EXCEPTION 'assertion content absent without deletion evidence'
            USING ERRCODE = '23514';
    END IF;

    tombstone := jsonb_build_object(
        'contract_version', '1.0.0',
        'tombstone_id', p_tombstone_id,
        'assertion_id', p_assertion_id,
        'owner_id', p_owner_id,
        'deleted_by_record_id', p_deleted_by_record_id,
        'content_hash', content_record.content_hash,
        'size_bytes', content_record.size_bytes,
        'retention_policy', content_record.retention_policy,
        'retained_at', content_record.retained_at,
        'expires_at', content_record.expires_at,
        'deleted_at', p_deleted_at,
        'reason_code', p_reason_code,
        'rebuild_work_id', p_rebuild_work_id
    );
    rebuild_work := jsonb_build_object(
        'contract_version', '1.0.0',
        'work_id', p_rebuild_work_id,
        'work_type', 'memory.assertion-derived-rebuild',
        'assertion_id', p_assertion_id,
        'tombstone_id', p_tombstone_id,
        'requested_by_record_id', p_deleted_by_record_id,
        'requested_at', p_deleted_at
    );

    INSERT INTO melloa.assertion_content_deletions (
        tombstone_id,
        assertion_id,
        owner_id,
        deleted_by_record_id,
        content_hash,
        size_bytes,
        retention_policy,
        retained_at,
        expires_at,
        deleted_at,
        reason_code,
        rebuild_work_id,
        document
    ) VALUES (
        p_tombstone_id,
        p_assertion_id,
        p_owner_id,
        p_deleted_by_record_id,
        content_record.content_hash,
        content_record.size_bytes,
        content_record.retention_policy,
        content_record.retained_at,
        content_record.expires_at,
        p_deleted_at,
        p_reason_code,
        p_rebuild_work_id,
        tombstone
    );

    INSERT INTO melloa.assertion_derived_rebuild_work (
        work_id,
        work_type,
        assertion_id,
        tombstone_id,
        requested_by_record_id,
        requested_at,
        document
    ) VALUES (
        p_rebuild_work_id,
        'memory.assertion-derived-rebuild',
        p_assertion_id,
        p_tombstone_id,
        p_deleted_by_record_id,
        p_deleted_at,
        rebuild_work
    );

    tombstone_document := tombstone;
    rebuild_work_document := rebuild_work;
    created := true;
    RETURN NEXT;
END
$function$;

REVOKE ALL ON FUNCTION melloa.delete_assertion_content(
    text, text, text, text, text, timestamptz, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION melloa.delete_assertion_content(
    text, text, text, text, text, timestamptz, text
) TO melloa_core;

GRANT SELECT ON melloa.assertion_content_deletions,
    melloa.assertion_derived_rebuild_work
    TO melloa_readonly, melloa_backup, melloa_core;
