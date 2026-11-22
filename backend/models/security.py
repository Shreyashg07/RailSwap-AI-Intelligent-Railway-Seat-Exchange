import json

from backend.constants import (
    FRAUD_ALERT_OPEN,
    FRAUD_ALERT_STATUSES,
    FRAUD_SEVERITIES,
)
from backend.extensions import db
from backend.utils import isoformat, utcnow


class LoginAttempt(db.Model):
    """Persisted sign-in attempt metadata for lockout and admin summaries.

    Email addresses are stored as salted hashes, never as plaintext. The raw IP
    address is retained only for short-window abuse review in this local demo.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (
        db.Index("ix_login_attempts_email_created", "email_hash", "created_at"),
        db.Index("ix_login_attempts_ip_created", "ip_address", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    email_hash = db.Column(db.String(64), nullable=False)
    ip_address = db.Column(db.String(64), nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    def to_admin_dict(self):
        return {
            "id": self.id,
            "email_reference": f"email-hash:{self.email_hash[:10]}",
            "ip_reference": "masked" if self.ip_address else None,
            "success": self.success,
            "created_at": isoformat(self.created_at),
        }

    def __repr__(self):
        return f"<LoginAttempt {self.email_hash[:10]} success={self.success}>"


class FraudAlert(db.Model):
    __tablename__ = "fraud_alerts"
    __table_args__ = (
        db.CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH')",
            name="ck_fraud_alerts_severity_valid",
        ),
        db.CheckConstraint(
            "status IN ('OPEN', 'RESOLVED', 'DISMISSED')",
            name="ck_fraud_alerts_status_valid",
        ),
        db.Index("ix_fraud_alerts_status_created", "status", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    alert_type = db.Column(db.String(60), nullable=False, index=True)
    severity = db.Column(db.String(16), nullable=False, default="MEDIUM")
    status = db.Column(db.String(20), nullable=False, default=FRAUD_ALERT_OPEN)
    summary = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    user = db.relationship("User", foreign_keys=[user_id])
    resolved_by = db.relationship("User", foreign_keys=[resolved_by_user_id])

    def details_public(self):
        try:
            parsed = json.loads(self.details or "{}")
        except (TypeError, ValueError):
            parsed = {}
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def to_admin_dict(self):
        return {
            "id": self.id,
            "user_reference": f"User #{self.user_id}" if self.user_id else "Unknown user",
            "alert_type": self.alert_type,
            "severity": self.severity,
            "status": self.status,
            "summary": self.summary,
            "details": self.details_public(),
            "created_at": isoformat(self.created_at),
            "updated_at": isoformat(self.updated_at),
            "resolved_at": isoformat(self.resolved_at),
            "resolved_by_reference": (
                f"Admin #{self.resolved_by_user_id}"
                if self.resolved_by_user_id
                else None
            ),
        }

    def __repr__(self):
        return f"<FraudAlert {self.alert_type} {self.status}>"
