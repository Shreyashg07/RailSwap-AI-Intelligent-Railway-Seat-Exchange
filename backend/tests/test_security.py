from datetime import timedelta

from backend.extensions import db
from backend.models import ExchangeRequest
from backend.tests.helpers import (
    ADMIN_PASSWORD,
    PASSWORD,
    login_headers,
    make_booking,
    make_journey,
    make_pending_exchange,
    make_user,
)
from backend.utils import utcnow


def test_repeated_failed_logins_lock_account_and_create_admin_alert(client, app):
    make_user(app, "lockout@example.test", "Lockout Demo")
    make_user(
        app,
        "admin@example.test",
        "Admin Demo",
        role="admin",
        password=ADMIN_PASSWORD,
    )

    for _ in range(5):
        response = client.post(
            "/api/auth/login",
            json={"email": "lockout@example.test", "password": "WrongPassword"},
        )
        assert response.status_code == 401

    locked = client.post(
        "/api/auth/login",
        json={"email": "lockout@example.test", "password": PASSWORD},
    )
    assert locked.status_code == 429
    assert locked.get_json()["error"]["code"] == "LOGIN_LOCKED"

    admin_headers = login_headers(
        client, "admin@example.test", password=ADMIN_PASSWORD
    )
    alerts = client.get(
        "/api/admin/fraud-alerts?status=OPEN", headers=admin_headers
    )
    assert alerts.status_code == 200
    alert_items = alerts.get_json()["items"]
    lockout_alerts = [
        item for item in alert_items if item["alert_type"] == "REPEATED_FAILED_LOGINS"
    ]
    assert lockout_alerts
    serialized_alert = str(lockout_alerts[0])
    assert "lockout@example.test" not in serialized_alert
    assert "127.0.0.1" not in serialized_alert
    assert "Lockout Demo" not in serialized_alert
    assert lockout_alerts[0]["user"]["reference"].startswith("Demo user #")
    assert lockout_alerts[0]["details"]["failed_attempts_in_window"] == 5

    resolved = client.post(
        f"/api/admin/fraud-alerts/{lockout_alerts[0]['id']}/resolve",
        headers=admin_headers,
        json={"resolution": "RESOLVED", "note": "Synthetic test review."},
    )
    assert resolved.status_code == 200
    assert resolved.get_json()["alert"]["status"] == "RESOLVED"


def test_successful_login_resets_failed_attempt_counter(client, app):
    make_user(app, "reset@example.test", "Reset Demo")

    for _ in range(4):
        response = client.post(
            "/api/auth/login",
            json={"email": "reset@example.test", "password": "WrongPassword"},
        )
        assert response.status_code == 401

    success = client.post(
        "/api/auth/login",
        json={"email": "reset@example.test", "password": PASSWORD},
    )
    assert success.status_code == 200

    one_failure = client.post(
        "/api/auth/login",
        json={"email": "reset@example.test", "password": "WrongPassword"},
    )
    assert one_failure.status_code == 401

    allowed = client.post(
        "/api/auth/login",
        json={"email": "reset@example.test", "password": PASSWORD},
    )
    assert allowed.status_code == 200


def test_admin_can_restrict_account_and_login_is_blocked(client, app):
    user_id = make_user(app, "restrict@example.test", "Restrict Demo")
    make_user(
        app,
        "restrict-admin@example.test",
        "Admin Demo",
        role="admin",
        password=ADMIN_PASSWORD,
    )
    admin_headers = login_headers(
        client, "restrict-admin@example.test", password=ADMIN_PASSWORD
    )

    response = client.post(
        f"/api/admin/users/{user_id}/status",
        headers=admin_headers,
        json={"status": "RESTRICTED"},
    )
    assert response.status_code == 200
    assert response.get_json()["user"]["account_status"] == "RESTRICTED"

    blocked = client.post(
        "/api/auth/login",
        json={"email": "restrict@example.test", "password": PASSWORD},
    )
    assert blocked.status_code == 403
    assert blocked.get_json()["error"]["code"] == "ACCOUNT_RESTRICTED"


def test_restricting_account_revokes_existing_session(client, app):
    user_id = make_user(app, "revoke@example.test", "Revoke Demo")
    make_user(
        app,
        "revoke-admin@example.test",
        "Admin Demo",
        role="admin",
        password=ADMIN_PASSWORD,
    )
    user_headers = login_headers(client, "revoke@example.test")
    admin_headers = login_headers(
        client, "revoke-admin@example.test", password=ADMIN_PASSWORD
    )

    assert client.get("/api/auth/me", headers=user_headers).status_code == 200

    response = client.post(
        f"/api/admin/users/{user_id}/status",
        headers=admin_headers,
        json={"status": "RESTRICTED"},
    )
    assert response.status_code == 200

    blocked = client.get("/api/auth/me", headers=user_headers)
    assert blocked.status_code == 403
    assert blocked.get_json()["error"]["code"] == "ACCOUNT_RESTRICTED"


def test_registration_rate_limit(client, app):
    app.config["REGISTER_MAX_PER_HOUR"] = 2
    for index in range(2):
        response = client.post(
            "/api/auth/register",
            json={
                "display_name": f"Rate Limit {index}",
                "email": f"rate-limit-{index}@example.test",
                "password": PASSWORD,
            },
        )
        assert response.status_code == 201

    limited = client.post(
        "/api/auth/register",
        json={
            "display_name": "Rate Limit Blocked",
            "email": "rate-limit-blocked@example.test",
            "password": PASSWORD,
        },
    )
    assert limited.status_code == 429
    assert limited.get_json()["error"]["code"] == "REGISTRATION_RATE_LIMITED"


def test_expired_pending_request_is_marked_expired(client, app):
    requester = make_user(app, "expiry-requester@example.test", "Expiry Requester")
    recipient = make_user(app, "expiry-recipient@example.test", "Expiry Recipient")
    journey = make_journey(app, train_number="99311")
    requester_booking = make_booking(
        app, requester, journey, "S1", 1, desired_berth_type="UPPER"
    )
    recipient_booking = make_booking(
        app, recipient, journey, "S1", 3, desired_berth_type="LOWER"
    )
    exchange_id = make_pending_exchange(
        app, requester_booking["booking_id"], recipient_booking["booking_id"]
    )
    with app.app_context():
        exchange = db.session.get(ExchangeRequest, exchange_id)
        exchange.expires_at = utcnow() - timedelta(hours=1)
        db.session.commit()

    headers = login_headers(client, "expiry-requester@example.test")
    response = client.get("/api/exchanges", headers=headers)
    assert response.status_code == 200
    item = response.get_json()["items"][0]
    assert item["status"] == "EXPIRED"
    assert item["expires_at"] is not None
