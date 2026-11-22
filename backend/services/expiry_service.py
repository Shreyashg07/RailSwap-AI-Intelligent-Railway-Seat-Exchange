"""Expire stale pending exchange requests.

Expiry is a misuse-protection measure: a pending request should not block a
booking forever if the recipient never responds. Expired requests remain in
history and generate audit events and notifications.
"""

from backend.constants import (
    EVENT_EXPIRED,
    EXCHANGE_EXPIRED,
    EXCHANGE_PENDING,
)
from backend.extensions import db
from backend.models import ExchangeEvent, ExchangeRequest
from backend.services.notification_service import notify_exchange_event
from backend.utils import utcnow


def expire_stale_requests(now=None):
    now = now or utcnow()
    stale = (
        ExchangeRequest.query.filter(
            ExchangeRequest.status == EXCHANGE_PENDING,
            ExchangeRequest.expires_at.isnot(None),
            ExchangeRequest.expires_at <= now,
        )
        .order_by(ExchangeRequest.id)
        .all()
    )
    expired = []
    for exchange in stale:
        updated = (
            ExchangeRequest.query.filter_by(
                id=exchange.id, status=EXCHANGE_PENDING
            ).update(
                {
                    ExchangeRequest.status: EXCHANGE_EXPIRED,
                    ExchangeRequest.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            continue
        db.session.add(
            ExchangeEvent(
                exchange_request_id=exchange.id,
                actor_user_id=None,
                event_type=EVENT_EXPIRED,
            )
        )
        for user_id in (
            exchange.requester_booking.user_id,
            exchange.recipient_booking.user_id,
        ):
            notify_exchange_event(exchange, "EXPIRED", user_id)
        expired.append(exchange.id)
    if expired:
        db.session.commit()
    return expired
