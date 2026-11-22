from datetime import date

from flask import current_app, has_app_context
from werkzeug.security import check_password_hash, generate_password_hash

from backend.constants import (
    ACCOUNT_ACTIVE,
    ROLE_USER,
    ROLES,
    SENIOR_CITIZEN_AGE,
)
from backend.extensions import db
from backend.utils import isoformat, utcnow


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint(
            "role IN ('user', 'admin')", name="ck_users_role_valid"
        ),
        db.CheckConstraint(
            "account_status IN ('ACTIVE', 'RESTRICTED')",
            name="ck_users_account_status_valid",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_USER)
    share_display_name = db.Column(db.Boolean, nullable=False, default=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    senior_priority_opt_in = db.Column(db.Boolean, nullable=False, default=True)
    share_priority_status = db.Column(db.Boolean, nullable=False, default=True)
    account_status = db.Column(
        db.String(20), nullable=False, default=ACCOUNT_ACTIVE
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    bookings = db.relationship("Booking", back_populates="user", lazy="dynamic")
    notifications = db.relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_restricted(self):
        return self.account_status != ACCOUNT_ACTIVE

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = date.today()
        return (
            today.year
            - self.date_of_birth.year
            - (
                (today.month, today.day)
                < (self.date_of_birth.month, self.date_of_birth.day)
            )
        )

    def is_senior_citizen(self, threshold=SENIOR_CITIZEN_AGE):
        age = self.age
        return age is not None and age >= threshold

    def senior_priority_active(self, threshold=SENIOR_CITIZEN_AGE):
        return (
            self.is_senior_citizen(threshold)
            and self.senior_priority_opt_in
            and not self.is_restricted
        )

    def priority_public(self, threshold=SENIOR_CITIZEN_AGE):
        active = self.senior_priority_active(threshold)
        if not self.share_priority_status:
            return {
                "active": None,
                "shared": False,
                "label": "Private priority status",
            }
        return {
            "active": active,
            "shared": True,
            "label": "Senior citizen priority" if active else None,
        }

    def public_identity(self):
        if not self.share_display_name:
            return "Demo passenger"
        return self.display_name

    def _priority_threshold(self):
        if has_app_context():
            return int(
                current_app.config.get("SENIOR_CITIZEN_AGE", SENIOR_CITIZEN_AGE)
            )
        return SENIOR_CITIZEN_AGE

    def to_dict(self):
        threshold = self._priority_threshold()
        return {
            "id": self.id,
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "share_display_name": self.share_display_name,
            "date_of_birth": isoformat(self.date_of_birth),
            "age": self.age,
            "senior_citizen": self.is_senior_citizen(threshold),
            "senior_priority_active": self.senior_priority_active(threshold),
            "senior_priority_opt_in": self.senior_priority_opt_in,
            "share_priority_status": self.share_priority_status,
            "account_status": self.account_status,
            "created_at": isoformat(self.created_at),
        }

    def __repr__(self):
        return f"<User {self.email}>"
