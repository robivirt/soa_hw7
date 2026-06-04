from __future__ import annotations

import uuid

from fastapi import FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import SessionLocal
from app.errors import ApiError, add_error_handlers
from app.metrics import install_metrics
from app.models import Notification, User


class OrderEvent(BaseModel):
    event_type: str = Field(pattern="^ORDER_(CREATED|UPDATED|CANCELED)$")
    order_id: str
    user_id: str
    status: str


class NotificationResponse(BaseModel):
    id: str
    order_id: str
    user_id: str
    event_type: str
    channel: str
    recipient: str
    message: str
    status: str


app = FastAPI(title="Notification Service", version="1.0.0")
add_error_handlers(app)
install_metrics(app, "notification")


def parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise ApiError(400, "VALIDATION_ERROR", f"Invalid {field}", {field: value}) from exc


def notification_response(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=str(notification.id),
        order_id=str(notification.order_id),
        user_id=str(notification.user_id),
        event_type=notification.event_type,
        channel=notification.channel,
        recipient=notification.recipient,
        message=notification.message,
        status=notification.status,
    )


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok", "service": "notification"}


@app.post("/notifications/order-events", status_code=201)
def create_order_notification(event: OrderEvent) -> NotificationResponse:
    order_id = parse_uuid(event.order_id, "order_id")
    user_id = parse_uuid(event.user_id, "user_id")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Notification recipient was not found")

        notification = Notification(
            order_id=order_id,
            user_id=user_id,
            event_type=event.event_type,
            channel="EMAIL",
            recipient=user.username,
            message=f"{event.event_type}: order {order_id} is {event.status}",
            status="SENT",
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return notification_response(notification)


@app.get("/notifications/orders/{order_id}")
def list_order_notifications(order_id: str) -> list[NotificationResponse]:
    parsed_order_id = parse_uuid(order_id, "order_id")
    with SessionLocal() as db:
        notifications = db.scalars(
            select(Notification).where(Notification.order_id == parsed_order_id).order_by(Notification.created_at)
        ).all()
        return [notification_response(notification) for notification in notifications]
