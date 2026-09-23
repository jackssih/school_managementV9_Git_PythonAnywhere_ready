# Version 9 — Git -> PythonAnywhere deployment

This package is prepared to be pushed to a Git repository and then deployed on PythonAnywhere.

## Database design

Version 9 intentionally does **not** use Flask-Migrate/Alembic. On first startup, `db.create_all()` builds a fresh schema from `models.py`. No old SQLite database, migration history, students, classes, marks, attendance, reports, or other demo data are included. Only a minimal School record and the initial admin account are created so the system can be opened.

Initial login:
- Email: `admin@school.com`
- Password: `support`

Change the password after logging in.

## Git workflow

Push this folder to a new GitHub/GitLab repository. Do **not** commit `.env` or `instance/*.db`.

After the first PythonAnywhere deployment, future updates should be made locally, committed, and pushed to Git. In PythonAnywhere, update the checkout with `git pull` and reload the Web app. Do not edit application files directly in the PythonAnywhere editor.

## PythonAnywhere

Project directory:
`/home/EurekaScholaPrimaSolution/mysite`

Use Python 3.12. The included `wsgi.py` is already configured for this exact project path; copy its contents into the PythonAnywhere Web WSGI configuration file if needed.

Recommended virtualenv:
`/home/EurekaScholaPrimaSolution/.virtualenvs/mysite-venv`

Install dependencies from the repository:
`pip install -r /home/EurekaScholaPrimaSolution/mysite/requirements.txt`

Set a long random `SECRET_KEY` in PythonAnywhere's Web app environment variables. Leave `DATABASE_URL` unset for the fresh SQLite database.

After the first load, the database will be created automatically under the Flask instance directory.

## Updating

1. Edit locally.
2. Test locally.
3. `git add .`
4. `git commit -m "Describe the change"`
5. `git push`
6. In PythonAnywhere console: `cd /home/EurekaScholaPrimaSolution/mysite && git pull`
7. If dependencies changed: `pip install -r requirements.txt`
8. Reload the Web app.

Do not run old `flask db upgrade` commands against this Version 9 database.
