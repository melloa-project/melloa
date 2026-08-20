ALTER TABLE melloa.telegram_owner_channels
    ADD COLUMN model_route text NOT NULL DEFAULT 'economy'
        CHECK (model_route IN ('capable', 'economy'));

ALTER TABLE melloa.telegram_deliveries
    DROP CONSTRAINT telegram_deliveries_delivery_kind_check,
    ADD CONSTRAINT telegram_deliveries_delivery_kind_check
        CHECK (delivery_kind IN ('conversation', 'model_route', 'status')),
    DROP CONSTRAINT telegram_deliveries_check5,
    ADD CONSTRAINT telegram_deliveries_content_check CHECK (
        (delivery_kind = 'status'
            AND inbound_message_id IS NULL
            AND response_message_id IS NULL
            AND notice_code IS NULL
            AND state <> 'awaiting_reply')
        OR
        (delivery_kind = 'model_route'
            AND inbound_message_id IS NULL
            AND response_message_id IS NULL
            AND notice_code IN (
                'telegram.model_route.capable',
                'telegram.model_route.economy'
            )
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
    );
