-- Backup prerequisite: take and verify a database-consistent logical backup before applying.
-- Rollback is lossless only while every assertion content row remains present.

LOCK TABLE melloa.assertions IN ACCESS EXCLUSIVE MODE;

DO $validation$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM melloa.assertions
         WHERE jsonb_typeof(document -> 'value') IS DISTINCT FROM 'object'
    ) THEN
        RAISE EXCEPTION 'every legacy assertion must contain an object value before migration';
    END IF;
END
$validation$;

CREATE TABLE melloa.assertion_contents (
    assertion_id text PRIMARY KEY REFERENCES melloa.assertions(assertion_id),
    value jsonb NOT NULL CHECK (jsonb_typeof(value) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    retention_policy text NOT NULL CHECK (
        retention_policy ~ '^[a-z][a-z0-9_.-]{1,127}$'
    ),
    retained_at timestamptz NOT NULL,
    expires_at timestamptz,
    CHECK (expires_at IS NULL OR expires_at > retained_at)
);

CREATE FUNCTION melloa.set_assertion_content_integrity()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, melloa
AS $function$
BEGIN
    NEW.content_hash := 'sha256:' || encode(
        sha256(convert_to(NEW.value::text, 'UTF8')),
        'hex'
    );
    NEW.size_bytes := octet_length(convert_to(NEW.value::text, 'UTF8'));
    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION melloa.set_assertion_content_integrity() FROM PUBLIC;

CREATE TRIGGER assertion_contents_set_integrity
BEFORE INSERT ON melloa.assertion_contents
FOR EACH ROW EXECUTE FUNCTION melloa.set_assertion_content_integrity();

CREATE INDEX assertion_contents_retention_idx
    ON melloa.assertion_contents (retention_policy, retained_at, assertion_id);

CREATE INDEX assertion_contents_expiry_idx
    ON melloa.assertion_contents (expires_at, assertion_id)
    WHERE expires_at IS NOT NULL;

INSERT INTO melloa.assertion_contents (
    assertion_id,
    value,
    retention_policy,
    retained_at,
    expires_at
)
SELECT
    assertion_id,
    document -> 'value',
    'memory.assertion-owner-lifecycle',
    observed_at,
    NULL
FROM melloa.assertions;

DROP TRIGGER assertions_append_only ON melloa.assertions;

UPDATE melloa.assertions
   SET document = document - 'value';

ALTER TABLE melloa.assertions
    ADD CONSTRAINT assertions_document_is_content_free
    CHECK (
        NOT (document ? 'value')
        AND document ->> 'assertion_id' = assertion_id
    );

CREATE TRIGGER assertions_append_only
BEFORE UPDATE OR DELETE ON melloa.assertions
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

CREATE TRIGGER assertion_contents_update_forbidden
BEFORE UPDATE ON melloa.assertion_contents
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

CREATE FUNCTION melloa.append_assertion(
    p_document jsonb,
    p_retention_policy text,
    p_retained_at timestamptz,
    p_expires_at timestamptz
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, melloa
AS $function$
BEGIN
    IF jsonb_typeof(p_document) IS DISTINCT FROM 'object'
       OR jsonb_typeof(p_document -> 'value') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'assertion document and value must be objects'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO melloa.assertions (
        assertion_id,
        subject_id,
        predicate,
        epistemic_status,
        assertion_status,
        confidence,
        sensitivity,
        source_authority,
        observed_at,
        valid_from,
        valid_to,
        correction_target_id,
        document
    ) VALUES (
        p_document ->> 'assertion_id',
        p_document ->> 'subject_id',
        p_document ->> 'predicate',
        p_document ->> 'epistemic_status',
        p_document ->> 'status',
        (p_document ->> 'confidence')::double precision,
        p_document ->> 'sensitivity',
        p_document ->> 'source_authority',
        (p_document ->> 'observed_at')::timestamptz,
        (p_document ->> 'valid_from')::timestamptz,
        (p_document ->> 'valid_to')::timestamptz,
        p_document ->> 'correction_target_id',
        p_document - 'value'
    );

    INSERT INTO melloa.assertion_contents (
        assertion_id,
        value,
        retention_policy,
        retained_at,
        expires_at
    ) VALUES (
        p_document ->> 'assertion_id',
        p_document -> 'value',
        p_retention_policy,
        p_retained_at,
        p_expires_at
    );
END
$function$;

REVOKE ALL ON FUNCTION melloa.append_assertion(jsonb, text, timestamptz, timestamptz)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION melloa.append_assertion(jsonb, text, timestamptz, timestamptz)
    TO melloa_core, melloa_worker;

REVOKE INSERT ON melloa.assertions FROM melloa_core, melloa_worker;
GRANT SELECT ON melloa.assertion_contents
    TO melloa_core, melloa_worker, melloa_readonly, melloa_backup;
