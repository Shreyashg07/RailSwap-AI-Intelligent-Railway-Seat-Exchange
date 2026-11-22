from backend.constants import BERTH_TYPE_LABELS


def _berth_label(berth_type):
    return BERTH_TYPE_LABELS.get(berth_type, berth_type or "unknown")


def build_explanation(
    requester_booking,
    candidate_booking,
    eligibility,
    features,
    score_details,
    ml_result,
    priority_context=None,
):
    requester_pref = requester_booking.preference
    candidate_pref = candidate_booking.preference
    requester_name = "You"
    candidate_name = candidate_booking.user.public_identity()
    priority_applied = bool(
        priority_context and priority_context.get("applied")
    )

    summary = (
        f"{requester_name} currently have a "
        f"{_berth_label(requester_booking.berth.berth_type)} berth and prefer "
        f"{_berth_label(requester_pref.desired_berth_type if requester_pref else None)}. "
        f"{candidate_name} currently has a "
        f"{_berth_label(candidate_booking.berth.berth_type)} berth and prefers "
        f"{_berth_label(candidate_pref.desired_berth_type if candidate_pref else None)}. "
        "Both directional preferences are compatible."
        if eligibility.get("reciprocal_satisfied")
        else "This candidate does not currently satisfy both directional preferences."
    )
    if priority_applied:
        summary += (
            " The configured senior-citizen priority policy added a small, "
            "transparent ranking adjustment; it did not affect eligibility."
        )

    factor_messages = {
        "reciprocal_match": (
            "Your preferred type matches the candidate's current berth, and the "
            "candidate's preferred type matches your current berth."
            if features.get("reciprocal_match", 0) >= 1
            else "The two berth preferences are not reciprocal."
        ),
        "preference_compatibility": (
            "Both passengers' preferred berth types are available for exchange."
            if features.get("preference_compatibility", 0) >= 1
            else "At least one passenger's preferred berth type is not satisfied."
        ),
        "coach_compatibility": (
            "The two bookings are in the same coach."
            if features.get("coach_compatibility", 0) >= 1
            else "The bookings are in different coaches and both allow a coach-flexible match."
        ),
        "berth_proximity": (
            "A higher value means the two berth numbers are physically closer; "
            "cross-coach pairs receive a proximity penalty."
        ),
        "senior_priority": (
            "A self-declared senior-citizen priority flag is active for one "
            "passenger in this pair, so a small policy adjustment was added "
            "after eligibility passed. It is not an official railway priority."
            if features.get("senior_priority", 0) >= 1
            else "No senior-citizen priority adjustment applied to this pair."
        ),
    }

    factors = []
    for contribution in score_details["contributions"]:
        factor = dict(contribution)
        factor["message"] = factor_messages.get(
            contribution["feature"], contribution["label"]
        )
        factors.append(factor)

    limitations = [
        "This is an application-level suggestion, not an official railway reservation change.",
        "All trains, tickets, berths, and passengers in this project are synthetic demonstration data.",
        "The weighted compatibility score is a ranking heuristic, not a probability of acceptance.",
    ]
    if priority_applied:
        limitations.append(
            "Senior-citizen priority is a self-declared demonstration policy, "
            "not official railway priority or verified eligibility."
        )
    if not eligibility.get("eligible"):
        limitations.insert(
            0,
            "The pair is not eligible, so the recommendation must not be requested.",
        )
    if ml_result.get("score") is None:
        limitations.append(
            "The experimental ML model was not available; ranking uses the deterministic baseline."
        )
    else:
        limitations.append(
            "The ML value is a synthetic-label model output, not real passenger acceptance."
        )

    return {
        "summary": summary,
        "factors": factors,
        "eligibility": eligibility,
        "limitations": limitations,
        "score_interpretation": (
            "Scores are reproducible weighted-baseline ranking values from 0 to 100. "
            "They are not calibrated probabilities."
        ),
        "ml_note": ml_result.get("note"),
    }
