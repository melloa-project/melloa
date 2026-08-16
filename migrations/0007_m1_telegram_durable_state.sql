CREATE TABLE melloa.telegram_pairing_candidates (
    adapter_id text NOT NULL,
    candidate_id text NOT NULL,
    owner_id text NOT NULL REFERENCES melloa.owners(owner_id),
    update_id bigint NOT NULL CHECK (update_id BETWEEN 0 AND 4503599627370495),
    telegram_user_id bigint NOT NULL CHECK (
        telegram_user_id BETWEEN 1 AND 4503599627370495
    ),
    telegram_chat_id bigint NOT NULL CHECK (
        telegram_chat_id BETWEEN 1 AND 4503599627370495
    ),
    confirmation_code_hash text NOT NULL CHECK (
        confirmation_code_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    observed_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    PRIMARY KEY (adapter_id, candidate_id),
    UNIQUE (adapter_id, update_id),
    CHECK (expires_at > observed_at),
    CHECK (document ->> 'candidate_id' = candidate_id),
    CHECK ((document ->> 'update_id')::bigint = update_id)
);

CREATE INDEX telegram_pairing_candidates_owner_observed_idx
    ON melloa.telegram_pairing_candidates (
        adapter_id, owner_id, observed_at, candidate_id
    );

CREATE TABLE melloa.telegram_owner_pairings (
    adapter_id text NOT NULL,
    pairing_id text NOT NULL,
    candidate_id text NOT NULL,
    owner_id text NOT NULL REFERENCES melloa.owners(owner_id),
    telegram_user_id bigint NOT NULL CHECK (
        telegram_user_id BETWEEN 1 AND 4503599627370495
    ),
    telegram_chat_id bigint NOT NULL CHECK (
        telegram_chat_id BETWEEN 1 AND 4503599627370495
    ),
    confirmed_by_owner_id text NOT NULL REFERENCES melloa.owners(owner_id),
    confirmed_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    PRIMARY KEY (adapter_id, pairing_id),
    UNIQUE (adapter_id, candidate_id),
    FOREIGN KEY (adapter_id, candidate_id)
        REFERENCES melloa.telegram_pairing_candidates(adapter_id, candidate_id),
    CHECK (confirmed_by_owner_id = owner_id),
    CHECK (document ->> 'pairing_id' = pairing_id),
    CHECK (document -> 'revoked_at' = 'null'::jsonb)
);

CREATE INDEX telegram_owner_pairings_owner_confirmed_idx
    ON melloa.telegram_owner_pairings (
        adapter_id, owner_id, confirmed_at, pairing_id
    );

CREATE TABLE melloa.telegram_pairing_revocations (
    adapter_id text NOT NULL,
    pairing_id text NOT NULL,
    revoked_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    PRIMARY KEY (adapter_id, pairing_id),
    FOREIGN KEY (adapter_id, pairing_id)
        REFERENCES melloa.telegram_owner_pairings(adapter_id, pairing_id),
    CHECK (document ->> 'pairing_id' = pairing_id),
    CHECK (document ->> 'revoked_at' IS NOT NULL)
);

CREATE TABLE melloa.telegram_active_pairings (
    adapter_id text NOT NULL,
    owner_id text NOT NULL REFERENCES melloa.owners(owner_id),
    pairing_id text NOT NULL,
    activated_at timestamptz NOT NULL,
    PRIMARY KEY (adapter_id, owner_id),
    UNIQUE (adapter_id, pairing_id),
    FOREIGN KEY (adapter_id, pairing_id)
        REFERENCES melloa.telegram_owner_pairings(adapter_id, pairing_id)
);

CREATE TABLE melloa.telegram_inbound_updates (
    adapter_id text NOT NULL,
    update_id bigint NOT NULL CHECK (update_id BETWEEN 0 AND 4503599627370495),
    update_fingerprint text NOT NULL CHECK (
        update_fingerprint ~ '^sha256:[0-9a-f]{64}$'
    ),
    source_payload_hash text NOT NULL CHECK (
        source_payload_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    received_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    PRIMARY KEY (adapter_id, update_id),
    CHECK ((document ->> 'update_id')::bigint = update_id)
);

CREATE TABLE melloa.telegram_ingestion_receipts (
    adapter_id text NOT NULL,
    update_id bigint NOT NULL CHECK (update_id BETWEEN 0 AND 4503599627370495),
    receipt_id text NOT NULL,
    update_fingerprint text NOT NULL CHECK (
        update_fingerprint ~ '^sha256:[0-9a-f]{64}$'
    ),
    disposition text NOT NULL CHECK (
        disposition IN ('ingested', 'rejected', 'pairing_candidate')
    ),
    recorded_at timestamptz NOT NULL,
    canonical_message_id text REFERENCES melloa.conversation_messages(message_id),
    pairing_id text,
    pairing_candidate_id text,
    reason_code text,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    PRIMARY KEY (adapter_id, update_id),
    UNIQUE (adapter_id, receipt_id),
    UNIQUE (adapter_id, update_id, receipt_id),
    FOREIGN KEY (adapter_id, update_id)
        REFERENCES melloa.telegram_inbound_updates(adapter_id, update_id),
    FOREIGN KEY (adapter_id, pairing_id)
        REFERENCES melloa.telegram_owner_pairings(adapter_id, pairing_id),
    FOREIGN KEY (adapter_id, pairing_candidate_id)
        REFERENCES melloa.telegram_pairing_candidates(adapter_id, candidate_id),
    CHECK (document ->> 'receipt_id' = receipt_id),
    CHECK ((document ->> 'update_id')::bigint = update_id),
    CHECK (
        (
            disposition = 'ingested'
            AND canonical_message_id IS NOT NULL
            AND pairing_id IS NOT NULL
            AND pairing_candidate_id IS NULL
            AND reason_code IS NULL
        )
        OR (
            disposition = 'pairing_candidate'
            AND canonical_message_id IS NULL
            AND pairing_id IS NULL
            AND pairing_candidate_id IS NOT NULL
            AND reason_code IS NULL
        )
        OR (
            disposition = 'rejected'
            AND canonical_message_id IS NULL
            AND pairing_id IS NULL
            AND pairing_candidate_id IS NULL
            AND reason_code IS NOT NULL
        )
    )
);

CREATE INDEX telegram_ingestion_receipts_dispatch_idx
    ON melloa.telegram_ingestion_receipts (adapter_id, update_id)
    WHERE disposition = 'ingested';

CREATE TABLE melloa.telegram_poll_states (
    adapter_id text PRIMARY KEY,
    next_offset bigint NOT NULL CHECK (
        next_offset BETWEEN 0 AND 4503599627370496
    ),
    revision bigint NOT NULL CHECK (revision >= 0),
    last_update_id bigint,
    last_receipt_id text,
    updated_at timestamptz NOT NULL,
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    FOREIGN KEY (adapter_id, last_update_id, last_receipt_id)
        REFERENCES melloa.telegram_ingestion_receipts(
            adapter_id, update_id, receipt_id
        ),
    CHECK (document ->> 'adapter_id' = adapter_id),
    CHECK (
        (
            revision = 0
            AND next_offset = 0
            AND last_update_id IS NULL
            AND last_receipt_id IS NULL
        )
        OR (
            revision > 0
            AND last_update_id IS NOT NULL
            AND last_receipt_id IS NOT NULL
            AND next_offset = last_update_id + 1
        )
    )
);

DO $triggers$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'telegram_pairing_candidates',
        'telegram_owner_pairings',
        'telegram_pairing_revocations',
        'telegram_inbound_updates',
        'telegram_ingestion_receipts'
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

CREATE TRIGGER telegram_active_pairings_update_forbidden
BEFORE UPDATE ON melloa.telegram_active_pairings
FOR EACH ROW EXECUTE FUNCTION melloa.reject_append_only_mutation();

GRANT SELECT ON melloa.telegram_pairing_candidates,
    melloa.telegram_owner_pairings,
    melloa.telegram_pairing_revocations,
    melloa.telegram_active_pairings,
    melloa.telegram_inbound_updates,
    melloa.telegram_ingestion_receipts,
    melloa.telegram_poll_states
    TO melloa_readonly, melloa_backup, melloa_core;

GRANT INSERT ON melloa.telegram_pairing_candidates,
    melloa.telegram_owner_pairings,
    melloa.telegram_pairing_revocations,
    melloa.telegram_active_pairings,
    melloa.telegram_inbound_updates,
    melloa.telegram_ingestion_receipts,
    melloa.telegram_poll_states
    TO melloa_core;

GRANT UPDATE ON melloa.telegram_poll_states TO melloa_core;
GRANT DELETE ON melloa.telegram_active_pairings TO melloa_core;
