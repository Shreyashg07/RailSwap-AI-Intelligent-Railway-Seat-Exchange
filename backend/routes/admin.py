from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user
from sqlalchemy import func

from backend.constants import (
    ACTIVE_EXCHANGE_STATUSES,
    EXCHANGE_STATUSES,
    FRAUD_ALERT_STATUSES,
    FRAUD_SEVERITIES,
    PRIORITY_SENIOR,
)
from backend.errors import ApiError
from backend.extensions import db
from backend.models import (
    Booking,
    ExchangeRequest,
    FraudAlert,
    Journey,
    Notification,
    Train,
    User,
)
from backend.security import admin_required
from backend.services.abuse_service import (
    admin_security_summary,
    resolve_fraud_alert,
    set_user_account_status,
)
from backend.services.exchange_service import admin_advance_exchange
from backend.services.ml_service import ml_service
from backend.utils import isoformat, utcnow
from backend.validation import clean_bool, clean_string, json_body

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _admin_exchange_summary(exchange):
    journey = exchange.requester_booking.journey
    return {
        "id": exchange.id,
        "status": exchange.status,
        "compatibility_score": exchange.compatibility_score,
        "priority_tier": exchange.priority_tier,
        "expires_at": isoformat(exchange.expires_at),
        "created_at": isoformat(exchange.created_at),
        "updated_at": isoformat(exchange.updated_at),
        "journey_date": isoformat(journey.journey_date),
        "train_number": journey.train.train_number,
        "source": journey.train.source,
        "destination": journey.train.destination,
        "passenger_data": "REDACTED",
        "official_change": False,
    }


def _admin_alert_summary(alert):
    user = alert.user
    return {
        "id": alert.id,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "status": alert.status,
        "summary": alert.summary,
        "details": alert.details_public(),
        "user": (
            {
                "reference": f"Demo user #{user.id}",
                "account_status": user.account_status,
            }
            if user
            else None
        ),
        "created_at": isoformat(alert.created_at),
        "resolved_at": isoformat(alert.resolved_at),
        "resolved_by_user_id": alert.resolved_by_user_id,
        "privacy_note": (
            "Passenger display names, email addresses, IP addresses, and ticket "
            "data are not exposed."
        ),
    }


@admin_bp.get("/overview")
@admin_required
def overview():
    status_counts = {
        status: 0
        for status in EXCHANGE_STATUSES
    }
    for status, count in (
        db.session.query(ExchangeRequest.status, func.count(ExchangeRequest.id))
        .group_by(ExchangeRequest.status)
        .all()
    ):
        status_counts[status] = count
    active_count = sum(
        status_counts.get(status, 0) for status in ACTIVE_EXCHANGE_STATUSES
    )
    return jsonify(
        {
            "counts": {
                "users": User.query.count(),
                "admins": User.query.filter_by(role="admin").count(),
                "trains": Train.query.count(),
                "journeys": Journey.query.count(),
                "bookings": Booking.query.count(),
                "exchange_requests": ExchangeRequest.query.count(),
                "notifications": Notification.query.count(),
                "active_exchanges": active_count,
                "senior_priority_requests": ExchangeRequest.query.filter_by(
                    priority_tier=PRIORITY_SENIOR
                ).count(),
            },
            "exchange_status_counts": status_counts,
            "security": admin_security_summary(),
            "ml": ml_service.status(),
            "data_mode": "SYNTHETIC_DEMONSTRATION_DATA",
            "privacy_note": (
                "Administrators see aggregate and exchange-state information only. "
                "Passenger names, emails, references, and ticket details are redacted."
            ),
            "generated_at": isoformat(utcnow()),
        }
    )


@admin_bp.get("/exchanges")
@admin_required
def exchanges():
    status = (request.args.get("status") or "").strip().upper()
    if status and status not in EXCHANGE_STATUSES:
        raise ApiError("Unknown exchange status filter.", 400, "VALIDATION_ERROR")
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 100))
    except ValueError:
        raise ApiError("limit must be an integer.", 400, "VALIDATION_ERROR") from None
    query = ExchangeRequest.query
    if status:
        query = query.filter(ExchangeRequest.status == status)
    results = query.order_by(ExchangeRequest.updated_at.desc()).limit(limit).all()
    return jsonify(
        {
            "items": [_admin_exchange_summary(exchange) for exchange in results],
            "count": len(results),
            "redaction": "Passenger identity and booking references are not exposed.",
        }
    )


@admin_bp.get("/fraud-alerts")
@admin_required
def fraud_alerts():
    status = (request.args.get("status") or "").strip().upper()
    severity = (request.args.get("severity") or "").strip().upper()
    if status and status not in FRAUD_ALERT_STATUSES:
        raise ApiError("Unknown fraud-alert status filter.", 400, "VALIDATION_ERROR")
    if severity and severity not in FRAUD_SEVERITIES:
        raise ApiError("Unknown fraud-alert severity filter.", 400, "VALIDATION_ERROR")
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 100))
    except ValueError:
        raise ApiError("limit must be an integer.", 400, "VALIDATION_ERROR") from None
    query = FraudAlert.query
    if status:
        query = query.filter(FraudAlert.status == status)
    if severity:
        query = query.filter(FraudAlert.severity == severity)
    alerts = query.order_by(FraudAlert.created_at.desc()).limit(limit).all()
    return jsonify(
        {
            "items": [_admin_alert_summary(alert) for alert in alerts],
            "count": len(alerts),
            "security": admin_security_summary(),
            "notice": (
                "Alerts are generated from synthetic demo activity. "
                "Review them before restricting an account."
            ),
        }
    )


@admin_bp.post("/fraud-alerts/<int:alert_id>/resolve")
@admin_required
def resolve_alert(alert_id):
    alert = db.session.get(FraudAlert, alert_id)
    if alert is None:
        raise ApiError("Fraud alert not found.", 404, "ALERT_NOT_FOUND")
    payload = json_body()
    resolution = payload.get("resolution")
    restrict_user = clean_bool(
        payload.get("restrict_user"), "restrict_user"
    ) or False
    note = payload.get("note")
    if note is not None:
        note = clean_string(note, "note", max_length=300, required=False)
    updated = resolve_fraud_alert(
        alert,
        current_user,
        resolution,
        restrict_user=restrict_user,
        note=note,
    )
    return jsonify(
        {
            "alert": _admin_alert_summary(updated),
            "security": admin_security_summary(),
        }
    )


@admin_bp.post("/users/<int:user_id>/status")
@admin_required
def update_user_status(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        raise ApiError("User not found.", 404, "USER_NOT_FOUND")
    payload = json_body()
    updated = set_user_account_status(user, payload.get("status"))
    return jsonify(
        {
            "user": {
                "id": updated.id,
                "display_name": updated.display_name,
                "role": updated.role,
                "account_status": updated.account_status,
            },
            "notice": (
                "Restricting an account blocks sign-in, revokes existing "
                "sessions, and disables new exchange requests."
            ),
        }
    )


@admin_bp.post("/exchanges/<int:exchange_id>/advance")
@admin_required
def advance_exchange(exchange_id):
    exchange = db.session.get(ExchangeRequest, exchange_id)
    if exchange is None:
        raise ApiError("Exchange request not found.", 404, "EXCHANGE_NOT_FOUND")
    payload = json_body()
    target_status = str(payload.get("target_status") or "").strip().upper()
    updated = admin_advance_exchange(exchange, current_user, target_status)
    return jsonify(
        {
            "exchange": _admin_exchange_summary(updated),
            "simulation_note": (
                "This administrative action only simulates an external authorization "
                "gate. It does not modify or contact any railway reservation system."
            ),
        }
    )
