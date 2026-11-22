"""Senior-citizen priority policy for the demonstration matching engine.

This is a transparent policy layer, not part of the ML classifier. It never
overrides hard eligibility. Senior status is self-declared synthetic data; no
government identifier or real verification document is collected.
"""

from flask import current_app, has_app_context

from backend.constants import (
    PRIORITY_SENIOR,
    PRIORITY_STANDARD,
    SENIOR_CITIZEN_AGE,
    SENIOR_PRIORITY_BONUS,
)


def priority_threshold():
    if has_app_context():
        return int(
            current_app.config.get("SENIOR_CITIZEN_AGE", SENIOR_CITIZEN_AGE)
        )
    return SENIOR_CITIZEN_AGE


def priority_bonus_points():
    if has_app_context():
        return float(
            current_app.config.get("SENIOR_PRIORITY_BONUS", SENIOR_PRIORITY_BONUS)
        )
    return SENIOR_PRIORITY_BONUS


def user_priority_state(user, threshold=None):
    threshold = threshold or priority_threshold()
    if user is None:
        return {
            "active": False,
            "senior": False,
            "shared": False,
            "public_active": None,
            "label": None,
        }
    active = user.senior_priority_active(threshold)
    public = user.priority_public(threshold)
    return {
        "active": active,
        "senior": user.is_senior_citizen(threshold),
        "shared": public["shared"],
        "public_active": public["active"],
        "label": public["label"],
    }


def pair_priority(requester_booking, candidate_booking):
    requester = user_priority_state(requester_booking.user)
    candidate = user_priority_state(candidate_booking.user)
    applied = bool(requester["active"] or candidate["active"])
    bonus = round(priority_bonus_points(), 2) if applied else 0.0
    return {
        "applied": applied,
        "tier": PRIORITY_SENIOR if applied else PRIORITY_STANDARD,
        "bonus_points": bonus,
        "requester_active": requester["active"],
        "candidate_active": candidate["active"],
        "candidate_shared": candidate["shared"],
        "candidate_public_active": candidate["public_active"],
        "candidate_label": candidate["label"],
        "threshold_age": priority_threshold(),
        "note": (
            "Self-declared demonstration priority policy. It adds a small "
            "ranking adjustment and never overrides hard eligibility."
        ),
    }


def public_priority_payload(priority_context):
    if not priority_context:
        return {
            "applied": False,
            "tier": PRIORITY_STANDARD,
            "bonus_points": 0.0,
            "candidate_status": "STANDARD",
            "candidate_label": None,
            "note": "No senior-citizen priority adjustment was applied.",
        }
    if priority_context.get("candidate_shared"):
        candidate_status = (
            PRIORITY_SENIOR
            if priority_context.get("candidate_active")
            else PRIORITY_STANDARD
        )
    else:
        candidate_status = "PRIVATE"
    return {
        "applied": priority_context.get("applied", False),
        "tier": priority_context.get("tier", PRIORITY_STANDARD),
        "bonus_points": priority_context.get("bonus_points", 0.0),
        "candidate_status": candidate_status,
        "candidate_label": priority_context.get("candidate_label"),
        "threshold_age": priority_context.get("threshold_age"),
        "note": priority_context.get("note"),
    }


def policy_meta():
    return {
        "enabled": True,
        "threshold_age": priority_threshold(),
        "bonus_points": priority_bonus_points(),
        "basis": "self_declared_demo_date_of_birth",
        "eligibility_override": False,
        "note": (
            "Senior-citizen priority is a transparent, configurable policy "
            "adjustment. It does not use sensitive data beyond an optional "
            "self-declared date of birth, and it cannot make an ineligible "
            "pair eligible."
        ),
    }
