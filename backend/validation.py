import re
from datetime import date

from flask import request

from backend.errors import ApiError
from backend.utils import parse_iso_date

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def json_body() -> dict:
    if not request.is_json:
        raise ApiError(
            "A JSON request body is required.", 415, "UNSUPPORTED_MEDIA_TYPE"
        )
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("The JSON body must be an object.", 400, "INVALID_JSON")
    return payload


def clean_string(value, field, min_length=1, max_length=255, required=True):
    if value is None:
        if required:
            raise ApiError(f"{field} is required.", 400, "VALIDATION_ERROR")
        return None
    if not isinstance(value, str):
        raise ApiError(f"{field} must be a string.", 400, "VALIDATION_ERROR")
    value = value.strip()
    if required and len(value) < min_length:
        raise ApiError(
            f"{field} must be at least {min_length} character(s).",
            400,
            "VALIDATION_ERROR",
        )
    if len(value) > max_length:
        raise ApiError(
            f"{field} must be at most {max_length} characters.",
            400,
            "VALIDATION_ERROR",
        )
    return value or None


def clean_email(value):
    email = clean_string(value, "Email", max_length=255)
    email = email.lower()
    if not EMAIL_PATTERN.match(email):
        raise ApiError("Enter a valid email address.", 400, "VALIDATION_ERROR")
    return email


def clean_password(value):
    password = clean_string(value, "Password", min_length=8, max_length=128)
    return password


def clean_bool(value, field, required=False):
    if value is None:
        if required:
            raise ApiError(f"{field} is required.", 400, "VALIDATION_ERROR")
        return None
    if not isinstance(value, bool):
        raise ApiError(f"{field} must be a boolean.", 400, "VALIDATION_ERROR")
    return value


def clean_date_of_birth(value, field="Date of birth"):
    if value in (None, ""):
        return None
    parsed = parse_iso_date(value)
    if parsed is None:
        raise ApiError(
            f"{field} must use the YYYY-MM-DD format.",
            400,
            "VALIDATION_ERROR",
        )
    today = date.today()
    if parsed > today:
        raise ApiError(
            f"{field} cannot be in the future.", 400, "VALIDATION_ERROR"
        )
    age = today.year - parsed.year - (
        (today.month, today.day) < (parsed.month, parsed.day)
    )
    if age > 120:
        raise ApiError(
            f"{field} does not represent a plausible age for the demo.",
            400,
            "VALIDATION_ERROR",
        )
    return parsed


def require_int(value, field, minimum=None):
    if isinstance(value, bool):
        raise ApiError(f"{field} must be an integer.", 400, "VALIDATION_ERROR")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ApiError(f"{field} must be an integer.", 400, "VALIDATION_ERROR")
    if minimum is not None and parsed < minimum:
        raise ApiError(
            f"{field} must be at least {minimum}.", 400, "VALIDATION_ERROR"
        )
    return parsed
