CREATE TABLE melloa.telegram_owner_channels (
    channel_key text PRIMARY KEY CHECK (channel_key = 'owner.telegram'),
    owner_user_id bigint NOT NULL CHECK (owner_user_id > 0),
    owner_chat_id bigint NOT NULL CHECK (owner_chat_id > 0),
    last_update_id bigint CHECK (last_update_id >= 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CHECK (updated_at >= created_at)
);

CREATE TABLE melloa.telegram_deliveries (
    update_id bigint PRIMARY KEY CHECK (update_id >= 0),
    channel_key text NOT NULL REFERENCES melloa.telegram_owner_channels(channel_key),
    incoming_message_id bigint NOT NULL CHECK (incoming_message_id >= 0),
    delivery_kind text NOT NULL CHECK (delivery_kind IN ('conversation', 'status')),
    inbound_message_id text,
    response_message_id text,
    notice_code text,
    state text NOT NULL CHECK (
        state IN ('awaiting_reply', 'ready', 'running', 'sent', 'dead')
    ),
    sent_part_count integer NOT NULL DEFAULT 0 CHECK (sent_part_count >= 0),
    telegram_message_ids bigint[] NOT NULL DEFAULT ARRAY[]::bigint[],
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL CHECK (max_attempts BETWEEN 1 AND 100),
    available_at timestamptz NOT NULL,
    lease_owner text,
    lease_expires_at timestamptz,
    last_error_code text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    delivered_at timestamptz,
    CHECK (updated_at >= created_at),
    CHECK (available_at >= created_at),
    CHECK (attempt_count <= max_attempts),
    CHECK (sent_part_count = cardinality(telegram_message_ids)),
    CHECK (
        (state = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (state <> 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL)
    ),
    CHECK (
        (delivery_kind = 'status'
            AND inbound_message_id IS NULL
            AND response_message_id IS NULL
            AND notice_code IS NULL
            AND state <> 'awaiting_reply')
        OR
        (delivery_kind = 'conversation'
            AND inbound_message_id IS NOT NULL
            AND (
                (state = 'awaiting_reply'
                    AND response_message_id IS NULL
                    AND notice_code IS NULL)
                OR
                (state <> 'awaiting_reply'
                    AND (response_message_id IS NULL) <> (notice_code IS NULL))
            ))
    ),
    CHECK (
        (state = 'sent' AND delivered_at IS NOT NULL AND sent_part_count > 0)
        OR (state <> 'sent' AND delivered_at IS NULL)
    )
);

CREATE INDEX telegram_deliveries_awaiting_idx
    ON melloa.telegram_deliveries (update_id)
    WHERE state = 'awaiting_reply';

CREATE INDEX telegram_deliveries_claim_idx
    ON melloa.telegram_deliveries (available_at, update_id)
    WHERE state IN ('ready', 'running');

GRANT SELECT, INSERT, UPDATE ON melloa.telegram_owner_channels,
    melloa.telegram_deliveries TO melloa_core;
GRANT SELECT ON melloa.telegram_owner_channels,
    melloa.telegram_deliveries TO melloa_readonly, melloa_backup;
