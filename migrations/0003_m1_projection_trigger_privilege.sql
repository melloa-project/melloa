CREATE OR REPLACE FUNCTION melloa.initialize_assertion_current_state()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, melloa
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

REVOKE ALL ON FUNCTION melloa.initialize_assertion_current_state() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION melloa.initialize_assertion_current_state()
    TO melloa_core, melloa_worker;
