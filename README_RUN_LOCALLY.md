# Running School Management locally

This is your Render project, packaged to run on your own laptop for debugging.
Locally it uses the SQLite database that's already bundled in `instance/school_management.db`
(no need to set up Postgres).

## Requirements
- Python 3.12 (matches `runtime.txt`). Any recent Python 3.10+ will likely work too.
- Download from https://www.python.org/downloads/ if you don't have it, and
  make sure "Add python to PATH" is checked during install (Windows).

## Quick start

**Mac / Linux**
```bash
./run_mac_linux.sh
```
If you get a "permission denied" error, run `chmod +x run_mac_linux.sh` first.

**Windows**
Double-click `run_windows.bat`, or run it from a terminal.

Either script will:
1. Create a virtual environment in `.venv/` (first run only)
2. Install everything in `requirements.txt`
3. Start the app at **http://127.0.0.1:5000**

Then open that URL in your browser.

## Login
- Email: `admin@school.com`
- Password: `support`

(This is the same seed admin account `app.py` creates automatically if the
`Staff` table is empty — see the bottom of `app.py`.)

## Manual setup (if you'd rather not use the scripts)
```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Debugging notes
- `FLASK_DEBUG=1` is set in `.env`, so Flask's debugger and auto-reload are on —
  code changes restart the server automatically, and errors show a full traceback
  in the browser.
- The app reads `DATABASE_URL` from `.env` and falls back to
  `sqlite:///school_management.db` if it's not set (see `_database_url()` near
  the top of `app.py`), so you're automatically using the local SQLite file
  rather than your Render Postgres database — safe to break/reset.
- To reset the local database to a clean slate, delete
  `instance/school_management.db` and restart the app; it will recreate the
  tables and the admin account on startup.
- A backup copy of the DB is already sitting in `instance/backups/` if you want
  to restore it instead.
- Schema migrations live in `migrations/` (Flask-Migrate/Alembic) if you need
  to run `flask db upgrade` / `flask db migrate` against this DB.

## What was removed from the Render copy
- `.git/` history and `__MACOSX/` / `.DS_Store` junk from the zip
- `Archive.zip` (a redundant duplicate backup already inside the project)
- `*.bak` files

Everything else — templates, static assets, migrations, both databases — is
unchanged from what's on Render.
