CREATE TABLE melloa.assertion_state_changes (
    change_id text PRIMARY KEY,
    assertion_id text NOT NULL REFERENCES melloa.assertions(assertion_id),
    previous_status text,
    new_status text NOT NULL CHECK (
        new_status IN (
            'provisional', 'active', 'confirmed', 'disputed',
            'superseded', 'retracted', 'expired'
        )
    ),
    preferred_assertion_id text REFERENCES melloa.assertions(assertion_id),
    changed_by_record_id text NOT NULL,
    reason text NOT NULL,
    changed_at timestamptz NOT NULL,
    version bigint NOT NULL CHECK (version > 0),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    UNIQUE (assertion_id, version),
    CHECK (
        (version = 1 AND previous_status IS NULL)
        OR (version > 1 AND previous_status IS NOT NULL)
    ),
    CHECK (preferred_assertion_id IS NULL OR preferred_assertion_id <> assertion_id),
    CHECK (new_status <> 'superseded' OR preferred_assertion_id IS NOT NULL)
);

CREATE INDEX assertion_state_changes_changed_at_idx
    ON melloa.assertion_state_changes (changed_at, assertion_id, version);

INSERT INTO melloa.assertion_state_changes (
    change_id,
    assertion_id,
    previous_status,
    new_status,
    preferred_assertion_id,
    changed_by_record_id,
    reason,
    changed_at,
    version,
    document
)
SELECT
    'state_change_' || md5(assertion_id || ':initial'),
    assertion_id,
    NULL,
    current_status,
    preferred_assertion_id,
    changed_by_record_id,
    'assertion.initialized',
    changed_at,
    1,
    jsonb_build_object(
        'contract_version', '1.0.0',
        'change_id', 'state_change_' || md5(assertion_id || ':initial'),
        'assertion_id', assertion_id,
        'previous_status', NULL,
        'new_status', current_status,
        'preferred_assertion_id', preferred_assertion_id,
        'changed_by_record_id', changed_by_record_id,
        'reason', 'assertion.initialized',
        'changed_at', changed_at,
        'version', 1
    )
FROM melloa.assertion_current_state;

CREATE OR REPLACE FUNCTION melloa.initialize_assertion_current_state()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, melloa
AS $function$
DECLARE
    initial_change_id text := 'state_change_' || md5(NEW.assertion_id || ':initial');
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
            'contract_version', '1.0.0',
            'assertion_id', NEW.assertion_id,
            'current_status', NEW.assertion_status,
            'preferred_assertion_id', NULL,
            'changed_by_record_id', NEW.assertion_id,
            'changed_at', NEW.observed_at,
            'version', 1
        )
    );
    INSERT INTO melloa.assertion_state_changes (
        change_id,
        assertion_id,
        previous_status,
        new_status,
        preferred_assertion_id,
        changed_by_record_id,
        reason,
        changed_at,
        version,
        document
    ) VALUES (
        initial_change_id,
        NEW.assertion_id,
        NULL,
        NEW.assertion_status,
        NULL,
        NEW.assertion_id,
        'assertion.initialized',
        NEW.observed_at,
        1,
        jsonb_build_object(
            'contract_version', '1.0.0',
            'change_id', initial_change_id,
            'assertion_id', NEW.assertion_id,
            'previous_status', NULL,
            'new_status', NEW.assertion_status,
            'preferred_assertion_id', NULL,
            'changed_by_record_id', NEW.assertion_id,
            'reason', 'assertion.initialized',
            'changed_at', NEW.observed_at,
            'version', 1
        )
    );
    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION melloa.initialize_assertion_current_state() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION melloa.initialize_assertion_current_state()
    TO melloa_core, melloa_worker;

CREATE FUNCTION melloa.transition_assertion_state(
    p_change_id text,
    p_assertion_id text,
    p_expected_version bigint,
    p_previous_status text,
    p_new_status text,
    p_preferred_assertion_id text,
    p_changed_by_record_id text,
    p_reason text,
    p_changed_at timestamptz,
    p_projection_document jsonb,
    p_change_document jsonb
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, melloa
AS $function$
BEGIN
    UPDATE melloa.assertion_current_state
       SET current_status = p_new_status,
           preferred_assertion_id = p_preferred_assertion_id,
           changed_by_record_id = p_changed_by_record_id,
           changed_at = p_changed_at,
           version = p_expected_version + 1,
           document = p_projection_document
     WHERE assertion_id = p_assertion_id
       AND version = p_expected_version
       AND current_status = p_previous_status;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'assertion state version conflict' USING ERRCODE = '40001';
    END IF;

    INSERT INTO melloa.assertion_state_changes (
        change_id,
        assertion_id,
        previous_status,
        new_status,
        preferred_assertion_id,
        changed_by_record_id,
        reason,
        changed_at,
        version,
        document
    ) VALUES (
        p_change_id,
        p_assertion_id,
        p_previous_status,
        p_new_status,
        p_preferred_assertion_id,
        p_changed_by_record_id,
        p_reason,
        p_changed_at,
        p_expected_version + 1,
        p_change_document
    );
END
$function$;

REVOKE ALL ON FUNCTION melloa.transition_assertion_state(
    text, text, bigint, text, text, text, text, text, timestamptz, jsonb, jsonb
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION melloa.transition_assertion_state(
    text, text, bigint, text, text, text, text, text, timestamptz, jsonb, jsonb
) TO melloa_core;

CREATE TRIGGER assertion_state_changes_append_only
BEFORE UPDATE OR DELETE ON melloa.assertion_state_changes
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

GRANT SELECT ON melloa.assertion_state_changes TO melloa_readonly, melloa_backup;
GRANT SELECT ON melloa.assertion_state_changes TO melloa_core;
REVOKE INSERT, UPDATE ON melloa.assertion_current_state FROM melloa_core;
