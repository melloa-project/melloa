DROP TRIGGER owner_sessions_append_only ON melloa.owner_sessions;
DROP TRIGGER owner_session_revocations_append_only ON melloa.owner_session_revocations;

CREATE TRIGGER owner_sessions_update_forbidden
BEFORE UPDATE ON melloa.owner_sessions
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

CREATE TRIGGER owner_session_revocations_update_forbidden
BEFORE UPDATE ON melloa.owner_session_revocations
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

CREATE FUNCTION melloa.cleanup_expired_owner_sessions(
    p_owner_id text,
    p_before timestamptz,
    p_limit integer DEFAULT 1000
)
RETURNS TABLE (
    expired_sessions integer,
    expired_revocations integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, melloa
AS $function$
DECLARE
    expired_session_ids text[];
BEGIN
    IF p_owner_id IS NULL OR p_before IS NULL THEN
        RAISE EXCEPTION 'owner session cleanup requires owner and timestamp'
            USING ERRCODE = '22023';
    END IF;
    IF p_limit IS NULL OR p_limit < 0 OR p_limit > 10000 THEN
        RAISE EXCEPTION 'owner session cleanup limit out of range'
            USING ERRCODE = '22023';
    END IF;
    IF p_limit = 0 THEN
        expired_sessions := 0;
        expired_revocations := 0;
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT COALESCE(array_agg(session_id), ARRAY[]::text[])
      INTO expired_session_ids
      FROM (
        SELECT session_id
          FROM melloa.owner_sessions
         WHERE owner_id = p_owner_id
           AND expires_at <= p_before
         ORDER BY expires_at, session_id
         LIMIT p_limit
      ) AS expired;

    IF cardinality(expired_session_ids) = 0 THEN
        expired_sessions := 0;
        expired_revocations := 0;
        RETURN NEXT;
        RETURN;
    END IF;

    WITH deleted_revocations AS (
        DELETE FROM melloa.owner_session_revocations
         WHERE session_id = ANY(expired_session_ids)
         RETURNING 1
    )
    SELECT count(*)::integer
      INTO expired_revocations
      FROM deleted_revocations;

    WITH deleted_sessions AS (
        DELETE FROM melloa.owner_sessions
         WHERE owner_id = p_owner_id
           AND session_id = ANY(expired_session_ids)
           AND expires_at <= p_before
         RETURNING 1
    )
    SELECT count(*)::integer
      INTO expired_sessions
      FROM deleted_sessions;

    RETURN NEXT;
END
$function$;

REVOKE ALL ON FUNCTION melloa.cleanup_expired_owner_sessions(
    text,
    timestamptz,
    integer
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION melloa.cleanup_expired_owner_sessions(
    text,
    timestamptz,
    integer
) TO melloa_core;
