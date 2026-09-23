# Database design — V8

V8 uses SQLAlchemy/Flask-SQLAlchemy with PostgreSQL as the production database and SQLite as the local development fallback.

- **Production:** Render PostgreSQL through `DATABASE_URL`.
- **Local development:** bundled SQLite through the same SQLAlchemy models.
- **Schema changes:** Alembic/Flask-Migrate.
- **Initial data migration:** `scripts/migrate_sqlite_to_postgres.py` copies the existing V7 SQLite data into a fresh PostgreSQL database and resets integer ID sequences.

The application does not hard-code a PostgreSQL password or connection string. Set `DATABASE_URL` as a Render environment variable.
