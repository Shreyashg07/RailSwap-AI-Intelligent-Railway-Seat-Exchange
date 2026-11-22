from flask import Blueprint, jsonify
from flask_jwt_extended import create_access_token, current_user, jwt_required

from backend.constants import ACCOUNT_ACTIVE
from backend.errors import ApiError
from backend.extensions import db
from backend.models import User
from backend.services.abuse_service import (
    client_ip,
    enforce_password_change_rate_limit,
    enforce_registration_rate_limit,
    login_guard,
    record_login_attempt,
)
from backend.validation import (
    clean_bool,
    clean_date_of_birth,
    clean_email,
    clean_password,
    clean_string,
    json_body,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _token_response(user, status_code=200):
    token = create_access_token(identity=str(user.id))
    return (
        jsonify(
            {
                "access_token": token,
                "token_type": "Bearer",
                "user": user.to_dict(),
                "data_mode": "SYNTHETIC_DEMONSTRATION_DATA",
            }
        ),
        status_code,
    )


@auth_bp.post("/register")
def register():
    enforce_registration_rate_limit()
    payload = json_body()
    display_name = clean_string(
        payload.get("display_name"), "Display name", 2, 80
    )
    email = clean_email(payload.get("email"))
    password = clean_password(payload.get("password"))
    date_of_birth = clean_date_of_birth(payload.get("date_of_birth"))
    senior_priority_opt_in = clean_bool(
        payload.get("senior_priority_opt_in"),
        "senior_priority_opt_in",
    )
    share_priority_status = clean_bool(
        payload.get("share_priority_status"),
        "share_priority_status",
    )

    if User.query.filter_by(email=email).first():
        raise ApiError(
            "An account with this email already exists.", 409, "EMAIL_IN_USE"
        )

    user = User(
        display_name=display_name,
        email=email,
        role="user",
        share_display_name=True,
        date_of_birth=date_of_birth,
        senior_priority_opt_in=(
            True if senior_priority_opt_in is None else senior_priority_opt_in
        ),
        share_priority_status=(
            True if share_priority_status is None else share_priority_status
        ),
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return _token_response(user, 201)


@auth_bp.post("/login")
def login():
    payload = json_body()
    email = clean_email(payload.get("email"))
    password = clean_string(payload.get("password"), "Password", max_length=128)
    ip = client_ip()
    login_guard(email, ip)
    user = User.query.filter_by(email=email).first()
    if user is None or not user.check_password(password):
        record_login_attempt(
            email, ip, False, user_id=user.id if user else None
        )
        raise ApiError(
            "Invalid email or password.", 401, "INVALID_CREDENTIALS"
        )
    record_login_attempt(email, ip, True, user_id=user.id)
    if user.account_status != ACCOUNT_ACTIVE:
        raise ApiError(
            "This demo account is restricted while an administrator reviews a "
            "security signal.",
            403,
            "ACCOUNT_RESTRICTED",
        )
    return _token_response(user)


@auth_bp.get("/me")
@jwt_required()
def me():
    return jsonify({"user": current_user.to_dict()})


@auth_bp.put("/me")
@jwt_required()
def update_me():
    payload = json_body()
    changed = False

    if "display_name" in payload:
        current_user.display_name = clean_string(
            payload.get("display_name"), "Display name", 2, 80
        )
        changed = True

    if "share_display_name" in payload:
        current_user.share_display_name = clean_bool(
            payload.get("share_display_name"),
            "share_display_name",
            required=True,
        )
        changed = True

    if "date_of_birth" in payload:
        current_user.date_of_birth = clean_date_of_birth(
            payload.get("date_of_birth")
        )
        changed = True

    if "senior_priority_opt_in" in payload:
        current_user.senior_priority_opt_in = clean_bool(
            payload.get("senior_priority_opt_in"),
            "senior_priority_opt_in",
            required=True,
        )
        changed = True

    if "share_priority_status" in payload:
        current_user.share_priority_status = clean_bool(
            payload.get("share_priority_status"),
            "share_priority_status",
            required=True,
        )
        changed = True

    if "new_password" in payload:
        enforce_password_change_rate_limit(current_user)
        current_password = clean_string(
            payload.get("current_password"),
            "Current password",
            max_length=128,
        )
        if not current_user.check_password(current_password):
            raise ApiError(
                "The current password is incorrect.",
                400,
                "INVALID_CURRENT_PASSWORD",
            )
        current_user.set_password(clean_password(payload.get("new_password")))
        changed = True

    if not changed:
        raise ApiError(
            "No supported profile fields were supplied.",
            400,
            "VALIDATION_ERROR",
        )

    db.session.commit()
    return jsonify({"user": current_user.to_dict()})
