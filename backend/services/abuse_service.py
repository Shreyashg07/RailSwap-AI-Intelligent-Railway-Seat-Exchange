"""Fraud and misuse protection for the RailSwap AI demonstration.

Controls are intentionally lightweight but real:

* short-window rate limits for sensitive actions;
* persisted sign-in attempt metadata and account lockout;
* exchange-request velocity and repeat-decline cooldowns;
* active-request and booking caps;
* auditable fraud alerts for administrator review;
* account restriction for confirmed abuse.

The in-memory rate limiter is suitable for a single-process academic demo. A
production deployment would use a shared store such as Redis.
"""

import hashlib
import json
import threading
import time
from datetime import timedelta

from flask import current_app, has_app_context, request

from backend.constants import (
    ACCOUNT_ACTIVE,
    ACCOUNT_RESTRICTED,
    ACCOUNT_STATUSES,
    ACTIVE_EXCHANGE_STATUSES,
    EXCHANGE_DECLINED,
    FRAUD_ALERT_DISMISSED,
    FRAUD_ALERT_OPEN,
    FRAUD_ALERT_RESOLVED,
    FRAUD_SEVERITIES,
)
from backend.errors import ApiError
from backend.extensions import db
from backend.models import Booking, ExchangeRequest, FraudAlert, LoginAttempt, User
from backend.utils import utcnow

_RATE_BUCKETS = {}
_RATE_LOCK = threading.Lock()


def reset_runtime_limits():
    with _RATE_LOCK:
        _RATE_BUCKETS.clear()


def _cfg(name, default):
    if has_app_context():
        return current_app.config.get(name, default)
    return default


def _rate_limits_enabled():
    return bool(_cfg("RATE_LIMIT_ENABLED", True))


def client_ip():
    return (request.remote_addr or "unknown")[:64]


def hash_identifier(value):
    return hashlib.sha256(str(value or "").strip().lower().encode("utf-8")).hexdigest()


def check_rate_limit(
    key,
    limit,
    window_seconds,
    message="Too many requests. Please wait before trying again.",
    code="RATE_LIMITED",
    user_id=None,
    alert_type=None,
    alert_summary=None,
    severity="MEDIUM",
):
    if not _rate_limits_enabled():
        return
    limit = max(1, int(limit))
    now = time.monotonic()
    with _RATE_LOCK:
        bucket = [
            stamp
            for stamp in _RATE_BUCKETS.get(key, [])
            if now - stamp < window_seconds
        ]
        if len(bucket) >= limit:
            retry_after = max(1, int(window_seconds - (now - bucket[0])) + 1)
            _RATE_BUCKETS[key] = bucket
            blocked = True
        else:
            bucket.append(now)
            _RATE_BUCKETS[key] = bucket
            blocked = False
    if not blocked:
        return
    if alert_type:
        raise_fraud_alert(
            alert_type=alert_type,
            severity=severity,
            summary=alert_summary or "Rate limit reached.",
            user_id=user_id,
            details={"limit": limit, "window_seconds": window_seconds},
        )
    raise ApiError(
        message,
        429,
        code,
        {"retry_after_seconds": retry_after},
    )


def raise_fraud_alert(
    alert_type,
    severity,
    summary,
    user_id=None,
    details=None,
    dedupe_minutes=60,
):
    if severity not in FRAUD_SEVERITIES:
        severity = "MEDIUM"
    cutoff = utcnow() - timedelta(minutes=dedupe_minutes)
    duplicate = FraudAlert.query.filter(
        FraudAlert.alert_type == alert_type,
        FraudAlert.user_id.is_(user_id)
        if user_id is None
        else FraudAlert.user_id == user_id,
        FraudAlert.status == FRAUD_ALERT_OPEN,
        FraudAlert.created_at >= cutoff,
    ).first()
    if duplicate:
        return duplicate
    alert = FraudAlert(
        user_id=user_id,
        alert_type=alert_type[:60],
        severity=severity,
        summary=summary[:255],
        details=json.dumps(details or {}, sort_keys=True)[:2000],
    )
    db.session.add(alert)
    db.session.commit()
    return alert


def _window_start(minutes):
    return utcnow() - timedelta(minutes=minutes)


def _failed_login_query(email_hash, window_minutes):
    window_start = _window_start(window_minutes)
    query = LoginAttempt.query.filter(
        LoginAttempt.email_hash == email_hash,
        LoginAttempt.success.is_(False),
        LoginAttempt.created_at >= window_start,
    )
    last_success = (
        LoginAttempt.query.filter(
            LoginAttempt.email_hash == email_hash,
            LoginAttempt.success.is_(True),
            LoginAttempt.created_at >= window_start,
        )
        .order_by(LoginAttempt.created_at.desc())
        .first()
    )
    if last_success is not None:
        query = query.filter(LoginAttempt.created_at > last_success.created_at)
    return query


def login_guard(email, ip):
    window_minutes = int(_cfg("LOGIN_WINDOW_MINUTES", 15))
    ip_limit = int(_cfg("LOGIN_IP_MAX_ATTEMPTS", 100))
    email_limit = int(_cfg("LOGIN_MAX_ATTEMPTS", 5))
    check_rate_limit(
        f"login-ip:{ip}",
        ip_limit,
        window_minutes * 60,
        message="Too many sign-in attempts from this network. Please wait.",
        code="LOGIN_RATE_LIMITED",
        alert_type="LOGIN_IP_RATE_LIMIT",
        alert_summary="A network address reached the sign-in rate limit.",
    )
    email_hash = hash_identifier(email)
    failures = _failed_login_query(email_hash, window_minutes).order_by(
        LoginAttempt.created_at
    )
    count = failures.count()
    if count >= email_limit:
        oldest = failures.first()
        retry_after = window_minutes * 60
        if oldest:
            elapsed = (utcnow() - oldest.created_at).total_seconds()
            retry_after = max(1, int(window_minutes * 60 - elapsed) + 1)
        raise ApiError(
            "Too many failed sign-in attempts. This account is temporarily "
            "locked for the demo. Please try again later.",
            429,
            "LOGIN_LOCKED",
            {"retry_after_seconds": retry_after},
        )


def record_login_attempt(email, ip, success, user_id=None):
    email_hash = hash_identifier(email)
    db.session.add(
        LoginAttempt(
            email_hash=email_hash,
            ip_address=ip,
            success=bool(success),
        )
    )
    db.session.commit()
    if success:
        return 0
    window_minutes = int(_cfg("LOGIN_WINDOW_MINUTES", 15))
    limit = int(_cfg("LOGIN_MAX_ATTEMPTS", 5))
    failures = _failed_login_query(email_hash, window_minutes).count()
    if failures >= limit:
        raise_fraud_alert(
            alert_type="REPEATED_FAILED_LOGINS",
            severity="HIGH",
            summary=(
                "Repeated failed sign-in attempts reached the configured "
                "lockout threshold for a demo account or unknown email."
            ),
            user_id=user_id,
            details={
                "failed_attempts_in_window": failures,
                "window_minutes": window_minutes,
            },
        )
    return failures


def enforce_registration_rate_limit():
    check_rate_limit(
        f"register-ip:{client_ip()}",
        int(_cfg("REGISTER_MAX_PER_HOUR", 5)),
        3600,
        message="Too many demo accounts were created from this network. Try later.",
        code="REGISTRATION_RATE_LIMITED",
        alert_type="REGISTRATION_RATE_LIMIT",
        alert_summary="A network address reached the demo registration rate limit.",
    )


def enforce_booking_limit(user):
    limit = int(_cfg("MAX_BOOKINGS_PER_USER", 8))
    count = Booking.query.filter_by(user_id=user.id).count()
    if count >= limit:
        raise_fraud_alert(
            alert_type="BOOKING_LIMIT_REACHED",
            severity="LOW",
            summary="A demo passenger reached the synthetic booking cap.",
            user_id=user.id,
            details={"booking_count": count, "limit": limit},
        )
        raise ApiError(
            f"The demo account can hold at most {limit} synthetic bookings. "
            "Remove an unused booking before adding another.",
            409,
            "BOOKING_LIMIT_REACHED",
        )


def _active_request_query(user):
    booking_ids = [
        booking_id
        for (booking_id,) in db.session.query(Booking.id)
        .filter(Booking.user_id == user.id)
        .all()
    ]
    if not booking_ids:
        return None, 0
    now = utcnow()
    query = ExchangeRequest.query.filter(
        ExchangeRequest.requester_booking_id.in_(booking_ids),
        ExchangeRequest.status.in_(ACTIVE_EXCHANGE_STATUSES),
        db.or_(
            ExchangeRequest.expires_at.is_(None),
            ExchangeRequest.expires_at > now,
        ),
    )
    return query, len(booking_ids)


def enforce_exchange_creation(user):
    if user.account_status != ACCOUNT_ACTIVE:
        raise ApiError(
            "This demo account is restricted. New exchange requests are disabled "
            "while an administrator reviews the security signal.",
            403,
            "ACCOUNT_RESTRICTED",
        )
    check_rate_limit(
        f"exchange-hour:{user.id}",
        int(_cfg("EXCHANGE_REQUESTS_PER_HOUR", 10)),
        3600,
        message="Too many exchange requests in a short period. Please wait.",
        code="EXCHANGE_RATE_LIMITED",
        user_id=user.id,
        alert_type="EXCHANGE_RATE_LIMIT",
        alert_summary="A demo account reached the hourly exchange-request limit.",
    )
    check_rate_limit(
        f"exchange-day:{user.id}",
        int(_cfg("EXCHANGE_REQUESTS_PER_DAY", 25)),
        86400,
        message="The daily exchange-request limit has been reached.",
        code="EXCHANGE_DAILY_LIMIT",
        user_id=user.id,
        alert_type="EXCHANGE_DAILY_LIMIT",
        alert_summary="A demo account reached the daily exchange-request limit.",
    )
    active_query, booking_count = _active_request_query(user)
    if active_query is None:
        return
    max_active = int(_cfg("MAX_ACTIVE_EXCHANGE_REQUESTS_PER_USER", 3))
    active_count = active_query.count()
    if active_count >= max_active:
        raise_fraud_alert(
            alert_type="ACTIVE_REQUEST_LIMIT",
            severity="MEDIUM",
            summary="A demo account reached the active exchange-request cap.",
            user_id=user.id,
            details={
                "active_requests": active_count,
                "limit": max_active,
                "booking_count": booking_count,
            },
        )
        raise ApiError(
            "Resolve an existing active exchange request before creating another.",
            409,
            "ACTIVE_REQUEST_LIMIT",
        )


def enforce_repeat_decline_cooldown(requester_booking_id, recipient_booking_id):
    cooldown_hours = int(_cfg("DECLINED_REQUEST_COOLDOWN_HOURS", 24))
    if cooldown_hours <= 0:
        return
    cutoff = utcnow() - timedelta(hours=cooldown_hours)
    previous = (
        ExchangeRequest.query.filter(
            ExchangeRequest.requester_booking_id == requester_booking_id,
            ExchangeRequest.recipient_booking_id == recipient_booking_id,
            ExchangeRequest.status == EXCHANGE_DECLINED,
            ExchangeRequest.updated_at >= cutoff,
        )
        .order_by(ExchangeRequest.updated_at.desc())
        .first()
    )
    if not previous:
        return
    elapsed = (utcnow() - previous.updated_at).total_seconds()
    retry_after = max(1, int(cooldown_hours * 3600 - elapsed) + 1)
    raise_fraud_alert(
        alert_type="REPEAT_DECLINED_REQUEST",
        severity="MEDIUM",
        summary=(
            "A demo passenger tried to resend a request shortly after a "
            "recipient declined the same pairing."
        ),
        user_id=previous.requester_booking.user_id,
        details={
            "cooldown_hours": cooldown_hours,
            "previous_exchange_id": previous.id,
        },
    )
    raise ApiError(
        "This pairing was recently declined. Please wait before sending another "
        "request to the same candidate.",
        429,
        "REQUEST_COOLDOWN",
        {"retry_after_seconds": retry_after},
    )


def enforce_password_change_rate_limit(user):
    check_rate_limit(
        f"password-change:{user.id}",
        int(_cfg("PASSWORD_CHANGES_PER_HOUR", 5)),
        3600,
        message="Too many password changes. Please wait before trying again.",
        code="PASSWORD_CHANGE_RATE_LIMITED",
        user_id=user.id,
        alert_type="PASSWORD_CHANGE_RATE_LIMIT",
        alert_summary="A demo account reached the password-change rate limit.",
    )


def enforce_matching_rate_limit(user):
    check_rate_limit(
        f"matching:{user.id}",
        int(_cfg("MATCHING_SEARCHES_PER_HOUR", 120)),
        3600,
        message="Too many matching searches. Please wait before trying again.",
        code="MATCHING_RATE_LIMITED",
        user_id=user.id,
    )


def enforce_exchange_action_rate_limit(user):
    check_rate_limit(
        f"exchange-action:{user.id}",
        int(_cfg("EXCHANGE_ACTIONS_PER_HOUR", 60)),
        3600,
        message="Too many exchange actions. Please wait before trying again.",
        code="EXCHANGE_ACTION_RATE_LIMITED",
        user_id=user.id,
    )


def admin_security_summary():
    since = utcnow() - timedelta(hours=24)
    return {
        "failed_logins_24h": LoginAttempt.query.filter(
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= since,
        ).count(),
        "successful_logins_24h": LoginAttempt.query.filter(
            LoginAttempt.success.is_(True),
            LoginAttempt.created_at >= since,
        ).count(),
        "open_fraud_alerts": FraudAlert.query.filter_by(
            status=FRAUD_ALERT_OPEN
        ).count(),
        "restricted_users": User.query.filter_by(
            account_status=ACCOUNT_RESTRICTED
        ).count(),
        "rate_limit_store": "in_memory_single_process",
        "note": (
            "Sign-in metadata is stored with hashed email identifiers. Admin "
            "views never expose passenger display names, raw emails, IP "
            "addresses, or ticket data."
        ),
    }


def resolve_fraud_alert(alert, admin, resolution, restrict_user=False, note=None):
    resolution = str(resolution or "").strip().upper()
    if resolution not in (FRAUD_ALERT_RESOLVED, FRAUD_ALERT_DISMISSED):
        raise ApiError(
            "resolution must be RESOLVED or DISMISSED.",
            400,
            "VALIDATION_ERROR",
        )
    if alert.status != FRAUD_ALERT_OPEN:
        raise ApiError(
            "This alert has already been reviewed.",
            409,
            "ALERT_ALREADY_REVIEWED",
        )
    if restrict_user and alert.user_id:
        user = db.session.get(User, alert.user_id)
        if user and user.role != "admin":
            user.account_status = ACCOUNT_RESTRICTED
    details = {}
    try:
        details = json.loads(alert.details or "{}")
    except (TypeError, ValueError):
        details = {}
    if note:
        details["resolution_note"] = str(note)[:300]
    details["restricted_user"] = bool(restrict_user and alert.user_id)
    alert.details = json.dumps(details, sort_keys=True)[:2000]
    alert.status = resolution
    alert.resolved_at = utcnow()
    alert.resolved_by_user_id = admin.id
    db.session.commit()
    return alert


def set_user_account_status(user, status):
    normalized = str(status or "").strip().upper()
    if normalized not in ACCOUNT_STATUSES:
        raise ApiError(
            "status must be ACTIVE or RESTRICTED.", 400, "VALIDATION_ERROR"
        )
    if user.role == "admin" and normalized == ACCOUNT_RESTRICTED:
        raise ApiError(
            "Administrator accounts cannot be restricted through this endpoint.",
            400,
            "VALIDATION_ERROR",
        )
    user.account_status = normalized
    db.session.commit()
    return user
