"""Small SQLite schema upgrader for the local demonstration database.

The project intentionally avoids a heavyweight migration workflow for the
single-file SQLite demo. New tables are created by ``db.create_all``; this
helper adds the few new columns to an existing database so an older seeded
database keeps working after an upgrade.
"""

from sqlalchemy import inspect, text

from backend.extensions import db

NEW_COLUMNS = {
    "users": {
        "date_of_birth": "DATE",
        "senior_priority_opt_in": "BOOLEAN NOT NULL DEFAULT 1",
        "share_priority_status": "BOOLEAN NOT NULL DEFAULT 1",
        "account_status": "VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'",
    },
    "exchange_requests": {
        "priority_tier": "VARCHAR(24) NOT NULL DEFAULT 'STANDARD'",
        "expires_at": "DATETIME",
    },
}


def ensure_schema_compatibility(app):
    with app.app_context():
        if db.engine.dialect.name != "sqlite":
            return
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        changed = False
        for table_name, columns in NEW_COLUMNS.items():
            if table_name not in tables:
                continue
            existing = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            for column_name, ddl in columns.items():
                if column_name in existing:
                    continue
                db.session.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"ADD COLUMN {column_name} {ddl}"
                    )
                )
                changed = True
        if changed:
            db.session.commit()
            app.logger.info("Applied local SQLite schema compatibility columns.")
