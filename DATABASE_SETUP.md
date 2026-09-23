# Database setup — V8

## Local development

V8 still uses the bundled SQLite database by default:

```env
DATABASE_URL=sqlite:///school_management.db
```

The existing demo database remains in `instance/school_management.db`.

## Render / production

Use a Render PostgreSQL database and set:

```env
DATABASE_URL=postgresql://<user>:<password>@<host>/<database>
SECRET_KEY=<long-random-secret>
```

The application automatically normalizes Render's PostgreSQL URL to the psycopg 3 SQLAlchemy driver.

Render deployment should run:

```bash
pip install -r requirements.txt && flask --app app db upgrade
```

and start with:

```bash
gunicorn --workers 2 --timeout 120 app:app
```

The `/health` endpoint is available for Render health checks.

## Migrating the existing demo data

Use `scripts/migrate_sqlite_to_postgres.py` against a fresh PostgreSQL database. See `POSTGRES_MIGRATION.md` for the exact command.
