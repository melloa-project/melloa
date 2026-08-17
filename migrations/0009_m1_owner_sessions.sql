CREATE TABLE melloa.owner_sessions (
    session_digest bytea PRIMARY KEY CHECK (octet_length(session_digest) = 32),
    session_id text NOT NULL UNIQUE,
    owner_id text NOT NULL REFERENCES melloa.owners(owner_id),
    credential_digest bytea NOT NULL CHECK (octet_length(credential_digest) = 32),
    csrf_digest bytea NOT NULL CHECK (octet_length(csrf_digest) = 32),
    authentication_method text NOT NULL CHECK (
        authentication_method ~ '^[a-z][a-z0-9_.-]{1,127}$'
    ),
    authenticated_at timestamptz NOT NULL,
    reauthenticated_until timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    CHECK (reauthenticated_until > authenticated_at),
    CHECK (expires_at > authenticated_at),
    CHECK (reauthenticated_until <= expires_at),
    CHECK (document ->> 'session_id' = session_id),
    CHECK (document ->> 'owner_id' = owner_id),
    CHECK (document ->> 'authentication_method' = authentication_method),
    CHECK ((document ->> 'authenticated_at')::timestamptz = authenticated_at),
    CHECK (
        (document ->> 'reauthenticated_until')::timestamptz = reauthenticated_until
    ),
    CHECK ((document ->> 'expires_at')::timestamptz = expires_at)
);

CREATE INDEX owner_sessions_owner_expiry_idx
    ON melloa.owner_sessions (owner_id, expires_at, session_id);

CREATE TABLE melloa.owner_session_revocations (
    session_id text PRIMARY KEY REFERENCES melloa.owner_sessions(session_id),
    revoked_at timestamptz NOT NULL,
    reason_code text NOT NULL CHECK (
        reason_code ~ '^[a-z][a-z0-9_.-]{1,127}$'
    )
);

CREATE INDEX owner_session_revocations_revoked_idx
    ON melloa.owner_session_revocations (revoked_at, session_id);

CREATE TRIGGER owner_sessions_append_only
BEFORE UPDATE OR DELETE ON melloa.owner_sessions
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

CREATE TRIGGER owner_session_revocations_append_only
BEFORE UPDATE OR DELETE ON melloa.owner_session_revocations
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

GRANT SELECT, INSERT ON melloa.owner_sessions, melloa.owner_session_revocations
    TO melloa_core;
GRANT SELECT ON melloa.owner_sessions, melloa.owner_session_revocations
    TO melloa_backup;
