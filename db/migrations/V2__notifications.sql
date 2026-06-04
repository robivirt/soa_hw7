CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    event_type VARCHAR(40) NOT NULL CHECK (event_type IN ('ORDER_CREATED', 'ORDER_UPDATED', 'ORDER_CANCELED')),
    channel VARCHAR(20) NOT NULL CHECK (channel IN ('EMAIL', 'PUSH')),
    recipient VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('CREATED', 'SENT')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_notifications_order_id ON notifications(order_id);
CREATE INDEX idx_notifications_user_id ON notifications(user_id);
