from datetime import date

from backend.tests.helpers import (
    login_headers,
    make_booking,
    make_journey,
    make_user,
)


def _priority_world(app, *, requester_senior=True, candidate_senior=False):
    requester = make_user(
        app,
        "priority-requester@example.test",
        "Priority Requester",
        date_of_birth=date(1955, 3, 12) if requester_senior else date(1995, 4, 4),
    )
    candidate = make_user(
        app,
        "priority-candidate@example.test",
        "Priority Candidate",
        date_of_birth=date(1950, 8, 21) if candidate_senior else date(1992, 6, 6),
    )
    journey = make_journey(app, train_number="99301", coach_numbers=("S1", "S2"))
    requester_booking = make_booking(
        app, requester, journey, "S1", 1, desired_berth_type="UPPER"
    )
    candidate_booking = make_booking(
        app, candidate, journey, "S2", 3, desired_berth_type="LOWER"
    )
    return requester_booking, candidate_booking


def test_senior_priority_applies_only_after_eligibility_and_is_capped(client, app):
    requester_booking, _candidate_booking = _priority_world(app)
    headers = login_headers(client, "priority-requester@example.test")

    response = client.post(
        "/api/matching/search",
        headers=headers,
        json={"booking_id": requester_booking["booking_id"]},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["meta"]["priority_matches"] == 1
    match = payload["items"][0]
    assert match["priority"]["applied"] is True
    assert match["priority"]["tier"] == "SENIOR_PRIORITY"
    assert match["priority"]["bonus_points"] == 3.0
    assert match["score_breakdown"]["priority_adjustment"] == 3.0
    assert match["score_breakdown"]["score"] > match["score_breakdown"]["base_score"]
    assert match["score_breakdown"]["score"] <= 100
    assert any(
        factor["kind"] == "policy_adjustment"
        for factor in match["score_breakdown"]["contributions"]
    )


def test_senior_priority_opt_out_disables_adjustment(client, app):
    requester = make_user(
        app,
        "priority-optout@example.test",
        "Opt Out Passenger",
        date_of_birth=date(1952, 2, 2),
        senior_priority_opt_in=False,
    )
    candidate = make_user(
        app,
        "priority-standard@example.test",
        "Standard Passenger",
        date_of_birth=date(1993, 3, 3),
    )
    journey = make_journey(app, train_number="99302", coach_numbers=("S1", "S2"))
    requester_booking = make_booking(
        app, requester, journey, "S1", 1, desired_berth_type="UPPER"
    )
    make_booking(app, candidate, journey, "S2", 3, desired_berth_type="LOWER")
    headers = login_headers(client, "priority-optout@example.test")

    response = client.post(
        "/api/matching/search",
        headers=headers,
        json={"booking_id": requester_booking["booking_id"]},
    )
    assert response.status_code == 200
    match = response.get_json()["items"][0]
    assert match["priority"]["applied"] is False
    assert match["score_breakdown"]["priority_adjustment"] == 0.0


def test_hidden_candidate_priority_does_not_expose_private_status(client, app):
    requester_booking, _candidate_booking = _priority_world(
        app, requester_senior=False, candidate_senior=True
    )
    with app.app_context():
        from backend.extensions import db
        from backend.models import User

        candidate = User.query.filter_by(
            email="priority-candidate@example.test"
        ).first()
        candidate.share_priority_status = False
        db.session.commit()

    headers = login_headers(client, "priority-requester@example.test")
    response = client.post(
        "/api/matching/search",
        headers=headers,
        json={"booking_id": requester_booking["booking_id"]},
    )
    assert response.status_code == 200
    match = response.get_json()["items"][0]
    assert match["priority"]["applied"] is True
    assert match["priority"]["candidate_status"] == "PRIVATE"
    policy = match["score_breakdown"]["priority_policy"]
    assert "candidate_active" not in policy
    assert "candidate_shared" not in policy
    assert "requester_active" not in policy
