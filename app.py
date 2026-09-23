import csv
import io
import os
import re
import secrets
import shutil
import string
from datetime import date, datetime, timedelta
from functools import wraps
from urllib.parse import urlencode

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort, Response, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from models import (
    AcademicClass,
    Assessment,
    AssessmentResult,
    AttendanceMark,
    AttendanceRecord,
    DutyEntry,
    DutyShift,
    Enrollment,
    Event,
    GatePickupEntry,
    GatePickupWeek,
    PromotionDecision,
    PromotionRun,
    PromotionRunEntry,
    PublishedReport,
    ReportBatch,
    ReportComment,
    School,
    Staff,
    Student,
    Subject,
    Term,
    TimetableBoard,
    TimetableEntry,
    TimetableLegendEntry,
    TimetablePeriod,
    db,
)

app = Flask(__name__)
# Production-safe configuration. Local development still falls back to the bundled SQLite DB.
app.secret_key = os.getenv("SECRET_KEY", "dev-only-change-me")

def _database_url():
    """Normalize Render/Postgres URLs for psycopg 3 while preserving SQLite locally."""
    url = os.getenv("DATABASE_URL", "sqlite:///school_management.db")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url

app.config["SQLALCHEMY_DATABASE_URI"] = _database_url()
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

@app.template_global()
def pagination_url(**overrides):
    """Build the current page's URL with one or more query params swapped
    out (e.g. page=2, or per_page=50). Every other filter already on the
    URL — search, tab, sort, class, status — is carried over automatically,
    so the _pagination.html partial works on any table-listing page without
    that page having to wire up its own hidden fields for paging."""
    args = request.args.to_dict(flat=True)
    args.update({key: str(value) for key, value in overrides.items()})
    query = urlencode(args)
    return f"{request.path}?{query}" if query else request.path

# --- Profile photo / signature / logo uploads ---
#
# These used to be saved as files under static/images/... so they could be
# served directly by url_for('static', ...). Render's free web service has an
# ephemeral filesystem though — anything written there at runtime disappears
# the moment the instance redeploys, restarts, or spins down from inactivity
# — so a freshly-uploaded photo, signature, or logo could vanish without
# warning. To survive that, uploads are now read into memory and stored as
# bytes in the database instead (see Staff.photo_data/signature_data and
# School.logo_data in models.py), which lives in Postgres and isn't wiped.
#
# The *_path columns and the static/images/... folders are kept only for the
# handful of sample images already committed to the repo — those are safe
# because git, not the runtime filesystem, is what restores them on deploy.
ALLOWED_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

_MIMETYPES_BY_EXTENSION = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

BACKUP_SUBDIR = "backups"
BACKUP_DIR = os.path.join(app.instance_path, BACKUP_SUBDIR)
os.makedirs(BACKUP_DIR, exist_ok=True)


def allowed_photo(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_PHOTO_EXTENSIONS


def read_uploaded_image(file_storage):
    """Read an uploaded image into memory for database storage.

    Returns (data, mimetype), or (None, None) if nothing usable was
    uploaded. Callers should already have checked allowed_photo() on the
    filename before calling this.
    """
    if not file_storage or not file_storage.filename:
        return None, None
    ext = secure_filename(file_storage.filename).rsplit(".", 1)[1].lower()
    mimetype = file_storage.mimetype or _MIMETYPES_BY_EXTENSION.get(ext, "application/octet-stream")
    data = file_storage.read()
    if not data:
        return None, None
    return data, mimetype


def staff_photo_url(staff):
    """URL for a staff member's profile photo — database-backed image if one
    has been uploaded, else the legacy static-file path, else empty."""
    if not staff:
        return ""
    if staff.photo_data:
        return url_for("staff_photo_image", staff_id=staff.id, v=int(staff.updated_at.timestamp()) if staff.updated_at else 0)
    if staff.photo_path:
        return url_for("static", filename=staff.photo_path)
    return ""


def staff_signature_url(staff):
    """URL for a staff member's digital signature — same fallback order as
    staff_photo_url."""
    if not staff:
        return ""
    if staff.signature_data:
        return url_for("staff_signature_image", staff_id=staff.id, v=int(staff.updated_at.timestamp()) if staff.updated_at else 0)
    if staff.signature_path:
        return url_for("static", filename=staff.signature_path)
    return ""


def school_logo_url(school):
    """URL for the school logo — same fallback order as staff_photo_url."""
    if not school:
        return ""
    if school.logo_data:
        return url_for("school_logo_image", v=int(school.updated_at.timestamp()) if school.updated_at else 0)
    if school.logo_path:
        return url_for("static", filename=school.logo_path)
    return ""


@app.route("/uploads/staff/<int:staff_id>/photo")
def staff_photo_image(staff_id):
    staff = Staff.query.get_or_404(staff_id)
    if not staff.photo_data:
        abort(404)
    return Response(staff.photo_data, mimetype=staff.photo_mimetype or "image/png")


@app.route("/uploads/staff/<int:staff_id>/signature")
def staff_signature_image(staff_id):
    staff = Staff.query.get_or_404(staff_id)
    if not staff.signature_data:
        abort(404)
    return Response(staff.signature_data, mimetype=staff.signature_mimetype or "image/png")


@app.route("/uploads/school/logo")
def school_logo_image():
    school = get_school()
    if not school or not school.logo_data:
        abort(404)
    return Response(school.logo_data, mimetype=school.logo_mimetype or "image/png")


# --- Login & access control ---
#
# Sessions store just the staff id. current_staff_account() is the single
# place that resolves "who is this" for every page, so login enforcement,
# role checks, and the topbar avatar all agree with each other.
#
# Endpoints in ADMIN_ONLY_ENDPOINTS are the "whole system" parts of the app:
# staff accounts, academic setup (classes/subjects/enrollment/terms), the
# timetable/duty/gate rota builders, events, and Settings itself. A teacher
# account can reach everything else — Home, their own Profile, Students,
# Grades, Attendance, Reports — which is where student data actually lives.
ADMIN_ONLY_ENDPOINTS = {
    # Settings (school profile, user accounts, appearance, backups)
    "settings_school", "save_school_settings", "settings_users", "settings_appearance",
    "save_appearance_settings", "reset_user_password", "toggle_user_active",
    "settings_backup", "download_backup", "restore_backup", "settings_index",
    # Staff accounts (as opposed to student records)
    "new_staff", "download_staff_upload_template", "bulk_upload_staff",
    "edit_staff", "delete_staff",
    # Academic setup — classes, subjects, enrollment, promotion, terms
    "academics", "academic_subjects_class", "new_academic_class", "edit_academic_class", "delete_academic_class",
    "download_class_students", "new_subject", "edit_subject", "delete_subject",
    "new_enrollment", "edit_enrollment", "unenroll_students", "update_promotion_decisions",
    "run_promotion", "undo_promotion", "undo_promotion_student",
    "save_term_dates", "switch_term",
    # Whole-school scheduling
    "events", "new_event", "edit_event", "delete_event",
    "timetable", "timetable_board", "save_duty_entry", "save_gate_entry",
    "new_gate_week", "edit_gate_week", "delete_gate_week", "edit_duty_shift",
    "print_duty_rota", "print_gate_rota", "new_timetable_board", "edit_timetable_board",
    "delete_timetable_board", "new_timetable_period", "delete_timetable_period",
    "move_timetable_period", "save_timetable_cell", "new_timetable_legend_entry",
    "delete_timetable_legend_entry", "print_timetable_board",
}

# Endpoints reachable without an active session.
PUBLIC_ENDPOINTS = {"login", "static", "school_logo_image"}


def generate_temp_password(length=10):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def set_staff_password(account, raw_password, remember_as_temp=False):
    account.password_hash = generate_password_hash(raw_password)
    # Only keep a plaintext copy when this is an admin-issued temporary password
    # (new account / password reset). A self-chosen password always wipes it.
    account.temp_password_plain = raw_password if remember_as_temp else ""


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("staff_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        account = current_staff_account()
        if not account or account.role != "admin":
            flash("That area is restricted to admin accounts.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def enforce_login_and_access():
    endpoint = request.endpoint
    if endpoint is None or endpoint in PUBLIC_ENDPOINTS:
        return None

    staff_id = session.get("staff_id")
    if not staff_id:
        return redirect(url_for("login", next=request.path))

    account = db.session.get(Staff, staff_id)
    if account is None or not account.is_active:
        session.clear()
        flash("Your session has ended. Please sign in again.", "error")
        return redirect(url_for("login"))

    if account.must_change_password and endpoint not in {"change_password", "logout"}:
        return redirect(url_for("change_password"))

    if account.role != "admin" and endpoint in ADMIN_ONLY_ENDPOINTS:
        flash("Your account has limited access and can't open that page. Ask an admin if you need it.", "error")
        return redirect(url_for("home"))

    return None

# --- Placeholder data (will move to the database once models are wired up) ---

SCHOOL_NAME = "School name"

# Fill these in with your real school details — they show in the report card
# footer and header. Leave any field blank to omit it from the printed card.
SCHOOL_INFO = {
    "type": "Primary School",     # subtitle shown under the school name, e.g. "International Primary School"
    "address": "",                # e.g. "Nakasamba Close Plot 10, Entebbe, Uganda"
    "phone": "",
    "email": "",
    "website": "",
    "reg_no": "",                 # e.g. a Ministry of Education registration number
    "logo_path": "images /Screenshot 2026-07-08 at 07.47.18.png",              # e.g. "images/logo.png" once you add a real logo file under static/images/
}

NAV_ITEMS = [
    {"label": "Home", "endpoint": "home"},
    {"label": "Profiles", "endpoint": "profiles"},
    {"label": "Academics", "endpoint": "academics"},
    {"label": "Grades", "endpoint": "grades"},
    {"label": "Attendance", "endpoint": "attendance"},
    {"label": "Reports", "endpoint": "reports"},
    {"label": "Timetable", "endpoint": "timetable"},
]

TERMS = [
    {"id": 1, "name": "Term 1, 2026", "start": date(2026, 2, 3), "end": date(2026, 5, 8)},
    {"id": 2, "name": "Term 2, 2026", "start": date(2026, 5, 25), "end": date(2026, 8, 14)},
    {"id": 3, "name": "Term 3, 2026", "start": date(2026, 9, 7), "end": date(2026, 12, 4)},
]

QUICK_ACTIONS = [
    {"icon": "ti-report", "title": "Enter grades", "subtitle": "Primary 5 — Maths", "endpoint": "grades"},
    {"icon": "ti-clipboard-check", "title": "Take attendance", "subtitle": "3 classes pending", "endpoint": "attendance"},
    {"icon": "ti-file-text", "title": "Generate report", "subtitle": "End of term", "endpoint": "reports"},
]

# Events are now backed by the database (Event in models.py). The list below
# is only used once, by seed_initial_database() — everything at runtime reads
# from the database via all_events() / event_records().
EVENT_RECORDS = [
    {"id": 1, "name": "Mid-term exams begin", "start_date": "14-07-2026", "end_date": "18-07-2026", "audience": "Whole school", "teacher": "Taaka Beatrice"},
    {"id": 2, "name": "Parents meeting", "start_date": "18-07-2026", "end_date": "18-07-2026", "audience": "Whole school", "teacher": "Support R"},
]

# --- Status rules ---
#
# Staff status is driven by account activity, not enrollment:
#   - "Active"                    -> the account has been created AND the person has logged in at least once
#   - "Account not activated yet" -> the account exists but they haven't logged in yet
#
# Student status is driven by enrollment, and will be set automatically once the
# Academics > Enrollment flow exists:
#   - "Active"   -> currently enrolled in a class for the current term
#   - "Inactive" -> not currently enrolled (never enrolled, withdrawn, or not yet promoted/re-enrolled)
#
# Both lists below store the raw facts (account_created / has_logged_in, enrolled_class)
# rather than a hardcoded status string, and status is computed with the functions below.
# That's the hook point: once real enrollment records exist, swap `enrolled_class` for a
# real lookup against the current term's class assignments and this logic doesn't change.

STAFF = [
    {"id": 1, "name": "Jackson Dance", "email": "jackson.dance@school.org", "phone": "", "role": "teacher", "account_created": True, "has_logged_in": False, "created_on": "21-04-2026"},
    {"id": 2, "name": "Elvin Ndoli", "email": "elvin.ndoli@school.org", "phone": "", "role": "teacher", "account_created": True, "has_logged_in": True, "created_on": "09-03-2026"},
    {"id": 3, "name": "Uwimana D'amour", "email": "uwimana.damour@school.org", "phone": "", "role": "teacher", "account_created": True, "has_logged_in": True, "created_on": "16-02-2026"},
    {"id": 4, "name": "Ishimwe Joselyne", "email": "ishimwe.joselyne@school.org", "phone": "", "role": "teacher", "account_created": True, "has_logged_in": True, "created_on": "10-07-2025"},
    {"id": 5, "name": "Raymond Gakwaya", "email": "raymond.gakwaya@school.org", "phone": "", "role": "teacher", "account_created": True, "has_logged_in": True, "created_on": "04-02-2026"},
    {"id": 6, "name": "Eddy Sheja", "email": "eddy.sheja@school.org", "phone": "", "role": "teacher", "account_created": True, "has_logged_in": True, "created_on": "08-12-2025"},
    {"id": 7, "name": "Dushime Alipe", "email": "dushime.alipe@school.org", "phone": "", "role": "teacher", "account_created": True, "has_logged_in": True, "created_on": "11-04-2025"},
    {"id": 8, "name": "Support R", "email": "support.r@school.org", "phone": "", "role": "admin", "account_created": True, "has_logged_in": True, "created_on": "04-09-2025"},
    {"id": 9, "name": "Rene Mucyo", "email": "rene.mucyo@school.org", "phone": "", "role": "teacher", "account_created": True, "has_logged_in": False, "created_on": "14-10-2025"},
]

STUDENTS = [
    {"id": 1, "registration_number": "STU-2026-001", "name": "Nabirye Grace", "gender": "Female", "lin": "", "date_of_birth": "2015-03-12", "enrolled_class": "Primary 5", "created_on": "12-01-2026"},
    {"id": 2, "registration_number": "STU-2026-002", "name": "Okello Brian", "gender": "Male", "lin": "UG-LIN-88213", "date_of_birth": "2016-07-01", "enrolled_class": "Primary 3", "created_on": "12-01-2026"},
    {"id": 3, "registration_number": "STU-2026-003", "name": "Achen Mercy", "gender": "Female", "lin": "", "date_of_birth": "2014-11-23", "enrolled_class": "", "created_on": "03-02-2026"},
    {"id": 4, "registration_number": "STU-2026-004", "name": "Kato Emmanuel", "gender": "Male", "lin": "UG-LIN-90042", "date_of_birth": "2015-01-09", "enrolled_class": "Primary 4", "created_on": "20-01-2026"},
]

# --- Academics seed data ---
#
# Classes, subjects, enrollment, and promotion decisions are now backed by the
# database (AcademicClass, Subject, Enrollment, PromotionDecision in models.py).
# The lists below are only used once, by seed_initial_database(), to populate
# the first rows — everything at runtime reads from the database via
# all_academic_classes() / all_subjects() / all_enrollments() / PromotionDecision.

ACADEMIC_CLASSES = [
    {"id": 1, "name": "Primary 1", "teacher": "Jackson Dance"},
    {"id": 2, "name": "Primary 2", "teacher": "Elvin Ndoli"},
    {"id": 3, "name": "Primary 3", "teacher": "Uwimana D'amour"},
    {"id": 4, "name": "Primary 4", "teacher": "Ishimwe Joselyne"},
    {"id": 5, "name": "Primary 5", "teacher": "Raymond Gakwaya"},
    {"id": 6, "name": "Primary 6", "teacher": "Eddy Sheja"},
    {"id": 7, "name": "Primary 7", "teacher": "Dushime Alipe"},
]

SUBJECTS = [
    {"id": 1, "name": "Mathematics", "class_name": "Primary 5", "maximum_mark": 100, "is_compulsory": True, "teacher": "Raymond Gakwaya"},
    {"id": 2, "name": "English", "class_name": "Primary 4", "maximum_mark": 100, "is_compulsory": True, "teacher": "Ishimwe Joselyne"},
    {"id": 3, "name": "Science", "class_name": "Primary 3", "maximum_mark": 100, "is_compulsory": True, "teacher": "Uwimana D'amour"},
    {"id": 4, "name": "French", "class_name": "Primary 3", "maximum_mark": 100, "is_compulsory": False, "teacher": "Uwimana D'amour"},
]

ENROLLMENTS = [
    {"id": 1, "date": "12-01-2026", "class_name": "Primary 5", "description": "Primary 5 enrollment", "student_ids": [1], "status": "Enrolled"},
    {"id": 2, "date": "12-01-2026", "class_name": "Primary 3", "description": "Primary 3 enrollment", "student_ids": [2], "status": "Enrolled"},
    {"id": 3, "date": "20-01-2026", "class_name": "Primary 4", "description": "Primary 4 enrollment", "student_ids": [4], "status": "Enrolled"},
]

# "Other subject" used to be a selectable assessment type here. It's no longer
# needed as a choice: whether an assessment is marks-graded or letter-graded
# is now derived automatically from the subject's own "is_compulsory" flag
# (see is_other_subject_assessment). Staff just pick the real assessment
# period below for every subject, compulsory or not.
ASSESSMENT_TYPES = [
    "B.O.T.",
    "Mid",
    "E.O.T Internal",
    "E.O.T External",
]

# Which printed report a comment belongs to: the full end of term report
# card, or the short mini report slip class teachers also fill in at the
# Beginning-of-term and Mid-term checkpoints.
COMMENT_REPORT_STAGES = [
    "End of term",
    "Mini report (Mid-term / BOT)",
]

# Assessments and results are now backed by the database (Assessment,
# AssessmentResult in models.py). The lists below are only used once, by
# seed_initial_database(), to populate the first rows — everything at runtime
# reads from the database via all_assessments() / assessment_result_map().
GRADING_ASSESSMENTS = [
    {"id": 1, "date": "01-05-2026", "class_name": "Primary 5", "subject": "Mathematics", "subject_id": 1, "assessment_type": "Mid", "maximum": 100},
    {"id": 2, "date": "01-05-2026", "class_name": "Primary 4", "subject": "English", "subject_id": 2, "assessment_type": "B.O.T.", "maximum": 100},
    {"id": 3, "date": "01-05-2026", "class_name": "Primary 3", "subject": "French", "subject_id": 4, "assessment_type": "Mid", "maximum": 5},
]

ASSESSMENT_RESULTS = {
    1: {1: {"mark": 92, "aggregate": "1"}},
    2: {},
    3: {2: {"mark": "", "grade": "B", "remark": "Good grasp of vocabulary, needs more speaking practice."}},
}

# Report comments and report batches are now backed by the database
# (ReportComment, ReportBatch, PublishedReport in models.py). The lists below
# are only used once, by seed_initial_database() — everything at runtime
# reads from the database via all_report_comments() / all_report_batches() /
# all_published_reports(). PUBLISHED_REPORTS stays empty; every published
# report from here on is created by the publish route, not seeded.
REPORT_COMMENTS = [
    {"id": 1, "student_id": 1, "class_name": "Primary 5", "comment_type": "Class teacher", "comment": "Strong performance and consistent effort.", "teacher": "Raymond Gakwaya", "report_stage": "End of term"},
    {"id": 2, "student_id": 2, "class_name": "Primary 3", "comment_type": "Head teacher", "comment": "Keep working steadily next term.", "teacher": "Taaka Beatrice", "report_stage": "End of term"},
]

# Attendance is now backed by the database (AttendanceRecord, AttendanceMark
# in models.py). The lists below are only used once, by
# seed_initial_database(), to populate the first rows — everything at runtime
# reads from the database via all_attendance_records() / attendance_mark_map().
ATTENDANCE_TYPES = ["Class", "Event", "Subject"]
ATTENDANCE_STATUSES = ["Present", "Absent", "Late", "Sick"]

ATTENDANCE_RECORDS = [
    {"id": 1, "date": "07-07-2026", "attendance_type": "Class", "session": "Day", "entity": "Primary 5", "class_name": "Primary 5"},
    {"id": 2, "date": "07-07-2026", "attendance_type": "Subject", "session": "Period 1", "entity": "Mathematics", "class_name": "Primary 5"},
    {"id": 3, "date": "07-07-2026", "attendance_type": "Event", "session": "Day", "entity": "Parents meeting", "class_name": ""},
]

ATTENDANCE_MARKS = {
    1: {1: {"status": "Present", "time": "08:00"}},
    2: {},
    3: {},
}

REPORT_TYPES = [
    "Attendance report",
    "Beginning of term",
    "Mid-term",
    "End of term",
    "Assessment report",
]

REPORT_BATCHES = [
    {"id": 1, "class_name": "Primary 5", "report_type": "End of term", "created_at": "07-07-2026 12:30", "status": "Generated", "generated_student_ids": [1]},
    {"id": 2, "class_name": "Primary 3", "report_type": "Mid-term", "created_at": "07-07-2026 12:35", "status": "Generated", "generated_student_ids": [2]},
]

PUBLISHED_REPORTS = []


def parse_seed_date(value):
    if isinstance(value, date):
        return value
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except (TypeError, ValueError):
            continue
    return date.today()


def parse_strict_date(value):
    """Parse a date value from a bulk-upload spreadsheet, returning None if
    nothing matches.

    Accepts the two formats documented on the download template
    (DD-MM-YYYY, YYYY-MM-DD) plus the other date styles a spreadsheet
    commonly produces: slash- and dot-separated, two-digit years, "12 Mar
    2015" / "March 12, 2015" style names, and the raw serial number
    Excel/Google Sheets sometimes exports a date column as when a CSV is
    re-saved under a different regional format.

    Unlike parse_seed_date (used for trusted seed data, which falls back to
    today's date), bulk-upload input is user-supplied and a bad date should be
    reported back as a skipped row rather than silently defaulted.
    """
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    # Excel/Sheets date serial number (days since 1899-12-30) — what a date
    # column sometimes turns into once a spreadsheet app re-exports the CSV
    # under a different regional/number format, e.g. "42074".
    if text.isdigit() and 4 <= len(text) <= 5:
        serial = int(text)
        if 1 <= serial <= 60000:
            return date(1899, 12, 30) + timedelta(days=serial)

    formats = (
        "%d-%m-%Y", "%Y-%m-%d",               # already-documented dash formats
        "%d/%m/%Y", "%Y/%m/%d",               # slash formats (DD/MM/YYYY is the common one outside the US)
        "%d.%m.%Y", "%Y.%m.%d",               # dot formats
        "%d-%m-%y", "%d/%m/%y", "%d.%m.%y",   # two-digit year
        "%d %B %Y", "%d %b %Y",               # "12 March 2015" / "12 Mar 2015"
        "%d-%B-%Y", "%d-%b-%Y",               # "12-March-2015" / "12-Mar-2015"
        "%B %d, %Y", "%b %d, %Y",             # "March 12, 2015" / "Mar 12, 2015"
        "%B %d %Y", "%b %d %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except (TypeError, ValueError):
            continue
    return None


def generate_registration_number():
    """Auto-generate the next STU-<year>-<seq> registration number.

    Registration is per calendar year; the sequence is based on how many
    students already carry that year's prefix, then nudged forward on
    collision so re-runs after manual edits still land on a free number.
    """
    year = date.today().year
    prefix = f"STU-{year}-"
    seq = Student.query.filter(Student.registration_number.like(f"{prefix}%")).count() + 1
    candidate = f"{prefix}{seq:03d}"
    while Student.query.filter_by(registration_number=candidate).first():
        seq += 1
        candidate = f"{prefix}{seq:03d}"
    return candidate


def read_csv_upload(file_storage):
    """Decode an uploaded CSV FileStorage into a list of dict rows.

    Header names are trimmed and lower-cased so the sheet can use any
    reasonable casing/spacing (e.g. "Full Name", " email ").
    """
    raw = file_storage.stream.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    reader.fieldnames = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    return list(reader)


def get_school():
    """The single School row — settings, report footers, and printed
    timetables all read school details from here (Settings > School profile
    is what edits it)."""
    return School.query.first()


def school_info_dict(school):
    if not school:
        return {**SCHOOL_INFO, "logo_url": ""}
    return {
        "type": school.type,
        "address": school.address,
        "phone": school.phone,
        "email": school.email,
        "website": school.website,
        "reg_no": school.reg_no,
        "logo_path": school.logo_path,
        "logo_url": school_logo_url(school),
    }


def seed_initial_database():
    """Copy the current starter data into the first database tables once."""
    if School.query.first():
        return

    db.session.add(
        School(
            name=SCHOOL_NAME,
            type=SCHOOL_INFO.get("type", ""),
            address=SCHOOL_INFO.get("address", ""),
            phone=SCHOOL_INFO.get("phone", ""),
            email=SCHOOL_INFO.get("email", ""),
            website=SCHOOL_INFO.get("website", ""),
            reg_no=SCHOOL_INFO.get("reg_no", ""),
            logo_path=SCHOOL_INFO.get("logo_path", ""),
        )
    )

    staff_by_name = {}
    for term in TERMS:
        db.session.add(
            Term(
                id=term["id"],
                name=term["name"],
                start_date=term["start"],
                end_date=term["end"],
                is_active=term["id"] == 2,
            )
        )

    for member in STAFF:
        staff = Staff(
            id=member["id"],
            name=member["name"],
            email=member["email"],
            phone=member.get("phone", ""),
            role=member.get("role", "teacher"),
            account_created=member.get("account_created", True),
            has_logged_in=member.get("has_logged_in", False),
            created_on=parse_seed_date(member.get("created_on")),
        )
        staff_by_name[staff.name] = staff
        db.session.add(staff)

    student_by_id = {}
    for student in STUDENTS:
        student_row = Student(
            id=student["id"],
            registration_number=student["registration_number"],
            name=student["name"],
            gender=student.get("gender", ""),
            lin=student.get("lin", ""),
            date_of_birth=parse_seed_date(student.get("date_of_birth")) if student.get("date_of_birth") else None,
            current_class_name=student.get("enrolled_class", ""),
            created_on=parse_seed_date(student.get("created_on")),
        )
        student_by_id[student_row.id] = student_row
        db.session.add(student_row)

    class_by_name = {}
    for class_record in ACADEMIC_CLASSES:
        academic_class = AcademicClass(
            id=class_record["id"],
            name=class_record["name"],
            level=class_level(class_record["name"]),
            class_teacher=staff_by_name.get(class_record.get("teacher", "")),
        )
        class_by_name[academic_class.name] = academic_class
        db.session.add(academic_class)

    subject_by_id = {}
    for subject in SUBJECTS:
        class_record = class_by_name.get(subject["class_name"])
        if not class_record:
            continue
        subject_row = Subject(
            id=subject["id"],
            name=subject["name"],
            academic_class=class_record,
            maximum_mark=subject.get("maximum_mark", 100),
            is_compulsory=subject.get("is_compulsory", True),
            teacher=staff_by_name.get(subject.get("teacher", "")),
        )
        subject_by_id[subject_row.id] = subject_row
        db.session.add(subject_row)

    for enrollment in ENROLLMENTS:
        class_record = class_by_name.get(enrollment["class_name"])
        if not class_record:
            continue
        db.session.add(
            Enrollment(
                id=enrollment["id"],
                date=parse_seed_date(enrollment.get("date")),
                academic_class=class_record,
                status=enrollment.get("status", "Enrolled"),
                students=[
                    student_by_id[sid] for sid in enrollment.get("student_ids", []) if sid in student_by_id
                ],
            )
        )

    for assessment in GRADING_ASSESSMENTS:
        subject_row = subject_by_id.get(assessment.get("subject_id"))
        if not subject_row:
            continue
        db.session.add(
            Assessment(
                id=assessment["id"],
                date=parse_seed_date(assessment.get("date")),
                subject=subject_row,
                assessment_type=assessment.get("assessment_type", ""),
                maximum=assessment.get("maximum", 100),
            )
        )
        for student_id, result in ASSESSMENT_RESULTS.get(assessment["id"], {}).items():
            if student_id not in student_by_id:
                continue
            db.session.add(
                AssessmentResult(
                    assessment_id=assessment["id"],
                    student_id=student_id,
                    mark=str(result.get("mark", "")),
                    aggregate=result.get("aggregate", ""),
                    grade=result.get("grade", ""),
                    remark=result.get("remark", ""),
                )
            )

    for comment in REPORT_COMMENTS:
        if comment["student_id"] not in student_by_id:
            continue
        db.session.add(
            ReportComment(
                id=comment["id"],
                student_id=comment["student_id"],
                comment_type=comment["comment_type"],
                comment=comment["comment"],
                teacher=comment.get("teacher", ""),
                report_stage=comment.get("report_stage", "End of term"),
            )
        )

    for batch in REPORT_BATCHES:
        class_record = class_by_name.get(batch["class_name"])
        if not class_record:
            continue
        db.session.add(
            ReportBatch(
                id=batch["id"],
                academic_class=class_record,
                report_type=batch["report_type"],
                generated_at=datetime.strptime(batch["created_at"], "%d-%m-%Y %H:%M"),
                status=batch.get("status", "Pending"),
                students=[
                    student_by_id[sid] for sid in batch.get("generated_student_ids", []) if sid in student_by_id
                ],
            )
        )
    # PUBLISHED_REPORTS starts empty in the seed data, so there's nothing to
    # copy into PublishedReport here — every row in that table from now on
    # is created by the /reports/<id>/publish route.

    for record in ATTENDANCE_RECORDS:
        class_record = class_by_name.get(record.get("class_name", ""))
        subject_row = None
        if record["attendance_type"] == "Subject":
            subject_row = next(
                (s for s in subject_by_id.values() if s.name == record["entity"]), None
            )
        db.session.add(
            AttendanceRecord(
                id=record["id"],
                date=parse_seed_date(record.get("date")),
                attendance_type=record["attendance_type"],
                session=record.get("session", ""),
                entity=record.get("entity", ""),
                academic_class=class_record,
                subject=subject_row,
            )
        )
        for student_id, mark in ATTENDANCE_MARKS.get(record["id"], {}).items():
            if student_id not in student_by_id:
                continue
            db.session.add(
                AttendanceMark(
                    attendance_record_id=record["id"],
                    student_id=student_id,
                    status=mark.get("status", ""),
                    time=mark.get("time", ""),
                )
            )

    for shift in DUTY_SHIFTS:
        db.session.add(
            DutyShift(id=shift["id"], label=shift["label"], time=shift.get("time", ""), sort_order=DUTY_SHIFTS.index(shift))
        )

    for day, shifts in DUTY_ROTA.items():
        for shift_id, names in shifts.items():
            for name in names:
                db.session.add(DutyEntry(day=day, shift_id=shift_id, staff_name=name))

    for week in GATE_PICKUP_WEEKS:
        db.session.add(GatePickupWeek(id=week["id"], label=week["label"], date_range=week.get("date_range", "")))
        for day, name in week.get("days", {}).items():
            db.session.add(GatePickupEntry(week_id=week["id"], day=day, staff_name=name))

    for board in TIMETABLES:
        board_row = TimetableBoard(
            id=board["id"],
            name=board["name"],
            layout=board.get("layout", "class_rows"),
            created_on=parse_seed_date(board.get("created_on")),
            class_records=[class_by_name[name] for name in board["classes"] if name in class_by_name],
        )
        db.session.add(board_row)

        period_by_seed_id = {}
        for index, period in enumerate(TIMETABLE_PERIODS.get(board["id"], [])):
            period_row = TimetablePeriod(
                board=board_row,
                start=period["start"],
                end=period["end"],
                label=period.get("label", ""),
                is_special=period.get("is_special", False),
                sort_order=index,
            )
            period_by_seed_id[period["id"]] = period_row
            db.session.add(period_row)

        for day, day_map in TIMETABLE_ENTRIES.get(board["id"], {}).items():
            for period_id, class_map in day_map.items():
                period_row = period_by_seed_id.get(period_id)
                if not period_row:
                    continue
                for class_name, cell in class_map.items():
                    class_record = class_by_name.get(class_name)
                    if not class_record:
                        continue
                    teacher_name = cell.get("teacher", "")
                    db.session.add(
                        TimetableEntry(
                            board=board_row,
                            day=day,
                            period=period_row,
                            academic_class=class_record,
                            subject=cell.get("subject", ""),
                            teacher=staff_by_name.get(teacher_name),
                        )
                    )

        for entry in TIMETABLE_LEGEND.get(board["id"], []):
            db.session.add(TimetableLegendEntry(board=board_row, code=entry["code"], name=entry["name"]))

    for event in EVENT_RECORDS:
        audience = event.get("audience", "Whole school")
        if audience == "Whole school":
            audience_mode = "Whole school"
            event_classes = []
        else:
            audience_mode = "Classes"
            event_classes = [
                class_by_name[name] for name in (n.strip() for n in audience.split(",")) if name in class_by_name
            ]
        db.session.add(
            Event(
                id=event["id"],
                name=event["name"],
                start_date=parse_seed_date(event.get("start_date")),
                end_date=parse_seed_date(event.get("end_date")),
                audience_mode=audience_mode,
                teacher=event.get("teacher", ""),
                classes=event_classes,
            )
        )

    db.session.commit()


@app.cli.command("init-db")
def init_db_command():
    """Create the current Version 9 schema without demo records."""
    db.create_all()
    print("Database initialized with the Version 9 schema (no demo data).")


def format_display_date(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return value.strftime("%d-%m-%Y")


def ordinal_date_label(value):
    """'14TH SEPT 2026' style label, for the report card's 'Next term
    commences on' line — matches the school's printed report format."""
    if not value:
        return ""
    day = value.day
    suffix = "TH" if 11 <= day % 100 <= 13 else {1: "ST", 2: "ND", 3: "RD"}.get(day % 10, "TH")
    return f"{day}{suffix} {value.strftime('%b').upper()} {value.year}"


def next_term_start_label(current_term):
    """The start date of the next term after the current one, formatted for
    display — used for the 'Next term commences on' line on report cards."""
    query = Term.query.order_by(Term.start_date)
    if current_term:
        query = query.filter(Term.start_date > current_term.start_date)
    next_term = query.first()
    return ordinal_date_label(next_term.start_date) if next_term else ""


_TERM_NUMBER_WORDS = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE", 6: "SIX"}


def term_title_parts(term):
    """('TWO', '2026') from a Term named like 'Term 2, 2026' — feeds the mini
    B.O.T./Mid-term slip's 'BEGINNING OF TERM TWO REPORT 2026.' heading."""
    if not term:
        return ("", "")
    match = re.search(r"(\d+).*?(\d{4})", term.name)
    if not match:
        return (term.name.upper(), "")
    number, year = match.groups()
    word = _TERM_NUMBER_WORDS.get(int(number), number)
    return (word, year)


def head_teacher_record():
    """The admin account treated as 'the head teacher' for the report
    card's signature line — the school's admin accounts stand in for that
    role since there's no separate head-teacher flag on Staff."""
    head_teacher = Staff.query.filter_by(role="admin").order_by(Staff.id).first()
    if not head_teacher:
        return {"name": "", "signature_url": ""}
    return {
        "name": head_teacher.name,
        "signature_url": staff_signature_url(head_teacher),
    }


def allowed_comment_teachers(class_name):
    """The only two people allowed to leave a report comment for a class:
    that class's own class teacher, and the school's head teacher. Used to
    build the restricted Teacher dropdown on the comment form and to check
    submissions server-side, so a comment can't be attributed to a teacher
    with no connection to the class."""
    academic_class = AcademicClass.query.filter_by(name=class_name).first() if class_name else None
    class_teacher_name = academic_class.class_teacher.name if academic_class and academic_class.class_teacher else ""
    return {
        "Class teacher": class_teacher_name,
        "Head teacher": head_teacher_record()["name"],
    }


def format_input_date(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return value.isoformat()


def initials_for(name):
    parts = (name or "").split()
    if not parts:
        return "?"
    return "".join(part[0] for part in parts[:2]).upper()


def current_staff_account():
    """The Staff row treated as "you" for the whole app — read from the
    session set by /login. Falls back to the admin account (or the first
    staff record) only when nothing is logged in, so pages don't hard-crash
    if this is ever called outside a request that's already gone through
    enforce_login_and_access."""
    staff_id = session.get("staff_id")
    if staff_id:
        account = db.session.get(Staff, staff_id)
        if account:
            return account
    return Staff.query.filter_by(role="admin").order_by(Staff.id).first() or Staff.query.order_by(Staff.id).first()


def staff_record(member):
    return {
        "id": member.id,
        "name": member.name,
        "email": member.email,
        "phone": member.phone,
        "role": member.role,
        "initials": initials_for(member.name),
        "photo_path": member.photo_path,
        "photo_url": staff_photo_url(member),
        "signature_path": member.signature_path,
        "signature_url": staff_signature_url(member),
        "account_created": member.account_created,
        "has_logged_in": member.has_logged_in,
        "is_active": member.is_active,
        "created_on": format_display_date(member.created_on),
        "status": staff_status(member),
        "temp_password": member.temp_password_plain,
    }


def student_record(student):
    class_name = student.current_class_name or "Not enrolled"
    return {
        "id": student.id,
        "registration_number": student.registration_number,
        "name": student.name,
        "gender": student.gender,
        "lin": student.lin,
        "date_of_birth": format_input_date(student.date_of_birth),
        "enrolled_class": student.current_class_name,
        "class_name": class_name,
        "created_on": format_display_date(student.created_on),
        "status": student_status(student),
    }


def staff_status(member):
    account_created = member["account_created"] if isinstance(member, dict) else member.account_created
    has_logged_in = member["has_logged_in"] if isinstance(member, dict) else member.has_logged_in
    if account_created and has_logged_in:
        return "Active"
    return "Account not activated yet"


def student_status(student):
    enrolled_class = student.get("enrolled_class") if isinstance(student, dict) else student.current_class_name
    return "Active" if enrolled_class else "Inactive"


def normalize_gender(value):
    """Accepts Male/Female (any case), or M/F shorthand, from CSV uploads.
    Returns "Male", "Female", or "" if the value doesn't match either.
    """
    value = (value or "").strip().lower()
    if value in ("male", "m"):
        return "Male"
    if value in ("female", "f"):
        return "Female"
    return ""


def next_id(records):
    return (max((r["id"] for r in records), default=0)) + 1


PAGE_SIZE_OPTIONS = [10, 25, 50, 100]
DEFAULT_PAGE_SIZE = 10


def paginate(records, default_per_page=DEFAULT_PAGE_SIZE):
    """Slice an already-filtered/sorted list of dict records for one page.

    Reads page/per_page straight off the current request's query string
    (per_page capped to PAGE_SIZE_OPTIONS) so every table-listing route can
    call this right before rendering instead of re-implementing paging.
    Returns (page_records, pagination) — pagination carries everything the
    _pagination.html partial needs to draw the rows-per-page selector and
    prev/next controls without any page-specific wiring.
    """
    try:
        per_page = int(request.args.get("per_page", default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page
    if per_page not in PAGE_SIZE_OPTIONS:
        per_page = default_per_page

    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)

    total = len(records)
    total_pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, total_pages)

    start = (page - 1) * per_page
    page_records = records[start:start + per_page]

    return page_records, {
        "page": page,
        "per_page": per_page,
        "page_size_options": PAGE_SIZE_OPTIONS,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "start_index": (start + 1) if total else 0,
        "end_index": min(start + per_page, total),
    }


def parse_created_on(value):
    """Parse the 'DD-MM-YYYY' created_on string into a datetime for sorting.

    Falls back to datetime.min for missing/malformed values so bad data
    doesn't crash the sort — it just sinks to the bottom of "newest first".
    """
    try:
        return datetime.strptime(value, "%d-%m-%Y")
    except (TypeError, ValueError):
        return datetime.min


def parse_date(value):
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except (TypeError, ValueError):
        return None


def format_event_date_range(event):
    # %-d (strip leading zero) is Linux/Mac-only; Windows needs %#d instead.
    # Formatting the day number manually sidesteps the platform difference entirely.
    def month_day(d):
        return f"{d.strftime('%b')} {d.day}"

    def day_only(d):
        return str(d.day)

    start = parse_date(event.get("start_date"))
    end = parse_date(event.get("end_date"))
    if not start:
        return event.get("start_date", "")
    if not end or start == end:
        return month_day(start)
    if start.month == end.month:
        return f"{month_day(start)} - {day_only(end)}"
    return f"{month_day(start)} - {month_day(end)}"


def event_activity(event, today=None):
    today = today or date.today()
    start = parse_date(event.get("start_date"))
    end = parse_date(event.get("end_date")) or start
    if not start:
        return "Pending"
    if start <= today <= end:
        return "Active"
    if today > end:
        return "Passed"
    return "Pending"


def event_record_dict(event):
    """Same dict shape the old EVENT_RECORDS placeholder used."""
    if event.audience_mode == "Classes":
        audience = ", ".join(c.name for c in event.classes) or "Whole school"
    else:
        audience = "Whole school"
    return {
        "id": event.id,
        "name": event.name,
        "start_date": event.start_date.strftime("%d-%m-%Y") if event.start_date else "",
        "end_date": event.end_date.strftime("%d-%m-%Y") if event.end_date else "",
        "audience": audience,
        "teacher": event.teacher,
    }


def all_events():
    """Every event, in the same dict shape EVENT_RECORDS used."""
    return [event_record_dict(e) for e in Event.query.order_by(Event.id).all()]


def event_records(today=None):
    return [
        {
            **event,
            "date_range": f"{event['start_date']} to {event['end_date']}",
            "activity": event_activity(event, today=today),
            "date_label": format_event_date_range(event),
            "calendar_start": parse_date(event["start_date"]).isoformat() if parse_date(event["start_date"]) else "",
            "calendar_end": parse_date(event["end_date"]).isoformat() if parse_date(event["end_date"]) else "",
        }
        for event in all_events()
    ]


def calendar_event_payload():
    return [
        {
            "title": record["name"],
            "start": record["calendar_start"],
            "end": record["calendar_end"],
            "activity": record["activity"],
        }
        for record in event_records()
    ]


def all_students():
    """Every student, in the same dict shape the old STUDENTS placeholder used."""
    return [student_record(s) for s in Student.query.all()]


def academic_class_record(academic_class):
    return {
        "id": academic_class.id,
        "name": academic_class.name,
        "teacher": academic_class.class_teacher.name if academic_class.class_teacher else "",
    }


def all_academic_classes():
    """Every class, in the same dict shape the old ACADEMIC_CLASSES placeholder used."""
    return [academic_class_record(c) for c in AcademicClass.query.order_by(AcademicClass.name).all()]


def subject_record_dict(subject):
    return {
        "id": subject.id,
        "name": subject.name,
        "class_name": subject.academic_class.name if subject.academic_class else "",
        "maximum_mark": subject.maximum_mark,
        "is_compulsory": subject.is_compulsory,
        "teacher": subject.teacher.name if subject.teacher else "",
    }


def all_subjects():
    """Every subject, in the same dict shape the old SUBJECTS placeholder used."""
    return [subject_record_dict(s) for s in Subject.query.all()]


def enrollment_record_dict(enrollment):
    class_name = enrollment.academic_class.name if enrollment.academic_class else ""
    return {
        "id": enrollment.id,
        "date": format_display_date(enrollment.date),
        "class_name": class_name,
        "description": f"{class_name} enrollment" if class_name else "",
        "student_ids": [s.id for s in enrollment.students],
        "status": enrollment.status,
    }


def all_enrollments():
    """Every enrollment record, in the same dict shape the old ENROLLMENTS placeholder used."""
    return [enrollment_record_dict(e) for e in Enrollment.query.order_by(Enrollment.id).all()]


def get_class_filter_options():
    """Classes offered in the student filter dropdown.

    Pulls from every class on record (not just classes currently in use), so a
    class shows up in the filter even before anyone is enrolled in it. "Not
    enrolled" is appended so students without a class can still be filtered on.
    """
    return [c["name"] for c in all_academic_classes()] + ["Not enrolled"]


def get_class_students(class_name):
    return [student_record(s) for s in Student.query.filter_by(current_class_name=class_name).all()]


def class_level(class_name):
    normalized = class_name.lower().replace(".", "").replace("primary", "p").strip()
    for number in range(1, 8):
        if normalized.startswith(f"p {number}") or normalized.startswith(f"p{number}"):
            if number <= 3:
                return "Lower primary"
            if number <= 5:
                return "Upper primary"
            return "Candidate class"
    return "Primary"


def find_subject_for_assessment(assessment):
    """Look up the Subject an assessment belongs to.

    Prefers subject_id (set on every assessment created going forward); falls
    back to matching on name + class for any older records that predate the
    subject_id link.
    """
    subjects = all_subjects()
    subject_id = assessment.get("subject_id")
    if subject_id is not None:
        subject = next((s for s in subjects if s["id"] == subject_id), None)
        if subject:
            return subject
    return next(
        (s for s in subjects if s["name"] == assessment.get("subject") and s["class_name"] == assessment.get("class_name")),
        None,
    )


def is_other_subject_assessment(assessment):
    """An assessment is letter-graded ("Other subject" style) when its subject
    is marked non-compulsory in Academics > Subjects. Compulsory subjects are
    marks-graded ("Major subject" style). If the subject can't be found
    (e.g. it was since deleted) we default to marks mode."""
    subject = find_subject_for_assessment(assessment)
    if subject is None:
        return False
    return not subject.get("is_compulsory", True)


def aggregate_from_mark(mark):
    try:
        score = int(mark)
    except (TypeError, ValueError):
        return ""
    if score >= 90:
        return "1"
    if score >= 80:
        return "2"
    if score >= 70:
        return "3"
    if score >= 60:
        return "4"
    if score >= 55:
        return "5"
    if score >= 50:
        return "6"
    if score >= 45:
        return "7"
    if score >= 40:
        return "8"
    return "9"


def get_student_names(student_ids):
    names = []
    for student_id in student_ids:
        student = Student.query.get(student_id)
        if student:
            names.append(student.name)
    return names


def teacher_names():
    return [m.name for m in Staff.query.filter_by(role="teacher").order_by(Staff.name).all()]


def students_payload(students):
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "registration_number": s["registration_number"],
            "class_name": s.get("enrolled_class") or "Not enrolled",
        }
        for s in students
    ]


def academic_class_records():
    records = []
    subjects = all_subjects()
    for class_record in all_academic_classes():
        class_students = get_class_students(class_record["name"])
        class_subjects = [s for s in subjects if s["class_name"] == class_record["name"]]
        records.append(
            {
                **class_record,
                "level": class_level(class_record["name"]),
                "enrolled_students": len(class_students),
                "subjects": len(class_subjects),
                "students": students_payload(class_students),
                "subject_names": [s["name"] for s in class_subjects],
            }
        )
    return records


def subject_records(class_id=None):
    records = []
    query = Subject.query
    if class_id is not None:
        query = query.filter_by(class_id=class_id)
    for subject in query.order_by(Subject.name).all():
        class_name = subject.academic_class.name if subject.academic_class else ""
        class_students = get_class_students(class_name)
        records.append(
            {
                **subject_record_dict(subject),
                "students_count": len(class_students),
                "students": students_payload(class_students),
                "is_compulsory_label": "Yes" if subject.is_compulsory else "No",
                "subject_type_label": "Major subject" if subject.is_compulsory else "Other subject",
            }
        )
    return records


def enrollment_records():
    records = []
    for enrollment in all_enrollments():
        students = get_student_names(enrollment["student_ids"])
        records.append(
            {
                **enrollment,
                "students_count": len(students),
                "students": students,
            }
        )
    return records


def enrollment_class_records():
    """Enrollment landing page: one clickable row per class, with the current
    class enrollment count. Classes are the source-of-truth level for enrollment.
    """
    records = []
    for class_record in all_academic_classes():
        students = get_class_students(class_record["name"])
        records.append({
            **class_record,
            "enrolled_students": len(students),
            "students": students_payload(students),
        })
    return records


def enrollment_student_records(class_id):
    """Students currently enrolled in a class, with their latest enrollment date."""
    academic_class = AcademicClass.query.get(class_id)
    if academic_class is None:
        return []
    students = Student.query.filter_by(current_class_name=academic_class.name).order_by(Student.name).all()
    records = []
    for student in students:
        dates = [e.date for e in Enrollment.query.filter_by(class_id=class_id).all() if student in e.students]
        enrolled_date = max(dates) if dates else student.created_on
        records.append({
            **student_record(student),
            "enrollment_date": format_display_date(enrolled_date),
        })
    return records


def promotion_records():
    decisions = {d.student_id: d.decision for d in PromotionDecision.query.all()}
    records = []
    for class_record in all_academic_classes():
        class_students = get_class_students(class_record["name"])
        decision_counts = {"Promoted": 0, "Second sitting": 0, "Repeating": 0, "Discontinued": 0}
        for student in class_students:
            decision = decisions.get(student["id"])
            if decision in decision_counts:
                decision_counts[decision] += 1
        records.append(
            {
                "id": class_record["id"],
                "class_name": class_record["name"],
                "all_students": len(class_students),
                "students": students_payload(class_students),
                "promoted": decision_counts["Promoted"],
                "second_sitting": decision_counts["Second sitting"],
                "repeating": decision_counts["Repeating"],
                "discontinued": decision_counts["Discontinued"],
            }
        )
    return records


# --- Year-end promotion: move students up to the next class ---
#
# A class name like "P.2 A" / "p.2a" / "Primary 2A" is read as level 2,
# stream "A"; "Primary 3" is level 3, no stream. Promotion moves a student
# to the same stream one level up (P.2 A -> P.3 A) when that class exists,
# and otherwise into the single plain class at that level (P.3 A -> P.4,
# if there's no P.4 A) — matching how this school actually names streamed
# vs. unstreamed classes, rather than assuming every level is streamed.
CLASS_LEVEL_STREAM_RE = re.compile(r"^\s*(?:primary|p)\.?\s*([1-7])\s*([a-z]*)\s*$", re.IGNORECASE)
PROMOTION_STAY_DECISIONS = {"Repeating", "Second sitting"}
PROMOTION_DEFAULT_DECISION = "Promoted"


def parse_class_level_stream(class_name):
    """Split a class name into (level 1-7, stream '' or 'A'/'B'/...).

    Returns None when the name doesn't follow the Primary numbering
    pattern at all (a custom class name) — callers should leave those
    students alone rather than guess.
    """
    match = CLASS_LEVEL_STREAM_RE.match(class_name or "")
    if not match:
        return None
    return int(match.group(1)), match.group(2).strip().upper()


def resolve_promotion_target(current_class_name, class_names):
    """Work out which class a student in `current_class_name` moves into
    next year, matched against the school's own existing class list.

    Returns {"outcome": ..., "class_name": ..., "reason": ...} where
    outcome is:
      - "matched": class_name is the class to move them into.
      - "final_year": already in the top class (Primary 7) — there's
        nowhere further to go, so they've completed primary school. This
        is expected and is never treated as a problem to flag.
      - "unresolved": class_name is None and reason explains why —
        "not_primary_class" (name doesn't parse at all), "no_next_class"
        (no class at all exists at the next level — nothing to promote
        into), or "ambiguous_stream" (more than one stream exists at the
        next level and none of them, nor a single plain class, matches).
    """
    parsed = parse_class_level_stream(current_class_name)
    if parsed is None:
        return {"outcome": "unresolved", "class_name": None, "reason": "not_primary_class"}
    level, stream = parsed
    if level >= 7:
        return {"outcome": "final_year", "class_name": None, "reason": None}

    next_level = level + 1
    next_level_classes = []
    for name in class_names:
        parsed_next = parse_class_level_stream(name)
        if parsed_next and parsed_next[0] == next_level:
            next_level_classes.append((parsed_next[1], name))

    if not next_level_classes:
        return {"outcome": "unresolved", "class_name": None, "reason": "no_next_class"}

    plain_classes = [name for class_stream, name in next_level_classes if not class_stream]

    if stream:
        for class_stream, name in next_level_classes:
            if class_stream == stream:
                return {"outcome": "matched", "class_name": name, "reason": None}
        if len(plain_classes) == 1:
            return {"outcome": "matched", "class_name": plain_classes[0], "reason": None}
        return {"outcome": "unresolved", "class_name": None, "reason": "ambiguous_stream"}

    if len(plain_classes) == 1:
        return {"outcome": "matched", "class_name": plain_classes[0], "reason": None}
    if len(next_level_classes) == 1:
        return {"outcome": "matched", "class_name": next_level_classes[0][1], "reason": None}
    return {"outcome": "unresolved", "class_name": None, "reason": "ambiguous_stream"}


def latest_promotion_run():
    return PromotionRun.query.order_by(PromotionRun.id.desc()).first()


def promotion_run_summary(run):
    if run is None:
        return None
    entries = list(run.entries)
    active = [e for e in entries if not e.reverted]
    return {
        "id": run.id,
        "run_date": format_display_date(run.run_date),
        "status": run.status,
        "label": run.label,
        "moved": len([e for e in active if e.outcome == "Moved"]),
        "stayed": len([e for e in active if e.outcome == "Stayed"]),
        "completed": len([e for e in active if e.outcome == "Completed"]),
        "discontinued": len([e for e in active if e.outcome == "Discontinued"]),
        "unresolved": len([e for e in active if e.outcome == "Unresolved"]),
        "reverted": len(entries) - len(active),
        "entries": [
            {
                "id": e.id,
                "student_id": e.student_id,
                "student_name": e.student.name if e.student else "(removed student)",
                "decision": e.decision,
                "from_class_name": e.from_class_name,
                "to_class_name": e.to_class_name,
                "outcome": e.outcome,
                "reverted": e.reverted,
            }
            for e in entries
        ],
    }


def academic_redirect(tab):
    return url_for("academics", tab=tab)


def promotion_json_or_redirect(message, category="success"):
    """Same shape as json_or_redirect, but lets the flash use an "error"
    style for guard-clause notices (e.g. "nothing to promote") while still
    telling the promotion-tab modals (which submit over fetch/XHR) to
    navigate back so the flash actually shows up."""
    flash(message, category)
    redirect_url = academic_redirect("promotion")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


def json_or_redirect(tab, message):
    flash(message, "success")
    redirect_url = academic_redirect(tab)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


def grades_redirect(tab):
    return url_for("grades", tab=tab)


def grade_class_records(tab):
    """Grades landing page: one clickable row per arranged class.

    Assessments and comments both use the class as their first-level
    navigation, matching the Subjects and Enrollment structure in Academics.
    """
    assessment_list = assessment_records() if tab == "assessments" else []
    comment_list = comment_records() if tab == "comments" else []
    records = []
    for class_record in all_academic_classes():
        class_name = class_record["name"]
        students = get_class_students(class_name)
        subjects = [s for s in all_subjects() if s["class_name"] == class_name]
        assessments = [a for a in assessment_list if a["class_name"] == class_name]
        comments = [c for c in comment_list if c["class_name"] == class_name]
        records.append({
            **class_record,
            "level": class_level(class_name),
            "students_count": len(students),
            "subjects_count": len(subjects),
            "assessments_count": len(assessments),
            "comments_count": len(comments),
        })
    return records


def grades_json_or_redirect(tab, message, class_id=None, student_id=None):
    flash(message, "success")
    if tab == "comments" and class_id and student_id:
        redirect_url = url_for("grades_comment_student", class_id=class_id, student_id=student_id)
    elif class_id:
        redirect_url = url_for("grades_class", tab=tab, class_id=class_id)
    else:
        redirect_url = grades_redirect(tab)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


def assessment_record_dict(assessment):
    subject = assessment.subject
    return {
        "id": assessment.id,
        "date": format_display_date(assessment.date),
        "class_name": subject.academic_class.name if subject and subject.academic_class else "",
        "subject": subject.name if subject else "",
        "subject_id": assessment.subject_id,
        "assessment_type": assessment.assessment_type,
        "maximum": assessment.maximum,
    }


def all_assessments():
    """Every assessment, in the same dict shape the old GRADING_ASSESSMENTS placeholder used."""
    return [assessment_record_dict(a) for a in Assessment.query.order_by(Assessment.id).all()]


def assessment_result_map(assessment_id):
    """{student_id: {mark, aggregate, grade, remark}} for one assessment — the
    same shape ASSESSMENT_RESULTS.get(assessment_id) used to return."""
    results = AssessmentResult.query.filter_by(assessment_id=assessment_id).all()
    return {
        r.student_id: {"mark": r.mark, "aggregate": r.aggregate, "grade": r.grade, "remark": r.remark}
        for r in results
    }


def assessment_records():
    records = []
    for assessment in all_assessments():
        class_students = get_class_students(assessment["class_name"])
        result_map = assessment_result_map(assessment["id"])
        result_mode = "letter" if is_other_subject_assessment(assessment) else "marks"
        students = []
        for student in class_students:
            result = result_map.get(student["id"], {})
            students.append(
                {
                    "id": student["id"],
                    "name": student["name"],
                    "registration_number": student["registration_number"],
                    "mark": result.get("mark", ""),
                    "grade": result.get("grade", ""),
                    "aggregate": result.get("aggregate") or aggregate_from_mark(result.get("mark", "")),
                    "remark": result.get("remark", ""),
                }
            )
        records.append(
            {
                **assessment,
                "level": class_level(assessment["class_name"]),
                "result_mode": result_mode,
                "recorded_count": len(result_map),
                "total_students": len(class_students),
                "recorded_label": f"{len(result_map)}/{len(class_students)}",
                "students": students,
            }
        )
    return records


def report_comment_record_dict(comment):
    """Same dict shape the old REPORT_COMMENTS placeholder used. class_name
    is derived from the student's *current* class rather than stored, so it
    always reflects where the student is enrolled now — consistent with how
    every other converted module derives names through their relationships
    instead of duplicating them."""
    student = comment.student
    return {
        "id": comment.id,
        "student_id": comment.student_id,
        "class_name": (student.current_class_name if student else "") or "Not enrolled",
        "comment_type": comment.comment_type,
        "comment": comment.comment,
        "teacher": comment.teacher,
        "report_stage": comment.report_stage,
    }


def all_report_comments():
    """Every report comment, in the same dict shape REPORT_COMMENTS used."""
    return [report_comment_record_dict(c) for c in ReportComment.query.order_by(ReportComment.id).all()]


def report_batch_record_dict(batch):
    """Same dict shape the old REPORT_BATCHES placeholder used."""
    return {
        "id": batch.id,
        "class_name": batch.academic_class.name if batch.academic_class else "",
        "report_type": batch.report_type,
        "created_at": batch.generated_at.strftime("%d-%m-%Y %H:%M") if batch.generated_at else "",
        "status": batch.status,
        "attendance_scope": batch.report_scope or "",
        "generated_student_ids": [s.id for s in batch.students],
    }


def all_report_batches():
    """Every report batch (Reports > Report Cards tab), in the same dict
    shape REPORT_BATCHES used."""
    return [report_batch_record_dict(b) for b in ReportBatch.query.order_by(ReportBatch.id).all()]


def published_report_record_dict(published):
    """Same dict shape the old PUBLISHED_REPORTS placeholder used."""
    return {
        "id": published.id,
        "class_name": published.academic_class.name if published.academic_class else "",
        "report_type": published.report_type,
        "created_at": published.generated_at.strftime("%d-%m-%Y %H:%M") if published.generated_at else "",
        "status": "Generated",
        "generated_student_ids": [s.id for s in published.students],
        "published_at": published.published_at.strftime("%d-%m-%Y %H:%M") if published.published_at else "",
        "publish_here": published.publish_here,
        "publish_sms": published.publish_sms,
        "publish_email": published.publish_email,
        "email": published.email,
    }


def all_published_reports():
    """Every published report (Reports > Published tab), in the same dict
    shape PUBLISHED_REPORTS used."""
    return [published_report_record_dict(p) for p in PublishedReport.query.order_by(PublishedReport.id).all()]


def comment_records():
    records = []
    for comment in all_report_comments():
        student = next((s for s in all_students() if s["id"] == comment["student_id"]), None)
        records.append(
            {
                **comment,
                "student_name": student["name"] if student else "Unknown student",
                "level": class_level(comment["class_name"]),
            }
        )
    return records


def attendance_record_dict(record):
    class_name = record.academic_class.name if record.academic_class else (record.entity if record.attendance_type == "Class" else "")
    return {
        "id": record.id,
        "date": format_display_date(record.date),
        "attendance_type": record.attendance_type,
        "session": record.session,
        "entity": record.entity,
        "class_id": record.class_id,
        "class_name": class_name,
    }


def all_attendance_records():
    """Every attendance sheet, in the same dict shape the old ATTENDANCE_RECORDS placeholder used."""
    return [attendance_record_dict(r) for r in AttendanceRecord.query.order_by(AttendanceRecord.id).all()]


def attendance_mark_map(attendance_record_id):
    """{student_id: {status, time}} for one sheet — the same shape
    ATTENDANCE_MARKS.get(record_id) used to return."""
    marks = AttendanceMark.query.filter_by(attendance_record_id=attendance_record_id).all()
    return {m.student_id: {"status": m.status, "time": m.time} for m in marks}


def attendance_students(record):
    if record.get("class_name"):
        return get_class_students(record["class_name"])
    return [s for s in all_students() if s.get("enrolled_class")]


def attendance_records():
    records = []
    for record in all_attendance_records():
        students = attendance_students(record)
        marks = attendance_mark_map(record["id"])
        records.append(
            {
                **record,
                "recorded_count": len(marks),
                "total_students": len(students),
                "attendance_label": f"{len(marks)}/{len(students)}",
                "students": [
                    {
                        "id": student["id"],
                        "name": student["name"],
                        "registration_number": student["registration_number"],
                        "status": marks.get(student["id"], {}).get("status", ""),
                        "time": marks.get(student["id"], {}).get("time", ""),
                    }
                    for student in students
                ],
            }
        )
    return records


def todays_attendance_percentage(today=None):
    """Attendance card percentage based on the latest Class register per class.

    Only class attendance is counted (not subject/event registers), and each
    class is counted once. A complete day is therefore 100% when every student
    currently enrolled in the school's classes is marked Present.
    """
    today = today or date.today()
    students = Student.query.filter(Student.current_class_name.isnot(None), Student.current_class_name != "").all()
    total_students = len(students)
    if total_students == 0:
        return 0

    class_names = {s.current_class_name for s in students}
    present_ids = set()
    marked_ids = set()

    for class_name in class_names:
        class_record = AcademicClass.query.filter_by(name=class_name).first()
        if not class_record:
            continue
        attendance = (
            AttendanceRecord.query
            .filter_by(date=today, attendance_type="Class", class_id=class_record.id)
            .order_by(AttendanceRecord.id.desc())
            .first()
        )
        if not attendance:
            continue
        for mark in AttendanceMark.query.filter_by(attendance_record_id=attendance.id).all():
            if not mark.student_id:
                continue
            marked_ids.add(mark.student_id)
            if mark.status == "Present":
                present_ids.add(mark.student_id)

    # The numerator can only count students actually present; the denominator
    # is the live student roster, so a complete present tally reads 100%.
    present_count = len(present_ids)
    return round((present_count / total_students) * 100)


def attendance_redirect():
    return url_for("attendance")


def attendance_json_or_redirect(message, redirect_url=None):
    flash(message, "success")
    redirect_url = redirect_url or attendance_redirect()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


def reports_redirect(tab="cards"):
    return url_for("reports", tab=tab)


def reports_json_or_redirect(tab, message):
    flash(message, "success")
    redirect_url = reports_redirect(tab)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


def report_scope_rows(records, classes):
    """Rows shown on Reports > Report Cards before individual classes.

    The first three rows are report-generation scopes. They deliberately have
    no teacher because they represent groups rather than a single class.
    Individual class rows follow and can generate reports for that class only.
    """
    scopes = ["All classes", "Lower primary", "Upper primary"]
    rows = []
    for scope in scopes:
        scope_classes = report_classes_for_scope(scope)
        class_names = set(scope_classes)
        matching = [c for c in classes if c["name"] in class_names]
        report_count = sum(
            1 for r in records
            if r.get("class_name") in class_names or r.get("attendance_scope") == scope
        )
        student_count = sum(c.get("enrolled_students", 0) for c in matching)
        rows.append({
            "name": scope,
            "students": student_count,
            "reports": report_count,
            "teacher": "",
            "scope": scope,
            "is_group": True,
        })
    for c in classes:
        rows.append({
            "name": c["name"],
            "students": c.get("enrolled_students", 0),
            "reports": sum(1 for r in records if r.get("class_name") == c["name"]),
            "teacher": c.get("teacher", ""),
            "scope": c["name"],
            "class_id": c["id"],
            "is_group": False,
        })
    return rows


def report_classes_for_scope(scope):
    classes = all_academic_classes()
    if scope == "All classes":
        return [c["name"] for c in classes]
    if scope == "Lower primary":
        return [c["name"] for c in classes if class_level(c["name"]) == "Lower primary"]
    if scope == "Upper primary":
        return [c["name"] for c in classes if class_level(c["name"]) in ("Upper primary", "Candidate class")]
    return [scope] if any(c["name"] == scope for c in classes) else []


def report_stage_for_report_type(report_type):
    """Maps a Reports-module report type to the report_stage recorded on a
    ReportComment. Beginning-of-term and Mid-term reports use the class
    teacher's short 'mini report' comment; everything else (End of term,
    and any other report type) uses the full end of term comment."""
    if report_type in ("Beginning of term", "Mid-term"):
        return "Mini report (Mid-term / BOT)"
    return "End of term"


def report_comment_map(student_id, report_type=None):
    stage = report_stage_for_report_type(report_type)
    comments = {"Class teacher": "", "Head teacher": ""}
    for comment in all_report_comments():
        if (
            comment["student_id"] == student_id
            and comment["comment_type"] in comments
            and comment.get("report_stage", "End of term") == stage
        ):
            comments[comment["comment_type"]] = comment["comment"]
    return comments


def report_assessment_rows(student):
    rows = []
    for assessment in all_assessments():
        if assessment["class_name"] != student.get("enrolled_class"):
            continue
        result = assessment_result_map(assessment["id"]).get(student["id"], {})
        rows.append(
            {
                "subject": assessment["subject"],
                "type": assessment["assessment_type"],
                "maximum": assessment["maximum"],
                "mark": result.get("mark", ""),
                "aggregate": result.get("aggregate", ""),
                "grade": result.get("grade", ""),
                "remark": result.get("remark", ""),
                "mode": "letter" if is_other_subject_assessment(assessment) else "marks",
            }
        )
    return rows


def student_enrollment_date(student_id, fallback=""):
    for enrollment in all_enrollments():
        if student_id in enrollment.get("student_ids", []):
            return enrollment["date"]
    return fallback


def main_subjects_for_class(class_name):
    """Marks-graded subjects (B.O.T./Mid/E.O.T.) for a class — the 'compulsory' ones.
    Non-compulsory subjects (ICT, French, Music, etc.) are graded via letter grade
    in the 'Other subjects' section instead. Toggle a subject's compulsory flag in
    Academics > Subjects to move it between the two."""
    return [s["name"] for s in all_subjects() if s["class_name"] == class_name and s.get("is_compulsory")]

def marksheet_subjects_for_class(class_name):
    """Subjects shown on the class-analysis marksheet, in the same marks/aggregate
    layout as the supplied P.5.B example. Compulsory subjects are the numeric
    marks subjects; if a class has not flagged any subjects as compulsory yet,
    fall back to all configured subjects so the sheet is never empty."""
    subjects = [s for s in all_subjects() if s["class_name"] == class_name]
    compulsory = [s for s in subjects if s.get("is_compulsory")]
    return compulsory or subjects


def marksheet_subject_code(subject_name):
    """Short subject heading used by the supplied class-analysis template."""
    normalized = re.sub(r"[^a-z0-9]+", " ", (subject_name or "").lower()).strip()
    known = {
        "english": "ENG",
        "mathematics": "MTC",
        "math": "MTC",
        "science": "SCI",
        "social studies": "SST",
        "social studies and religion": "SST",
        "religious education": "RE",
        "religious education christian": "CRE",
        "religious education islamic": "IRE",
        "literacy": "LIT",
        "local language": "LUG",
        "luganda": "LUG",
        "information communication technology": "ICT",
        "information technology": "ICT",
    }
    if normalized in known:
        return known[normalized]
    words = normalized.split()
    if not words:
        return "SUB"
    if len(words) == 1:
        return words[0][:4].upper()
    return "".join(word[0] for word in words[:3]).upper()


def marksheet_division(total_aggregate):
    try:
        total = int(total_aggregate)
    except (TypeError, ValueError):
        return ""
    if total <= 12:
        return "I"
    if total <= 23:
        return "II"
    if total <= 29:
        return "III"
    if total <= 33:
        return "IV"
    return "U"


def marksheet_data_for_class(class_name, sheet_type):
    """Return all entered numeric assessment data for one class and period.

    The period values map directly to the assessment types used by Grades:
    B.O.T., Mid, E.O.T Internal and E.O.T External.
    """
    type_map = {
        "bot": "B.O.T.",
        "mid": "Mid",
        "internal": "E.O.T Internal",
        "external": "E.O.T External",
    }
    assessment_type = type_map.get(sheet_type)
    if not assessment_type:
        return None

    subjects = marksheet_subjects_for_class(class_name)
    subject_ids = {s["id"] for s in subjects}
    assessments = [
        a for a in Assessment.query.join(Subject, Assessment.subject_id == Subject.id)
        .filter(Subject.class_id == AcademicClass.query.filter_by(name=class_name).first().id,
                Assessment.assessment_type == assessment_type)
        .order_by(Assessment.date.asc(), Assessment.id.asc())
        .all()
        if a.subject_id in subject_ids
    ]

    # If a subject has more than one assessment of the same period, use the
    # most recently entered assessment, matching the Grades data users see last.
    latest_by_subject = {}
    for assessment in assessments:
        latest_by_subject[assessment.subject_id] = assessment

    result_maps = {
        assessment.id: {
            r.student_id: {
                "mark": r.mark,
                "aggregate": r.aggregate or aggregate_from_mark(r.mark),
            }
            for r in AssessmentResult.query.filter_by(assessment_id=assessment.id).all()
        }
        for assessment in latest_by_subject.values()
    }

    students = get_class_students(class_name)
    rows = []
    division_counts = {"I": 0, "II": 0, "III": 0, "IV": 0, "U": 0, "X": 0}

    for student in students:
        cells = []
        total_mark = 0
        total_aggregate = 0
        mark_count = 0
        aggregate_count = 0

        for subject in subjects:
            assessment = latest_by_subject.get(subject["id"])
            result = result_maps.get(assessment.id, {}).get(student["id"], {}) if assessment else {}
            mark = result.get("mark", "")
            aggregate = result.get("aggregate", "")
            cells.append({
                "subject": subject["name"],
                "code": marksheet_subject_code(subject["name"]),
                "mark": mark,
                "aggregate": aggregate,
            })
            try:
                total_mark += int(mark)
                mark_count += 1
            except (TypeError, ValueError):
                pass
            try:
                total_aggregate += int(aggregate)
                aggregate_count += 1
            except (TypeError, ValueError):
                pass

        division = marksheet_division(total_aggregate) if aggregate_count else ""
        if division:
            division_counts[division] = division_counts.get(division, 0) + 1

        average_mark = (total_mark / mark_count) if mark_count else None

        rows.append({
            "name": student["name"],
            "cells": cells,
            "total_mark": total_mark if mark_count else "",
            "total_aggregate": total_aggregate if aggregate_count else "",
            "division": division,
            "_average_mark": average_mark,
        })

    # Highest average on top; students with no marks entered sink to the bottom.
    rows.sort(key=lambda r: (r["_average_mark"] is None, -(r["_average_mark"] or 0)))
    for index, row in enumerate(rows, 1):
        row["sn"] = index
        del row["_average_mark"]

    return {
        "class_name": class_name,
        "sheet_type": sheet_type,
        "sheet_label": {
            "bot": "B.O.T.",
            "mid": "MID TERM",
            "internal": "END TERM INTERNAL",
            "external": "END TERM EXTERNAL",
        }[sheet_type],
        "subjects": [{"name": s["name"], "code": marksheet_subject_code(s["name"])} for s in subjects],
        "students": rows,
        "division_counts": division_counts,
        "school_name": get_school().name if get_school() else "",
        "term": get_current_term().name if get_current_term() else "",
    }


def report_students_payload(report):
    students = [s for s in all_students() if s["id"] in report.get("generated_student_ids", [])]
    result = []
    for student in students:
        class_name = student.get("enrolled_class") or report["class_name"]
        class_record = next((c for c in all_academic_classes() if c["name"] == class_name), None)
        academic_class = AcademicClass.query.filter_by(name=class_name).first()
        class_teacher_staff = academic_class.class_teacher if academic_class else None
        result.append(
            {
                "id": student["id"],
                "name": student["name"],
                "registration_number": student["registration_number"],
                "date_of_birth": student.get("date_of_birth", ""),
                "lin": student.get("lin", ""),
                "class_name": class_name,
                "class_teacher": class_record["teacher"] if class_record else "",
                "class_teacher_signature_url": staff_signature_url(class_teacher_staff),
                "enrollment_date": student_enrollment_date(student["id"], student.get("created_on", "")),
                "level": class_level(class_name),
                "main_subjects": main_subjects_for_class(class_name),
                "comments": report_comment_map(student["id"], report.get("report_type")),
                "assessments": report_assessment_rows(student),
            }
        )
    return result


def attendance_summary_for_class(class_name, on_date=None):
    """Total/absent/present + absentee names for one class's Attendance report row.

    Present is never tallied separately — it's always Total - Absent, so it
    can't drift out of sync with the roster. Looks up the Class register for
    `on_date` (the report's generation date); if none was taken that exact
    day, falls back to the most recent Class register for that class so the
    report still shows something useful instead of all zeros.
    """
    total = Student.query.filter_by(current_class_name=class_name).count()
    absent_names = []

    class_record = AcademicClass.query.filter_by(name=class_name).first()
    if class_record:
        query = AttendanceRecord.query.filter_by(attendance_type="Class", class_id=class_record.id)
        record = query.filter_by(date=on_date).first() if on_date else None
        if not record:
            record = query.order_by(AttendanceRecord.date.desc()).first()
        if record:
            for mark in AttendanceMark.query.filter_by(attendance_record_id=record.id).all():
                if mark.status == "Absent" and mark.student:
                    absent_names.append(mark.student.name)

    absent = len(absent_names)
    present = max(total - absent, 0)
    return {
        "class_name": class_name,
        "total": total,
        "absent": absent,
        "present": present,
        "absent_names": sorted(absent_names),
    }


def attendance_report_payload(report, all_reports):
    """Build an attendance report for one class or one generated scope."""
    scope = report.get("attendance_scope", "")
    if scope in ("All classes", "Lower primary", "Upper primary"):
        class_names = report_classes_for_scope(scope)
    else:
        siblings = [
            r for r in all_reports
            if r["report_type"] == report["report_type"] and r["created_at"] == report["created_at"]
        ]
        class_names = [r["class_name"] for r in siblings]

    on_date = None
    try:
        on_date = datetime.strptime(report["created_at"], "%d-%m-%Y %H:%M").date()
    except (ValueError, TypeError):
        on_date = None

    classes_payload = [attendance_summary_for_class(name, on_date) for name in class_names]
    whole_school = {
        "total": sum(c["total"] for c in classes_payload),
        "absent": sum(c["absent"] for c in classes_payload),
        "present": sum(c["present"] for c in classes_payload),
    }
    return {
        "date": report["created_at"],
        "classes": classes_payload,
        "whole_school": whole_school,
    }


def report_records(records):
    output = []
    for report in records:
        attendance_scope = ""
        if report["report_type"] == "Attendance report":
            attendance_scope = report.get("attendance_scope", "")
            report = {**report, "attendance_scope": attendance_scope, "status": report.get("status", "")}
            summary = attendance_report_payload(report, records)
            output.append(
                {
                    **report,
                    "class_name": attendance_scope or report.get("class_name", ""),
                    "generated_count": summary["whole_school"]["total"],
                    "students": [],
                    "attendance_summary": summary,
                }
            )
        else:
            students = report_students_payload(report)
            output.append(
                {
                    **report,
                    "generated_count": len(students),
                    "students": students,
                }
            )
    return output


def completed_assessment_subjects(class_name):
    complete = []
    for record in assessment_records():
        if record["class_name"] == class_name and record["total_students"] and record["recorded_count"] == record["total_students"]:
            complete.append(record["subject"])
    return complete


def events_redirect():
    return url_for("events")


def events_json_or_redirect(message):
    flash(message, "success")
    redirect_url = events_redirect()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


def get_current_term(today=None):
    """Return the school-wide active term, or the term whose date range
    contains today if none is explicitly marked active yet."""
    active_term = Term.query.filter_by(is_active=True).first()
    if active_term:
        return active_term

    today = today or date.today()
    for term in Term.query.order_by(Term.start_date).all():
        if term.start_date <= today <= term.end_date:
            return term
    return None


def term_options():
    terms = Term.query.order_by(Term.start_date).all()
    if terms:
        return terms
    return [
        {"id": term["id"], "name": term["name"], "start_date": term["start"], "end_date": term["end"]}
        for term in TERMS
    ]


TERM_LABEL_RE = re.compile(r"Term\s+(\d+),\s*(\d{4})")


def term_year_and_number(term_name):
    """Pull the year + term number out of a 'Term N, YYYY' name.

    Terms are only stored as name/start_date/end_date — no separate year or
    term_number columns — so the term-dates picker (a year grid with 3 term
    slots) derives both from the name instead of needing a migration.
    """
    match = TERM_LABEL_RE.match(term_name or "")
    if not match:
        return None, None
    return int(match.group(2)), int(match.group(1))


def term_picker_payload():
    """Every term, shaped for the term-dates year grid (see term-picker.js)."""
    payload = []
    for term in Term.query.order_by(Term.start_date).all():
        year, number = term_year_and_number(term.name)
        if year is None:
            continue
        payload.append(
            {
                "id": term.id,
                "name": term.name,
                "year": year,
                "term_number": number,
                "start": term.start_date.isoformat(),
                "end": term.end_date.isoformat(),
            }
        )
    return payload


def nav_items_for_role(role):
    """Teacher accounts don't see nav items that lead to admin-only areas —
    Academics (class/subject/term setup) and Timetable (whole-school rota
    building) are both entirely gated by ADMIN_ONLY_ENDPOINTS."""
    if role == "admin":
        return NAV_ITEMS
    hidden = {"academics", "timetable"}
    return [item for item in NAV_ITEMS if item["endpoint"] not in hidden]


def base_context(active_endpoint):
    account = current_staff_account()
    if account:
        user = {
            "id": account.id,
            "name": account.name,
            "initials": initials_for(account.name),
            "role": account.role,
            "theme": account.theme,
            "photo_url": staff_photo_url(account),
        }
    else:
        user = {"id": None, "name": "", "initials": "?", "role": "teacher", "theme": "light", "photo_url": ""}

    school = get_school()
    current_term = get_current_term()
    title_map = {
        "home": "Dashboard", "profiles": "Students & Staff", "academics": "Academics",
        "grades": "Grades", "attendance": "Attendance", "reports": "Reports",
        "timetable": "Timetable", "events": "Events", "settings_school": "Settings",
        "profile": "Profile", "change_password": "Change Password",
    }
    logo_url = school_logo_url(school)
    year_label = ""
    if current_term:
        year = current_term.start_date.year
        year_label = f"{year}–{year + 1}"

    return {
        "school_name": school.name if school else SCHOOL_NAME,
        "school_logo_url": logo_url,
        "nav_items": nav_items_for_role(user["role"]),
        "active_endpoint": active_endpoint,
        "page_title": title_map.get(active_endpoint, "School Management"),
        "current_date_label": date.today().strftime("%A, %d %B %Y"),
        "academic_year_label": year_label,
        "current_term": current_term,
        "terms": term_options(),
        "all_terms_json": term_picker_payload(),
        "calendar_events": calendar_event_payload(),
        "user": user,
    }


# --- Timetable data model ---
#
# Timetable boards/periods/entries/legend, and the duty & gate rotas, are now
# backed by the database (TimetableBoard, TimetablePeriod, TimetableEntry,
# TimetableLegendEntry, DutyShift, DutyEntry, GatePickupWeek, GatePickupEntry
# in models.py). The lists below are only used once, by seed_initial_database(),
# to populate the first rows — everything at runtime reads/writes through the
# database via the helper functions further down (find_timetable(),
# timetable_periods(), timetable_grid(), duty_rota_map(), gate_weeks_context(), etc).
#
# One "board" (TIMETABLES) covers a group of classes for a term — e.g. "Upper Primary".
# PERIODS are the time columns, shared by every day on that board. A period is either a
# normal teaching slot, or a "special" slot (Assembly/Break/Lunch) that spans the row
# instead of holding a per-class subject+teacher.
# ENTRIES holds what's actually taught: entries[board_id][day][period_id][class_name] = {subject, teacher}
# LEGEND holds the teacher-code -> full-name key shown at the bottom of the printed grid.

TIMETABLE_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

TIMETABLES = [
    {"id": 1, "name": "Upper Primary - Term Two 2026", "classes": ["Primary 5", "Primary 6", "Primary 7"], "created_on": "09-07-2026", "layout": "class_rows"},
    {"id": 2, "name": "Lower Primary - Term Two 2026", "classes": ["Primary 1", "Primary 2", "Primary 3"], "created_on": "09-07-2026", "layout": "period_rows"},
]

TIMETABLE_PERIODS = {
    1: [
        {"id": 1, "start": "7:30", "end": "8:30", "label": "Assembly", "is_special": True},
        {"id": 2, "start": "8:30", "end": "9:30", "label": "", "is_special": False},
        {"id": 3, "start": "9:30", "end": "10:30", "label": "", "is_special": False},
        {"id": 4, "start": "10:30", "end": "11:00", "label": "Break", "is_special": True},
        {"id": 5, "start": "11:00", "end": "12:00", "label": "", "is_special": False},
        {"id": 6, "start": "12:00", "end": "13:00", "label": "", "is_special": False},
        {"id": 7, "start": "13:00", "end": "14:00", "label": "Lunch", "is_special": True},
        {"id": 8, "start": "14:00", "end": "15:00", "label": "", "is_special": False},
        {"id": 9, "start": "15:00", "end": "16:00", "label": "", "is_special": False},
    ],
    2: [
        {"id": 1, "start": "7:30", "end": "8:30", "label": "Assembly", "is_special": True},
        {"id": 2, "start": "8:30", "end": "9:30", "label": "", "is_special": False},
        {"id": 3, "start": "9:30", "end": "10:30", "label": "", "is_special": False},
        {"id": 4, "start": "10:30", "end": "11:00", "label": "Break", "is_special": True},
        {"id": 5, "start": "11:00", "end": "12:00", "label": "", "is_special": False},
        {"id": 6, "start": "12:00", "end": "13:00", "label": "", "is_special": False},
        {"id": 7, "start": "13:00", "end": "14:00", "label": "Lunch", "is_special": True},
        {"id": 8, "start": "14:00", "end": "15:00", "label": "", "is_special": False},
    ],
}

# Teacher is now picked from Staff (see timetable_teachers()) rather than typed
# in freehand, so entries store the teacher's actual name — no more initials
# that only mean something via a separately-maintained key.
TIMETABLE_ENTRIES = {
    1: {
        "Monday": {
            2: {
                "Primary 5": {"subject": "MTC", "teacher": "Raymond Gakwaya"},
                "Primary 6": {"subject": "SCI", "teacher": "Eddy Sheja"},
                "Primary 7": {"subject": "ENG", "teacher": "Dushime Alipe"},
            },
        },
    }
}

TIMETABLE_LEGEND = {
    1: [
        {"code": "RG", "name": "Raymond Gakwaya"},
        {"code": "ES", "name": "Eddy Sheja"},
        {"code": "DA", "name": "Dushime Alipe"},
    ]
}


def timetable_teachers():
    """Staff eligible to be picked as a timetable teacher — keeps the cell
    editor's teacher field tied to real Staff records instead of freeform
    initials that could typo or go stale."""
    return Staff.query.filter_by(role="teacher").order_by(Staff.name).all()


# --- Staff timetables: daily duty rota & gate/pickup rota ---
#
# Separate from the class timetable boards above — these rotas aren't about
# subjects and periods, they're about which staff are covering a fixed duty
# on a given day (or week, for the gate rota).

DUTY_SHIFTS = [
    {"id": "morning", "label": "Morning", "time": "7:30am – 7:55am"},
    {"id": "home_lower", "label": "Home time (Lower)", "time": "4:00pm – 5:00pm"},
    {"id": "home_upper", "label": "Home time (Upper)", "time": "5:00pm – 6:00pm"},
]

# One list of staff names per day per shift — transcribed from the Daily Duty
# Rota (National Section, Term 2 2026).
DUTY_ROTA = {
    "Monday": {"morning": ["Tr. Innocent"], "home_lower": ["Tr. Josephine Sr"], "home_upper": ["Tr. Emma", "Tr. Patrick", "Tr. Rebecca"]},
    "Tuesday": {"morning": ["Tr. Joel K"], "home_lower": ["Tr. Jane"], "home_upper": ["Tr. Carol", "Tr. Carrick", "Tr. Susan"]},
    "Wednesday": {"morning": ["Tr. Rebecca"], "home_lower": ["Tr. Hellen"], "home_upper": ["Tr. Joyce", "Tr. Brian", "Tr. Jackson"]},
    "Thursday": {"morning": ["Tr. Francis"], "home_lower": ["Tr. Mikado"], "home_upper": ["Tr. Marion", "Tr. Obbo", "Tr. Johnson"]},
    "Friday": {"morning": ["Tr. Josephine Sr"], "home_lower": ["Tr. Juliet", "Tr. Josephine Jr"], "home_upper": ["Tr. Jacob", "Tr. Apophia"]},
}

# Weekly gate & last-pick-up-from-6pm rota — transcribed from the uploaded
# schedule (WK1–WK13, 25th May to 21st August 2026). One staff name covers
# the whole week's gate duty for each weekday. "Eid Day" is just plain text in a
# cell like any other entry — there's no special holiday styling applied to it.
GATE_PICKUP_WEEKS = [
    {"id": 1, "label": "WK1", "date_range": "25th – 29th May", "days": {"Monday": "Joel", "Tuesday": "Elisa", "Wednesday": "Eid Day", "Thursday": "Josephine Jr", "Friday": "Susan"}},
    {"id": 2, "label": "WK2", "date_range": "1st – 6th June", "days": {"Monday": "Jacob", "Tuesday": "Josephine Sr", "Wednesday": "Apophia", "Thursday": "Marion", "Friday": "Obbo"}},
    {"id": 3, "label": "WK3", "date_range": "8th – 12th June", "days": {"Monday": "Emma", "Tuesday": "Brian", "Wednesday": "Rebecca", "Thursday": "Juliet", "Friday": "Carrick"}},
    {"id": 4, "label": "WK4", "date_range": "15th – 19th June", "days": {"Monday": "Patrick", "Tuesday": "Carol", "Wednesday": "Johnson", "Thursday": "Mitana", "Friday": "Hellen"}},
    {"id": 5, "label": "WK5", "date_range": "22nd – 26th June", "days": {"Monday": "Joyce", "Tuesday": "Jane", "Wednesday": "Josephine Jr", "Thursday": "Susan", "Friday": "Josephine Sr"}},
    {"id": 6, "label": "WK6", "date_range": "29th June – 3rd July", "days": {"Monday": "Elisa", "Tuesday": "Jacob", "Wednesday": "Apophia", "Thursday": "Marion", "Friday": "Obbo"}},
    {"id": 7, "label": "WK7", "date_range": "6th – 10th July", "days": {"Monday": "Brian", "Tuesday": "Rebecca", "Wednesday": "Juliet", "Thursday": "Joel", "Friday": "Patrick"}},
    {"id": 8, "label": "WK8", "date_range": "13th – 17th July", "days": {"Monday": "Mitana", "Tuesday": "Carol", "Wednesday": "Johnson", "Thursday": "Hellen", "Friday": "Carrick"}},
    {"id": 9, "label": "WK9", "date_range": "20th – 24th July", "days": {"Monday": "Jane", "Tuesday": "Josephine Jr", "Wednesday": "Joyce", "Thursday": "Jackson", "Friday": "Susan"}},
    {"id": 10, "label": "WK10", "date_range": "27th – 31st July", "days": {"Monday": "Emma", "Tuesday": "Elisa", "Wednesday": "Jacob", "Thursday": "Apophia", "Friday": "Marion"}},
    {"id": 11, "label": "WK11", "date_range": "3rd – 7th August", "days": {"Monday": "Obbo", "Tuesday": "Brian", "Wednesday": "Juliet", "Thursday": "Rebecca", "Friday": "Joel"}},
    {"id": 12, "label": "WK12", "date_range": "10th – 14th August", "days": {"Monday": "Johnson", "Tuesday": "Patrick", "Wednesday": "Carol", "Thursday": "Mitana", "Friday": "Hellen"}},
    {"id": 13, "label": "WK13", "date_range": "17th – 21st August", "days": {"Monday": "Carrick", "Tuesday": "Jane", "Wednesday": "Josephine Jr", "Thursday": "Joyce", "Friday": "Jackson"}},
]


def set_duty_entry(day, shift_id, names):
    """Replace the whole list of staff covering one day/shift in one go —
    matches the form, which submits a comma-separated names field."""
    DutyEntry.query.filter_by(day=day, shift_id=shift_id).delete()
    for name in names:
        db.session.add(DutyEntry(day=day, shift_id=shift_id, staff_name=name))
    db.session.commit()


def duty_rota_map():
    """Builds day -> shift_id -> [staff_name, ...], the shape the duty tab
    template expects (duty_rota.get(day, {}).get(shift.id, []))."""
    rota = {}
    for entry in DutyEntry.query.order_by(DutyEntry.id).all():
        rota.setdefault(entry.day, {}).setdefault(entry.shift_id, []).append(entry.staff_name)
    return rota


def set_gate_entry(week_id, day, name):
    entry = GatePickupEntry.query.filter_by(week_id=week_id, day=day).first()
    if entry:
        entry.staff_name = name
    else:
        db.session.add(GatePickupEntry(week_id=week_id, day=day, staff_name=name))
    db.session.commit()


def gate_week_context(week):
    """A GatePickupWeek plus its per-day staff names, in the {'days': {...}}
    shape the gate tab template expects (week.days.get(day, ''))."""
    days = {entry.day: entry.staff_name for entry in week.entries}
    return {"id": week.id, "label": week.label, "date_range": week.date_range, "days": days}


def gate_weeks_context():
    return [gate_week_context(week) for week in GatePickupWeek.query.order_by(GatePickupWeek.id).all()]


def find_timetable(board_id):
    return TimetableBoard.query.get(board_id)


def timetable_periods(board_id):
    return TimetablePeriod.query.filter_by(board_id=board_id).order_by(TimetablePeriod.sort_order).all()


def timetable_entry(board_id, day, period_id, class_name):
    academic_class = AcademicClass.query.filter_by(name=class_name).first()
    if not academic_class:
        return {"subject": "", "teacher": ""}
    entry = TimetableEntry.query.filter_by(
        board_id=board_id, day=day, period_id=period_id, class_id=academic_class.id
    ).first()
    if not entry:
        return {"subject": "", "teacher": ""}
    return {"subject": entry.subject, "teacher": entry.teacher.name if entry.teacher else ""}


def timetable_period_is_special_on_day(period, day):
    if not period.is_special:
        return False
    if (period.label or "").strip().lower() == "assembly":
        return day == "Monday"
    return True


def set_timetable_entry(board_id, day, period_id, class_name, subject, teacher):
    academic_class = AcademicClass.query.filter_by(name=class_name).first()
    if not academic_class:
        return
    entry = TimetableEntry.query.filter_by(
        board_id=board_id, day=day, period_id=period_id, class_id=academic_class.id
    ).first()
    if subject or teacher:
        teacher_row = Staff.query.filter_by(name=teacher).first() if teacher else None
        if entry:
            entry.subject = subject
            entry.teacher = teacher_row
        else:
            db.session.add(
                TimetableEntry(
                    board_id=board_id,
                    day=day,
                    period_id=period_id,
                    class_id=academic_class.id,
                    subject=subject,
                    teacher=teacher_row,
                )
            )
    elif entry:
        db.session.delete(entry)
    db.session.commit()


def timetable_grid(board_id):
    """Builds a day -> class-rows -> period-cells grid ready for rendering.

    Each day section has one row per class; period columns run across. Special
    periods (Assembly/Break/Lunch) render once per day as a single cell that spans
    down every class row for that day (rowspan), rather than repeating per class."""
    board = find_timetable(board_id)
    if not board:
        return []
    periods = timetable_periods(board_id)
    classes = board.classes
    grid = []
    for day in TIMETABLE_DAYS:
        class_rows = []
        for row_index, class_name in enumerate(classes):
            cells = []
            for period in periods:
                if timetable_period_is_special_on_day(period, day):
                    if row_index == 0:
                        cells.append({"special": True, "skip": False, "label": period.label, "rowspan": len(classes)})
                    else:
                        cells.append({"special": True, "skip": True})
                else:
                    entry = timetable_entry(board_id, day, period.id, class_name)
                    cells.append(
                        {
                            "special": False,
                            "skip": False,
                            "period_id": period.id,
                            "subject": entry["subject"],
                            "teacher": entry["teacher"],
                        }
                    )
            class_rows.append({"class_name": class_name, "cells": cells})
        grid.append({"day": day, "class_rows": class_rows})
    return grid


def timetable_grid_by_period(board_id):
    """Builds a day -> period-rows -> class-cells grid: time runs down the rows,
    classes run across the columns. Used for boards like Lower Primary where the
    time slots (including Break/Lunch) are shared by every class column at once.

    Special periods (Assembly/Break/Lunch) render as a single cell spanning every
    class column for that row, instead of one cell per class."""
    board = find_timetable(board_id)
    if not board:
        return []
    periods = timetable_periods(board_id)
    classes = board.classes
    grid = []
    for day in TIMETABLE_DAYS:
        period_rows = []
        for period in periods:
            if timetable_period_is_special_on_day(period, day):
                period_rows.append({"period": period, "special": True, "label": period.label})
            else:
                cells = []
                for class_name in classes:
                    entry = timetable_entry(board_id, day, period.id, class_name)
                    cells.append(
                        {
                            "class_name": class_name,
                            "period_id": period.id,
                            "subject": entry["subject"],
                            "teacher": entry["teacher"],
                        }
                    )
                period_rows.append({"period": period, "special": False, "cells": cells})
        grid.append({"day": day, "period_rows": period_rows})
    return grid


def build_timetable_grid(board):
    """Picks the right grid shape for a board's layout ('class_rows' is the
    default/original orientation; 'period_rows' is used by boards like Lower
    Primary where time should run down the rows instead of across the columns)."""
    if board.layout == "period_rows":
        return timetable_grid_by_period(board.id)
    return timetable_grid(board.id)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("staff_id"):
        return redirect(url_for("home"))

    errors = {}
    email = ""
    next_url = request.args.get("next") or request.form.get("next") or ""

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        account = Staff.query.filter_by(email=email).first() if email else None
        if not account or not account.password_hash or not check_password_hash(account.password_hash, password):
            errors["form"] = "That email and password don't match an account."
        elif not account.is_active:
            errors["form"] = "This account has been deactivated. Contact an admin."

        if not errors:
            session.clear()
            session["staff_id"] = account.id
            account.has_logged_in = True
            db.session.commit()
            flash(f"Welcome back, {account.name.split(' ')[0]}.", "success")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            if account.must_change_password:
                return redirect(url_for("change_password"))
            return redirect(url_for("home"))

    school = get_school()
    return render_template(
        "login.html",
        school_name=school.name if school else SCHOOL_NAME,
        school_logo_url=school_logo_url(school),
        errors=errors,
        email=email,
        next_url=next_url,
    )


@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    flash("You've been signed out.", "success")
    return redirect(url_for("login"))


@app.route("/account/password", methods=["GET", "POST"])
def change_password():
    account = current_staff_account()
    if account is None:
        abort(404)

    forced = account.must_change_password
    errors = {}

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not forced and not check_password_hash(account.password_hash, current_password):
            errors["current_password"] = "That's not your current password."
        if len(new_password) < 8:
            errors["new_password"] = "Use at least 8 characters."
        elif new_password != confirm_password:
            errors["confirm_password"] = "Passwords don't match."

        if not errors:
            set_staff_password(account, new_password)
            account.must_change_password = False
            db.session.commit()
            flash("Your password was updated.", "success")
            return redirect(url_for("profile"))

    school = get_school()
    return render_template(
        "change_password.html",
        school_name=school.name if school else SCHOOL_NAME,
        errors=errors,
        forced=forced,
    )


def home_attendance_trend(days=14):
    """Return real daily class-attendance percentages for the dashboard.

    Each day's percentage is present marks / total students currently
    enrolled in the school (whole-school denominator), matching the
    "Attendance Rate" KPI card. Days with no register recorded stay None
    rather than being filled with fabricated values.
    """
    today = date.today()
    start = today - timedelta(days=days - 1)
    total_students = Student.query.filter(
        Student.current_class_name.isnot(None), Student.current_class_name != ""
    ).count()
    records = AttendanceRecord.query.filter(
        AttendanceRecord.date >= start,
        AttendanceRecord.date <= today,
        AttendanceRecord.attendance_type == "Class",
    ).order_by(AttendanceRecord.date.asc(), AttendanceRecord.id.asc()).all()

    present_by_day = {}
    for record in records:
        marks = AttendanceMark.query.filter_by(attendance_record_id=record.id).all()
        present = sum(1 for mark in marks if mark.status == "Present")
        present_by_day[record.date] = present_by_day.get(record.date, 0) + present

    points = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        if day in present_by_day and total_students:
            value = round(present_by_day[day] / total_students * 100)
        else:
            value = None
        points.append({"label": str(day.day), "value": value})
    return points


def home_recent_activities(limit=5):
    """Build the dashboard activity feed from real database activity."""
    activities = []
    for student in Student.query.order_by(Student.created_at.desc()).limit(limit).all():
        activities.append({
            "when": student.created_at,
            "icon": "ti-user-plus",
            "title": "Student added",
            "subtitle": f"{student.name} · {student.current_class_name or 'Not enrolled'}",
        })
    for record in AttendanceRecord.query.order_by(AttendanceRecord.created_at.desc()).limit(limit).all():
        activities.append({
            "when": record.created_at,
            "icon": "ti-calendar-check",
            "title": "Attendance marked",
            "subtitle": record.entity or "Class attendance",
        })
    for report in ReportBatch.query.order_by(ReportBatch.created_at.desc()).limit(limit).all():
        # ReportBatch stores its class through the academic_class relationship.
        # Group attendance reports additionally carry their display scope in
        # report_scope (e.g. All classes / Lower primary / Upper primary).
        display_scope = report.report_scope or (
            report.academic_class.name if report.academic_class else "Unknown class"
        )
        activities.append({
            "when": report.created_at,
            "icon": "ti-file-analytics",
            "title": "Report generated" if report.status == "Generated" else "Report pending",
            "subtitle": f"{report.report_type} · {display_scope}",
        })
    activities.sort(key=lambda item: item["when"], reverse=True)

    now = datetime.utcnow()
    output = []
    for item in activities[:limit]:
        delta = max(0, int((now - item["when"]).total_seconds()))
        if delta < 60:
            label = "Just now"
        elif delta < 3600:
            label = f"{delta // 60}m ago"
        elif delta < 86400:
            label = f"{delta // 3600}h ago"
        else:
            label = item["when"].strftime("%d %b")
        output.append({**item, "time": label})
    return output


@app.route("/global-search")
def global_search():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({"results": []})
    needle = f"%{query}%"
    classes = AcademicClass.query.filter(AcademicClass.name.ilike(needle)).order_by(AcademicClass.name).limit(6).all()
    students = Student.query.filter(Student.name.ilike(needle)).order_by(Student.name).limit(6).all()
    results = [
        {"type": "class", "label": c.name, "subtitle": "Class report", "url": url_for("reports", class_id=c.id)}
        for c in classes
    ]
    results += [
        {"type": "student", "label": s.name, "subtitle": f"{s.current_class_name or 'Not enrolled'} · Student profile", "url": url_for("profiles", tab="students", q=s.name)}
        for s in students
    ]
    return jsonify({"results": results[:10]})


@app.route("/health")
def health():
    """Lightweight Render health check endpoint."""
    return {"status": "ok"}, 200


@app.route("/")
def home():
    total_students = Student.query.count()
    # Classify by the grade digit embedded in the class name (e.g. "Primary 1a",
    # "p.2a", "P3", "Primary 3" all resolve to grade 1/2/3) instead of matching
    # exact strings, so section letters and formatting differences don't drop
    # students out of every bucket.
    lower_students = 0
    upper_students = 0
    unassigned_students = 0
    for (class_name,) in db.session.query(Student.current_class_name).all():
        if not class_name or not class_name.strip():
            unassigned_students += 1
            continue
        match = re.search(r"(\d+)", class_name)
        grade = int(match.group(1)) if match else None
        if grade is not None and 1 <= grade <= 3:
            lower_students += 1
        elif grade is not None and 4 <= grade <= 7:
            upper_students += 1
        else:
            unassigned_students += 1

    attendance_value = todays_attendance_percentage()
    attendance_trend = home_attendance_trend()
    stats = [
        {"label": "Total Students", "value": str(total_students), "note": "All students in the system"},
        {"label": "Teachers", "value": str(Staff.query.count()), "note": "Active staff"},
        {"label": "Attendance Rate", "value": f"{attendance_value}%", "note": "Today"},
        {"label": "Classes", "value": str(AcademicClass.query.count()), "note": "Academic classes"},
    ]
    context = base_context("home")
    context.update({
        "stats": stats,
        "total_students": total_students,
        "lower_students": lower_students,
        "upper_students": upper_students,
        "unassigned_students": unassigned_students,
        "lower_percent": (lower_students / total_students * 100) if total_students else 0,
        "upper_percent": (upper_students / total_students * 100) if total_students else 0,
        "unassigned_percent": (unassigned_students / total_students * 100) if total_students else 0,
        "attendance_trend": attendance_trend,
        "recent_activities": home_recent_activities(),
        "events": [
            {"icon": "ti-calendar", "title": event["name"], "date_label": event["date_label"]}
            for event in event_records()
        ],
    })
    return render_template("home.html", **context)


@app.route("/terms/switch", methods=["POST"])
def switch_term():
    try:
        term_id = int(request.form.get("term_id", ""))
    except ValueError:
        term_id = None

    term = db.session.get(Term, term_id) if term_id else None
    if not term:
        flash("Choose a valid term before switching.", "error")
        return redirect(request.referrer or url_for("home"))

    Term.query.filter(Term.id != term.id).update({"is_active": False})
    term.is_active = True
    db.session.commit()
    flash(f"Switched to {term.name}.", "success")
    return redirect(request.form.get("next") or request.referrer or url_for("home"))


@app.route("/terms/dates", methods=["POST"])
def save_term_dates():
    redirect_url = request.form.get("next") or request.referrer or url_for("home")

    try:
        year = int(request.form.get("year", ""))
        term_number = int(request.form.get("term_number", ""))
    except ValueError:
        flash("Something went wrong identifying that term.", "error")
        return redirect(redirect_url)

    start_raw = request.form.get("start_date", "").strip()
    end_raw = request.form.get("end_date", "").strip()
    if term_number not in (1, 2, 3) or not start_raw or not end_raw:
        flash("Choose a start and end date before saving.", "error")
        return redirect(redirect_url)

    start_date_value = parse_seed_date(start_raw)
    end_date_value = parse_seed_date(end_raw)
    if start_date_value >= end_date_value:
        flash("The end date must be after the start date.", "error")
        return redirect(redirect_url)

    name = f"Term {term_number}, {year}"
    term = Term.query.filter_by(name=name).first()
    if term:
        term.start_date = start_date_value
        term.end_date = end_date_value
    else:
        db.session.add(Term(name=name, start_date=start_date_value, end_date=end_date_value, is_active=False))
    db.session.commit()

    flash(f"{name} dates were saved.", "success")
    return redirect(redirect_url)


# --- Settings ---
#
# Everything here is gated to admin accounts by ADMIN_ONLY_ENDPOINTS /
# enforce_login_and_access. Four tabs, one shared context builder.

def settings_context(active_tab):
    context = base_context("settings")
    context.update({"active_tab": active_tab})
    return context


@app.route("/settings")
def settings_index():
    return redirect(url_for("settings_school"))


@app.route("/settings/school", methods=["GET"])
def settings_school():
    school = get_school()
    context = settings_context("school")
    context.update({"school": school})
    return render_template("settings.html", **context)


@app.route("/settings/school", methods=["POST"])
def save_school_settings():
    school = get_school()
    if school is None:
        school = School(name="", type="", address="", phone="", email="", website="", reg_no="", logo_path="")
        db.session.add(school)

    school.name = request.form.get("name", "").strip() or school.name or SCHOOL_NAME
    school.type = request.form.get("type", "").strip()
    school.address = request.form.get("address", "").strip()
    school.phone = request.form.get("phone", "").strip()
    school.email = request.form.get("email", "").strip()
    school.website = request.form.get("website", "").strip()
    school.reg_no = request.form.get("reg_no", "").strip()

    logo_file = request.files.get("logo")
    if logo_file and logo_file.filename:
        if not allowed_photo(logo_file.filename):
            flash("Logo must be a PNG, JPG, GIF, or WEBP image.", "error")
            return redirect(url_for("settings_school"))
        logo_data, logo_mimetype = read_uploaded_image(logo_file)
        if logo_data:
            school.logo_data = logo_data
            school.logo_mimetype = logo_mimetype

    db.session.commit()
    flash("School profile was updated.", "success")
    return redirect(url_for("settings_school"))


@app.route("/settings/users", methods=["GET"])
def settings_users():
    accounts = [staff_record(member) for member in Staff.query.order_by(Staff.name).all()]
    total_count = len(accounts)
    page_accounts, pagination = paginate(accounts)
    context = settings_context("users")
    context.update({"accounts": page_accounts, "pagination": pagination, "total_count": total_count})
    return render_template("settings.html", **context)


@app.route("/settings/users/<int:staff_id>/reset-password", methods=["POST"])
def reset_user_password(staff_id):
    account = db.session.get(Staff, staff_id)
    if account is None:
        abort(404)

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    temp_password = generate_temp_password()
    set_staff_password(account, temp_password, remember_as_temp=True)
    account.must_change_password = True
    db.session.commit()

    if wants_json:
        return jsonify({
            "success": True,
            "name": account.name,
            "email": account.email,
            "temp_password": temp_password,
        })

    flash(
        f"New temporary password for {account.name} ({account.email}): {temp_password}. "
        f"Share it with them directly — they'll set their own password on next sign-in.",
        "success",
    )
    return redirect(url_for("settings_users"))


@app.route("/settings/users/<int:staff_id>/toggle-active", methods=["POST"])
def toggle_user_active(staff_id):
    account = db.session.get(Staff, staff_id)
    if account is None:
        abort(404)

    current_account = current_staff_account()
    if current_account and current_account.id == account.id:
        flash("You can't deactivate your own account.", "error")
        return redirect(url_for("settings_users"))

    account.is_active = not account.is_active
    if not account.is_active:
        session_owner = session.get("staff_id")
        if session_owner == account.id:
            session.clear()
    db.session.commit()

    state = "reactivated" if account.is_active else "deactivated"
    flash(f"{account.name}'s account was {state}.", "success")
    return redirect(url_for("settings_users"))


@app.route("/settings/appearance", methods=["GET"])
def settings_appearance():
    context = settings_context("appearance")
    return render_template("settings.html", **context)


@app.route("/settings/appearance", methods=["POST"])
def save_appearance_settings():
    account = current_staff_account()
    if account is None:
        abort(404)

    theme = request.form.get("theme", "light")
    account.theme = "dark" if theme == "dark" else "light"
    db.session.commit()
    flash("Appearance was updated.", "success")
    return redirect(url_for("settings_appearance"))


@app.route("/settings/backup", methods=["GET"])
def settings_backup():
    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    is_sqlite = db_uri.startswith("sqlite:///")
    context = settings_context("backup")
    context.update({"is_sqlite": is_sqlite})
    return render_template("settings.html", **context)


@app.route("/settings/backup/download")
def download_backup():
    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not db_uri.startswith("sqlite:///"):
        flash("Automatic backup download only works with the built-in SQLite database. Use your database provider's own backup tools (e.g. pg_dump) instead.", "error")
        return redirect(url_for("settings_backup"))

    db_path = os.path.join(app.instance_path, db_uri.replace("sqlite:///", "", 1))
    if not os.path.exists(db_path):
        flash("No database file was found to back up.", "error")
        return redirect(url_for("settings_backup"))

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    download_name = f"school-backup-{timestamp}.db"
    backup_copy_path = os.path.join(BACKUP_DIR, download_name)
    shutil.copyfile(db_path, backup_copy_path)

    return send_file(backup_copy_path, as_attachment=True, download_name=download_name)


@app.route("/settings/backup/restore", methods=["POST"])
def restore_backup():
    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not db_uri.startswith("sqlite:///"):
        flash("Restoring from a file only works with the built-in SQLite database.", "error")
        return redirect(url_for("settings_backup"))

    backup_file = request.files.get("backup_file")
    if not backup_file or not backup_file.filename:
        flash("Choose a .db backup file to restore.", "error")
        return redirect(url_for("settings_backup"))
    if not backup_file.filename.lower().endswith(".db"):
        flash("That doesn't look like a database backup file (expected a .db file).", "error")
        return redirect(url_for("settings_backup"))

    db_path = os.path.join(app.instance_path, db_uri.replace("sqlite:///", "", 1))

    try:
        # Keep a safety copy of what's currently live before overwriting it.
        if os.path.exists(db_path):
            timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            shutil.copyfile(db_path, os.path.join(BACKUP_DIR, f"pre-restore-{timestamp}.db"))

        db.session.remove()
        db.engine.dispose()
        backup_file.save(db_path)
    except OSError as exc:
        flash(f"Restore failed: {exc}", "error")
        return redirect(url_for("settings_backup"))

    session.clear()
    flash("Backup restored. Please sign in again — a server restart is recommended to ensure everything picks up the restored data.", "success")
    return redirect(url_for("login"))


@app.route("/profile")
def profile():
    context = base_context("profile")
    account = current_staff_account()
    if account is None:
        abort(404)

    context.update({"member": staff_record(account)})
    return render_template("profile.html", **context)


@app.route("/profile/edit", methods=["POST"])
def edit_profile():
    account = current_staff_account()
    if account is None:
        abort(404)

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    # Role is intentionally not editable from your own profile — that would let
    # a teacher grant themselves admin access. Roles are set when an account is
    # created and changed only by an admin via Settings > Users / Profiles > Staff.

    errors = {}
    if not name:
        errors["name"] = "Full name is required."
    if not email:
        errors["email"] = "Email is required."
    elif Staff.query.filter(Staff.email == email, Staff.id != account.id).first():
        errors["email"] = "That email is already in use by another staff member."

    if errors:
        if wants_json:
            return jsonify({"success": False, "errors": errors}), 400
        for message in errors.values():
            flash(message, "error")
        return redirect(url_for("profile"))

    photo_file = request.files.get("photo")
    if photo_file and photo_file.filename:
        if not allowed_photo(photo_file.filename):
            message = "Photo must be a PNG, JPG, GIF, or WEBP image."
            if wants_json:
                return jsonify({"success": False, "errors": {"photo": message}}), 400
            flash(message, "error")
            return redirect(url_for("profile"))
        photo_data, photo_mimetype = read_uploaded_image(photo_file)
        if photo_data:
            account.photo_data = photo_data
            account.photo_mimetype = photo_mimetype

    signature_file = request.files.get("signature")
    if signature_file and signature_file.filename:
        if not allowed_photo(signature_file.filename):
            message = "Signature must be a PNG, JPG, GIF, or WEBP image."
            if wants_json:
                return jsonify({"success": False, "errors": {"signature": message}}), 400
            flash(message, "error")
            return redirect(url_for("profile"))
        signature_data, signature_mimetype = read_uploaded_image(signature_file)
        if signature_data:
            account.signature_data = signature_data
            account.signature_mimetype = signature_mimetype

    account.name = name
    account.email = email
    account.phone = phone
    db.session.commit()

    flash("Your profile was updated.", "success")
    redirect_url = url_for("profile")
    if wants_json:
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


# --- Profiles: staff + students ---

@app.route("/profiles/staff/upload-template")
def download_staff_upload_template():
    # Mirrors the "New staff" form fields exactly: name, email, phone, role.
    csv_body = "name,email,phone,role\nNakato Diana,nakato.diana@school.org,+256 700000000,teacher\n"
    return Response(
        csv_body,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=staff-upload-template.csv"},
    )


@app.route("/profiles/students/upload-template")
def download_student_upload_template():
    # Mirrors the "New student" form fields exactly: name, gender, date_of_birth, lin.
    # No registration_number column — that's auto-assigned on save, same as
    # when a student is added one at a time.
    csv_body = "name,gender,date_of_birth,lin\nNabirye Grace,Female,2015-03-12,\n"
    return Response(
        csv_body,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=student-upload-template.csv"},
    )


@app.route("/profiles")
def profiles():
    account = current_staff_account()
    is_admin = bool(account and account.role == "admin")

    tab = request.args.get("tab", "staff" if is_admin else "students")
    if tab == "staff" and not is_admin:
        flash("Your account has limited access and can't open Staff. Ask an admin if you need it.", "error")
        return redirect(url_for("profiles", tab="students"))

    search_query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "")
    sort = request.args.get("sort", "name_asc")
    if sort not in ("name_asc", "name_desc", "created_desc", "created_asc"):
        sort = "name_asc"
    context = base_context("profiles")

    def apply_sort(records):
        if sort == "name_desc":
            records.sort(key=lambda r: r["name"].lower(), reverse=True)
        elif sort == "created_desc":
            records.sort(key=lambda r: parse_created_on(r["created_on"]), reverse=True)
        elif sort == "created_asc":
            records.sort(key=lambda r: parse_created_on(r["created_on"]))
        else:
            records.sort(key=lambda r: r["name"].lower())
        return records

    if tab == "students":
        class_filter = request.args.get("class", "")
        records = [student_record(student) for student in Student.query.all()]

        # Classes offered in the filter dropdown come from the school's whole
        # class list (see get_class_filter_options), not just who's currently
        # registered — this is the pre-wired hook point for Academics > Classes.
        available_classes = get_class_filter_options()

        if class_filter:
            records = [r for r in records if r["class_name"] == class_filter]
        if status_filter:
            records = [r for r in records if r["status"] == status_filter]
        if search_query:
            records = [r for r in records if search_query.lower() in r["name"].lower()]

        apply_sort(records)
        page_records, pagination = paginate(records)

        context.update(
            {
                "active_tab": "students",
                "records": page_records,
                "pagination": pagination,
                "singular_label": "Student",
                "plural_label": "Students",
                "available_classes": available_classes,
                "class_filter": class_filter,
                "status_options": ["Active", "Inactive"],
                "status_filter": status_filter,
                "search_query": search_query,
                "sort": sort,
                "total_count": len(records),
            }
        )
    else:
        tab = "staff"
        records = [staff_record(member) for member in Staff.query.all()]

        if status_filter:
            records = [r for r in records if r["status"] == status_filter]
        if search_query:
            records = [r for r in records if search_query.lower() in r["name"].lower()]

        apply_sort(records)
        page_records, pagination = paginate(records)

        context.update(
            {
                "active_tab": "staff",
                "records": page_records,
                "pagination": pagination,
                "singular_label": "Staff",
                "plural_label": "Staff",
                "status_options": ["Active", "Account not activated yet"],
                "status_filter": status_filter,
                "search_query": search_query,
                "sort": sort,
                "total_count": len(records),
            }
        )

    return render_template("profiles.html", **context)


@app.route("/profiles/staff/new", methods=["GET", "POST"])
def new_staff():
    context = base_context("profiles")
    errors = {}
    form = {"name": "", "email": "", "phone": "", "role": "teacher"}
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        form["name"] = request.form.get("name", "").strip()
        form["email"] = request.form.get("email", "").strip()
        form["phone"] = request.form.get("phone", "").strip()
        form["role"] = request.form.get("role", "teacher")

        if not form["name"]:
            errors["name"] = "Full name is required."
        if not form["email"]:
            errors["email"] = "Email is required so we can send account activation instructions."
        elif Staff.query.filter_by(email=form["email"]).first():
            errors["email"] = "That email is already in use."

        if form["role"] not in ("teacher", "admin"):
            form["role"] = "teacher"

        if errors:
            if wants_json:
                return jsonify({"success": False, "errors": errors}), 400
        else:
            temp_password = generate_temp_password()
            new_account = Staff(
                name=form["name"],
                email=form["email"],
                phone=form["phone"],
                role=form["role"],
                account_created=True,
                has_logged_in=False,
                must_change_password=True,
                is_active=True,
                created_on=date.today(),
            )
            set_staff_password(new_account, temp_password, remember_as_temp=True)
            db.session.add(new_account)
            db.session.commit()

            access_note = "full access" if form["role"] == "admin" else "access limited to student data only"
            flash(
                f"{form['name']} was added with {access_note}. Sign-in email: {form['email']} — "
                f"temporary password: {temp_password}. Share this with them directly; they'll be asked "
                f"to set their own password the first time they sign in.",
                "success",
            )
            redirect_url = url_for("profiles", tab="staff")
            if wants_json:
                return jsonify({"success": True, "redirect": redirect_url, "temp_password": temp_password})
            return redirect(redirect_url)

    context.update({"form": form, "errors": errors})
    return render_template("new_staff.html", **context)


@app.route("/profiles/students/new", methods=["GET", "POST"])
def new_student():
    context = base_context("profiles")
    errors = {}
    form = {"registration_number": "", "name": "", "gender": "", "lin": "", "date_of_birth": ""}
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        # No current form collects registration_number directly (it's auto-assigned),
        # but still honor one if a caller supplies it, so long as it's unique.
        form["registration_number"] = request.form.get("registration_number", "").strip()
        form["name"] = request.form.get("name", "").strip()
        form["gender"] = request.form.get("gender", "").strip()
        form["lin"] = request.form.get("lin", "").strip()
        form["date_of_birth"] = request.form.get("date_of_birth", "").strip()

        if form["registration_number"] and Student.query.filter_by(registration_number=form["registration_number"]).first():
            errors["registration_number"] = "That registration number is already in use."

        if not form["name"]:
            errors["name"] = "Full name is required."
        if form["gender"] not in ("Male", "Female"):
            errors["gender"] = "Select the student's gender."
        if not form["date_of_birth"]:
            errors["date_of_birth"] = "Date of birth is required."
        # LIN is intentionally optional here — it can be added or corrected later from the student's profile.

        if errors:
            if wants_json:
                return jsonify({"success": False, "errors": errors}), 400
        else:
            reg_no = form["registration_number"] or generate_registration_number()
            db.session.add(
                Student(
                    registration_number=reg_no,
                    name=form["name"],
                    gender=form["gender"],
                    lin=form["lin"],
                    date_of_birth=parse_seed_date(form["date_of_birth"]),
                    current_class_name="",
                    created_on=date.today(),
                )
            )
            db.session.commit()
            flash(f"{form['name']} was registered as {reg_no}. Enroll them in a class under Academics to mark them active.", "success")
            redirect_url = url_for("profiles", tab="students")
            if wants_json:
                return jsonify({"success": True, "redirect": redirect_url})
            return redirect(redirect_url)

    context.update({"form": form, "errors": errors})
    return render_template("new_student.html", **context)


@app.route("/profiles/staff/bulk-upload", methods=["POST"])
def bulk_upload_staff():
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    upload = request.files.get("file")

    if not upload or not upload.filename:
        errors = {"file": "Choose a CSV file first."}
        if wants_json:
            return jsonify({"success": False, "errors": errors}), 400
        flash(errors["file"], "error")
        return redirect(url_for("profiles", tab="staff"))

    try:
        rows = read_csv_upload(upload)
    except (UnicodeDecodeError, csv.Error):
        errors = {"file": "Could not read that file. Please upload a CSV exported from a spreadsheet."}
        if wants_json:
            return jsonify({"success": False, "errors": errors}), 400
        flash(errors["file"], "error")
        return redirect(url_for("profiles", tab="staff"))

    added = 0
    skipped = []
    seen_emails = set()

    for row_number, row in enumerate(rows, start=2):  # row 1 is the header
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip().lower()
        phone = (row.get("phone") or "").strip()
        role = (row.get("role") or "").strip().lower()
        if role not in ("teacher", "admin"):
            role = "teacher"

        if not name:
            skipped.append({"row": row_number, "reason": "Missing full name."})
            continue
        if not email:
            skipped.append({"row": row_number, "reason": "Missing email."})
            continue
        if email in seen_emails or Staff.query.filter_by(email=email).first():
            skipped.append({"row": row_number, "reason": f"Email {email} is already in use."})
            continue

        seen_emails.add(email)
        db.session.add(
            Staff(
                name=name,
                email=email,
                phone=phone,
                role=role,
                account_created=True,
                has_logged_in=False,
                created_on=date.today(),
            )
        )
        added += 1

    db.session.commit()
    message = f"{added} staff member(s) added from the uploaded file."
    if wants_json:
        return jsonify({"success": True, "added": added, "total_rows": len(rows), "skipped": skipped})
    flash(message, "success")
    return redirect(url_for("profiles", tab="staff"))


@app.route("/profiles/students/bulk-upload", methods=["POST"])
def bulk_upload_students():
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    upload = request.files.get("file")

    if not upload or not upload.filename:
        errors = {"file": "Choose a CSV file first."}
        if wants_json:
            return jsonify({"success": False, "errors": errors}), 400
        flash(errors["file"], "error")
        return redirect(url_for("profiles", tab="students"))

    try:
        rows = read_csv_upload(upload)
    except (UnicodeDecodeError, csv.Error):
        errors = {"file": "Could not read that file. Please upload a CSV exported from a spreadsheet."}
        if wants_json:
            return jsonify({"success": False, "errors": errors}), 400
        flash(errors["file"], "error")
        return redirect(url_for("profiles", tab="students"))

    added = 0
    skipped = []
    seen_reg_numbers = set()
    seen_lins = set()

    for row_number, row in enumerate(rows, start=2):  # row 1 is the header
        name = (row.get("name") or "").strip()
        gender_raw = (row.get("gender") or "").strip()
        lin = (row.get("lin") or "").strip()
        dob_raw = (row.get("date_of_birth") or "").strip()
        reg_no = (row.get("registration_number") or "").strip()

        if not name:
            skipped.append({"row": row_number, "reason": "Missing full name."})
            continue

        gender = normalize_gender(gender_raw)
        if not gender:
            skipped.append({"row": row_number, "reason": "Gender must be Male or Female."})
            continue

        date_of_birth = parse_strict_date(dob_raw) if dob_raw else None
        if dob_raw and date_of_birth is None:
            skipped.append({"row": row_number, "reason": "Date of birth wasn't recognized. Try DD-MM-YYYY, DD/MM/YYYY or YYYY-MM-DD."})
            continue

        # LIN is the one identifier every student actually carries on a
        # school-issued sheet, so it's what catches the same student showing
        # up twice — either repeated within this file, or already added from
        # an earlier upload — and keeps re-running the same file safe.
        if lin:
            if lin in seen_lins:
                skipped.append({"row": row_number, "reason": f"LIN {lin} is duplicated in this file."})
                continue
            if Student.query.filter_by(lin=lin).first():
                skipped.append({"row": row_number, "reason": f"LIN {lin} already belongs to an existing student."})
                continue

        if reg_no:
            if reg_no in seen_reg_numbers or Student.query.filter_by(registration_number=reg_no).first():
                skipped.append({"row": row_number, "reason": f"Registration number {reg_no} is already in use."})
                continue
        else:
            reg_no = generate_registration_number()

        seen_reg_numbers.add(reg_no)
        if lin:
            seen_lins.add(lin)
        db.session.add(
            Student(
                registration_number=reg_no,
                name=name,
                gender=gender,
                lin=lin,
                date_of_birth=date_of_birth,
                current_class_name="",
                created_on=date.today(),
            )
        )
        added += 1

    db.session.commit()
    message = f"{added} student(s) added from the uploaded file."
    if wants_json:
        return jsonify({"success": True, "added": added, "total_rows": len(rows), "skipped": skipped})
    flash(message, "success")
    return redirect(url_for("profiles", tab="students"))


# --- Profiles: edit + delete (powers the Actions column popups) ---

@app.route("/profiles/staff/<int:staff_id>/edit", methods=["POST"])
def edit_staff(staff_id):
    member = db.session.get(Staff, staff_id)
    if member is None:
        abort(404)

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()

    if not name or not email:
        message = "Full name and email are required to update a staff record."
        if wants_json:
            errors = {}
            if not name:
                errors["name"] = "Full name is required."
            if not email:
                errors["email"] = "Email is required."
            return jsonify({"success": False, "errors": errors}), 400
        flash(message, "error")
        return redirect(url_for("profiles", tab="staff"))

    duplicate = Staff.query.filter(Staff.email == email, Staff.id != staff_id).first()
    if duplicate:
        message = "That email is already in use by another staff member."
        if wants_json:
            return jsonify({"success": False, "errors": {"email": message}}), 400
        flash(message, "error")
        return redirect(url_for("profiles", tab="staff"))

    member.name = name
    member.email = email
    member.phone = request.form.get("phone", "").strip()
    member.role = request.form.get("role", member.role or "teacher")
    db.session.commit()

    flash(f"{member.name}'s details were updated.", "success")
    redirect_url = url_for("profiles", tab="staff")
    if wants_json:
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


@app.route("/profiles/staff/<int:staff_id>/delete", methods=["POST"])
def delete_staff(staff_id):
    current_account = current_staff_account()
    if current_account and current_account.id == staff_id:
        flash("You can't delete your own account. Ask another admin to do it.", "error")
        return redirect(url_for("profiles", tab="staff"))

    member = db.session.get(Staff, staff_id)
    if member:
        name = member.name
        for class_record in AcademicClass.query.filter_by(class_teacher_id=staff_id):
            class_record.class_teacher = None
        for subject in Subject.query.filter_by(teacher_id=staff_id):
            subject.teacher = None
        db.session.delete(member)
        db.session.commit()
        flash(f"{name} was removed from staff.", "success")
    return redirect(url_for("profiles", tab="staff"))


@app.route("/profiles/students/<int:student_id>/edit", methods=["POST"])
def edit_student(student_id):
    student = db.session.get(Student, student_id)
    if student is None:
        abort(404)

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    registration_number = request.form.get("registration_number", "").strip()
    name = request.form.get("name", "").strip()
    gender = request.form.get("gender", "").strip()
    date_of_birth = request.form.get("date_of_birth", "").strip()

    if not registration_number or not name or gender not in ("Male", "Female") or not date_of_birth:
        message = "Registration number, full name, gender, and date of birth are required."
        if wants_json:
            errors = {}
            if not registration_number:
                errors["registration_number"] = "Registration number is required."
            if not name:
                errors["name"] = "Full name is required."
            if gender not in ("Male", "Female"):
                errors["gender"] = "Select the student's gender."
            if not date_of_birth:
                errors["date_of_birth"] = "Date of birth is required."
            return jsonify({"success": False, "errors": errors}), 400
        flash(message, "error")
        return redirect(url_for("profiles", tab="students"))

    duplicate = Student.query.filter(Student.registration_number == registration_number, Student.id != student_id).first()
    if duplicate:
        message = "That registration number is already in use by another student."
        if wants_json:
            return jsonify({"success": False, "errors": {"registration_number": message}}), 400
        flash(message, "error")
        return redirect(url_for("profiles", tab="students"))

    student.registration_number = registration_number
    student.name = name
    student.gender = gender
    student.date_of_birth = parse_seed_date(date_of_birth)
    student.lin = request.form.get("lin", "").strip()
    # enrolled_class is intentionally untouched here — enrollment is managed under Academics.
    db.session.commit()

    flash(f"{student.name}'s details were updated.", "success")
    redirect_url = url_for("profiles", tab="students")
    if wants_json:
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


@app.route("/profiles/students/<int:student_id>/delete", methods=["POST"])
def delete_student(student_id):
    student = db.session.get(Student, student_id)
    if student:
        name = student.name
        db.session.delete(student)
        db.session.commit()
        flash(f"{name} was removed.", "success")
    return redirect(url_for("profiles", tab="students"))


# --- Academics: classes, subjects, enrollment, promotion ---

@app.route("/academics")
def academics():
    tab = request.args.get("tab", "classes")
    if tab not in ("classes", "subjects", "enrollment", "promotion"):
        tab = "classes"

    search_query = request.args.get("q", "").strip()
    context = base_context("academics")
    all_student_records = all_students()
    unenrolled_student_records = [
        s for s in all_student_records
        if not s.get("enrolled_class")
    ]
    enrolled_count = len(all_student_records) - len(unenrolled_student_records)
    context.update(
        {
            "active_tab": tab,
            "search_query": search_query,
            "classes": academic_class_records(),
            "students": all_student_records,
            "teachers": teacher_names(),
            "promotion_actions": ["Promoted", "Second sitting", "Repeating", "Discontinued"],
            # The "Bulk enroll" modal markup is shared across every Academics
            # tab (it just only gets a visible open-button on Enrollment), so
            # these need to be in context no matter which tab is active.
            "bulk_students": unenrolled_student_records,
            "enrolled_count": enrolled_count,
            "not_enrolled_count": len(unenrolled_student_records),
        }
    )

    if tab == "subjects":
        # Subjects are intentionally two-level: the landing page lists classes,
        # then a class-specific route lists only that class's subjects.
        records = academic_class_records()
        if search_query:
            query = search_query.lower()
            records = [r for r in records if query in r["name"].lower() or query in r["teacher"].lower()]
        records.sort(key=lambda r: r["name"].lower())
        total_count = len(records)
        page_records, pagination = paginate(records)
        context.update({
            "records": page_records,
            "pagination": pagination,
            "total_count": total_count,
            "singular_label": "Subject",
            "plural_label": "Subjects",
            "subject_class": None,
            "subject_detail": False,
        })
    elif tab == "enrollment":
        records = enrollment_class_records()
        if search_query:
            query = search_query.lower()
            records = [r for r in records if query in r["name"].lower() or query in r["teacher"].lower()]
        records.sort(key=lambda r: r["name"].lower())
        total_count = len(records)
        page_records, pagination = paginate(records)
        context.update({
            "records": page_records,
            "pagination": pagination,
            "total_count": total_count,
            "singular_label": "Enrollment",
            "plural_label": "Classes",
            "enrollment_class": None,
            "enrollment_detail": False,
        })
    elif tab == "promotion":
        records = promotion_records()
        if search_query:
            query = search_query.lower()
            records = [r for r in records if query in r["class_name"].lower()]
        records.sort(key=lambda r: r["class_name"].lower())
        total_count = len(records)
        page_records, pagination = paginate(records)
        context.update({
            "records": page_records,
            "pagination": pagination,
            "total_count": total_count,
            "singular_label": "Promotion",
            "plural_label": "Promotions",
            "latest_promotion_run": promotion_run_summary(latest_promotion_run()),
        })
    else:
        records = academic_class_records()
        if search_query:
            query = search_query.lower()
            records = [r for r in records if query in r["name"].lower() or query in r["teacher"].lower()]
        records.sort(key=lambda r: r["name"].lower())
        total_count = len(records)
        page_records, pagination = paginate(records)
        context.update({
            "records": page_records,
            "pagination": pagination,
            "total_count": total_count,
            "singular_label": "Class",
            "plural_label": "Classes",
        })

    return render_template("academics.html", **context)


@app.route("/academics/classes/new", methods=["POST"])
def new_academic_class():
    name = request.form.get("name", "").strip()
    teacher = request.form.get("teacher", "").strip()
    if not name:
        return jsonify({"success": False, "errors": {"name": "Class name is required."}}), 400
    if AcademicClass.query.filter(db.func.lower(AcademicClass.name) == name.lower()).first():
        return jsonify({"success": False, "errors": {"name": "That class already exists."}}), 400

    class_teacher = Staff.query.filter_by(name=teacher).first() if teacher else None
    db.session.add(AcademicClass(name=name, level=class_level(name), class_teacher=class_teacher))
    db.session.commit()
    return json_or_redirect("classes", f"{name} was added.")


@app.route("/academics/classes/<int:class_id>/edit", methods=["POST"])
def edit_academic_class(class_id):
    class_record = AcademicClass.query.get(class_id)
    if class_record is None:
        abort(404)

    name = request.form.get("name", "").strip()
    teacher = request.form.get("teacher", "").strip()
    if not name:
        return jsonify({"success": False, "errors": {"name": "Class name is required."}}), 400
    if AcademicClass.query.filter(
        db.func.lower(AcademicClass.name) == name.lower(), AcademicClass.id != class_id
    ).first():
        return jsonify({"success": False, "errors": {"name": "That class already exists."}}), 400

    old_name = class_record.name
    class_record.name = name
    class_record.level = class_level(name)
    class_record.class_teacher = Staff.query.filter_by(name=teacher).first() if teacher else None
    # Subjects and enrollments link to the class by id, so renaming here is all
    # that's needed for them. Students only, since current_class_name is stored
    # as plain text on the student row, need updating explicitly.
    if old_name != name:
        Student.query.filter_by(current_class_name=old_name).update({"current_class_name": name})
    db.session.commit()
    return json_or_redirect("classes", f"{name} was updated.")


@app.route("/academics/classes/<int:class_id>/delete", methods=["POST"])
def delete_academic_class(class_id):
    class_record = AcademicClass.query.get(class_id)
    if class_record:
        name = class_record.name
        db.session.delete(class_record)
        db.session.commit()
        flash(f"{name} was removed.", "success")
    return redirect(academic_redirect("classes"))


@app.route("/academics/classes/<int:class_id>/download")
def download_class_students(class_id):
    class_record = AcademicClass.query.get(class_id)
    if class_record is None:
        abort(404)

    lines = ["Registration number,Name,Class"]
    for student in get_class_students(class_record.name):
        lines.append(f"{student['registration_number']},{student['name']},{class_record.name}")
    csv_body = "\n".join(lines) + "\n"
    filename = f"{class_record.name.lower().replace(' ', '-')}-students.csv"
    return Response(
        csv_body,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/academics/subjects/<int:class_id>")
def academic_subjects_class(class_id):
    academic_class = AcademicClass.query.get(class_id)
    if academic_class is None:
        abort(404)

    search_query = request.args.get("q", "").strip()
    all_student_records = all_students()
    unenrolled_student_records = [s for s in all_student_records if not s.get("enrolled_class")]
    enrolled_count = len(all_student_records) - len(unenrolled_student_records)
    context = base_context("academics")
    records = subject_records(class_id)
    if search_query:
        query = search_query.lower()
        records = [
            r for r in records
            if query in r["name"].lower() or query in r["teacher"].lower()
        ]
    records.sort(key=lambda r: r["name"].lower())
    total_count = len(records)
    page_records, pagination = paginate(records)
    context.update({
        "active_tab": "subjects",
        "search_query": search_query,
        "classes": all_academic_classes(),
        "students": all_student_records,
        "teachers": teacher_names(),
        "promotion_actions": ["Promoted", "Second sitting", "Repeating", "Discontinued"],
        "bulk_students": unenrolled_student_records,
        "enrolled_count": enrolled_count,
        "not_enrolled_count": len(unenrolled_student_records),
        "records": page_records,
        "pagination": pagination,
        "total_count": total_count,
        "singular_label": "Subject",
        "plural_label": "Subjects",
        "subject_class": academic_class,
        "subject_detail": True,
    })
    return render_template("academics.html", **context)


@app.route("/academics/subjects/new", methods=["POST"])
def new_subject():
    name = request.form.get("name", "").strip()
    class_name = request.form.get("class_name", "").strip()
    maximum_mark = request.form.get("maximum_mark", "").strip()
    teacher = request.form.get("teacher", "").strip()
    is_compulsory = request.form.get("is_compulsory") == "on"
    academic_class = AcademicClass.query.filter_by(name=class_name).first() if class_name else None
    errors = {}
    if not name:
        errors["name"] = "Subject name is required."
    if not class_name or academic_class is None:
        errors["class_name"] = "Class is required."
    if not maximum_mark.isdigit():
        errors["maximum_mark"] = "Maximum mark must be a number."
    if not errors and academic_class and Subject.query.filter_by(class_id=academic_class.id, name=name).first():
        errors["name"] = "That subject already exists for this class."
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    db.session.add(
        Subject(
            name=name,
            academic_class=academic_class,
            maximum_mark=int(maximum_mark),
            is_compulsory=is_compulsory,
            teacher=Staff.query.filter_by(name=teacher).first() if teacher else None,
        )
    )
    db.session.commit()
    flash(f"{name} was added.", "success")
    class_id = academic_class.id if academic_class else None
    redirect_url = url_for("academic_subjects_class", class_id=class_id) if class_id else academic_redirect("subjects")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


@app.route("/academics/subjects/<int:subject_id>/edit", methods=["POST"])
def edit_subject(subject_id):
    subject = Subject.query.get(subject_id)
    if subject is None:
        abort(404)

    name = request.form.get("name", "").strip()
    class_name = request.form.get("class_name", "").strip()
    maximum_mark = request.form.get("maximum_mark", "").strip()
    teacher = request.form.get("teacher", "").strip()
    academic_class = AcademicClass.query.filter_by(name=class_name).first() if class_name else None
    errors = {}
    if not name:
        errors["name"] = "Subject name is required."
    if not class_name or academic_class is None:
        errors["class_name"] = "Class is required."
    if not maximum_mark.isdigit():
        errors["maximum_mark"] = "Maximum mark must be a number."
    if (
        not errors
        and academic_class
        and Subject.query.filter(
            Subject.class_id == academic_class.id, Subject.name == name, Subject.id != subject_id
        ).first()
    ):
        errors["name"] = "That subject already exists for this class."
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    subject.name = name
    subject.academic_class = academic_class
    subject.maximum_mark = int(maximum_mark)
    subject.is_compulsory = request.form.get("is_compulsory") == "on"
    subject.teacher = Staff.query.filter_by(name=teacher).first() if teacher else None
    db.session.commit()
    flash(f"{name} was updated.", "success")
    redirect_url = url_for("academic_subjects_class", class_id=subject.class_id)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


@app.route("/academics/subjects/<int:subject_id>/delete", methods=["POST"])
def delete_subject(subject_id):
    subject = Subject.query.get(subject_id)
    class_id = subject.class_id if subject else None
    if subject:
        name = subject.name
        db.session.delete(subject)
        db.session.commit()
        flash(f"{name} was removed.", "success")
    return redirect(url_for("academic_subjects_class", class_id=class_id)) if class_id else redirect(academic_redirect("subjects"))


@app.route("/academics/enrollment/<int:class_id>")
def academic_enrollment_class(class_id):
    academic_class = AcademicClass.query.get(class_id)
    if academic_class is None:
        abort(404)

    search_query = request.args.get("q", "").strip()
    all_student_records = all_students()
    unenrolled_student_records = [
        s for s in all_student_records
        if not s.get("enrolled_class")
    ]
    enrolled_count = len(all_student_records) - len(unenrolled_student_records)
    records = enrollment_student_records(class_id)
    if search_query:
        query = search_query.lower()
        records = [
            r for r in records
            if query in r["name"].lower()
            or query in r["registration_number"].lower()
            or query in r["status"].lower()
        ]
    records.sort(key=lambda r: r["name"].lower())
    total_count = len(records)
    page_records, pagination = paginate(records)

    context = base_context("academics")
    context.update({
        "active_tab": "enrollment",
        "search_query": search_query,
        "classes": all_academic_classes(),
        "students": all_student_records,
        "teachers": teacher_names(),
        "promotion_actions": ["Promoted", "Second sitting", "Repeating", "Discontinued"],
        "bulk_students": unenrolled_student_records,
        "enrolled_count": enrolled_count,
        "not_enrolled_count": len(unenrolled_student_records),
        "records": page_records,
        "pagination": pagination,
        "total_count": total_count,
        "singular_label": "Enrollment",
        "plural_label": "Students",
        "enrollment_class": academic_class,
        "enrollment_detail": True,
    })
    return render_template("academics.html", **context)


@app.route("/academics/enrollment/student/<int:student_id>/remove", methods=["POST"])
def remove_student_from_enrollment(student_id):
    student = Student.query.get(student_id)
    class_id = None
    if student and student.current_class_name:
        academic_class = AcademicClass.query.filter_by(name=student.current_class_name).first()
        class_id = academic_class.id if academic_class else None
        for enrollment in Enrollment.query.filter_by(status="Enrolled").all():
            if student in enrollment.students:
                enrollment.students.remove(student)
        student.current_class_name = ""
        db.session.commit()
        flash(f"{student.name} was removed from enrollment.", "success")
    return redirect(url_for("academic_enrollment_class", class_id=class_id)) if class_id else redirect(academic_redirect("enrollment"))


@app.route("/academics/enrollment/new", methods=["POST"])
def new_enrollment():
    try:
        class_name = request.form.get("class_name", "").strip()
        student_ids = [int(v) for v in request.form.getlist("student_ids") if v.isdigit()]
        
        # Validate inputs
        academic_class = AcademicClass.query.filter_by(name=class_name).first() if class_name else None
        if not class_name or academic_class is None:
            return jsonify({"success": False, "errors": {"class_name": "Class is required."}}), 400
        if not student_ids:
            return jsonify({"success": False, "errors": {"student_ids": "Choose at least one student."}}), 400

        # Get students and check if already enrolled
        students = Student.query.filter(Student.id.in_(student_ids)).all()
        if not students:
            return jsonify({"success": False, "errors": {"student_ids": "No valid students selected."}}), 400
            
        already_enrolled = [student.name for student in students if student.current_class_name]
        if already_enrolled:
            message = "Already enrolled: " + ", ".join(already_enrolled)
            return jsonify({"success": False, "errors": {"student_ids": message}}), 400

        # Update students and create enrollment
        for student in students:
            student.current_class_name = class_name
            db.session.add(student)
        
        # Create enrollment record
        enrollment = Enrollment(
            date=date.today(), 
            academic_class=academic_class, 
            status="Enrolled"
        )
        # Add students to enrollment via the relationship
        enrollment.students.extend(students)
        db.session.add(enrollment)
        db.session.commit()

        message = f"{len(student_ids)} student(s) enrolled in {class_name}."
        redirect_url = url_for("academic_enrollment_class", class_id=academic_class.id)
        
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "redirect": redirect_url, "message": message})
        
        flash(message, "success")
        return redirect(redirect_url)
        
    except Exception as e:
        print(f"Enrollment error: {e}")
        db.session.rollback()
        error_msg = f"Enrollment failed: {str(e)}"
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "errors": {"general": error_msg}}), 500
        flash(error_msg, "error")
        return redirect(url_for("academics"))


@app.route("/academics/enrollment/<int:enrollment_id>/edit", methods=["POST"])
def edit_enrollment(enrollment_id):
    enrollment = Enrollment.query.get(enrollment_id)
    if enrollment is None:
        abort(404)

    class_name = request.form.get("class_name", "").strip()
    student_ids = [int(v) for v in request.form.getlist("student_ids") if v.isdigit()]
    status = request.form.get("status", "Enrolled")
    academic_class = AcademicClass.query.filter_by(name=class_name).first() if class_name else None
    if not class_name or academic_class is None:
        return jsonify({"success": False, "errors": {"class_name": "Class is required."}}), 400
    if not student_ids:
        return jsonify({"success": False, "errors": {"student_ids": "Choose at least one student."}}), 400

    students = Student.query.filter(Student.id.in_(student_ids)).all()
    enrollment.academic_class = academic_class
    enrollment.students = students
    enrollment.status = status
    for student in students:
        student.current_class_name = class_name if status == "Enrolled" else ""
    db.session.commit()
    flash(f"{class_name} enrollment was updated.", "success")
    redirect_url = url_for("academic_enrollment_class", class_id=academic_class.id)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


@app.route("/academics/enrollment/<int:enrollment_id>/unenroll", methods=["POST"])
def unenroll_students(enrollment_id):
    enrollment = Enrollment.query.get(enrollment_id)
    if enrollment:
        enrollment.status = "Unenrolled"
        for student in enrollment.students:
            student.current_class_name = ""
        class_name = enrollment.academic_class.name if enrollment.academic_class else ""
        class_id = enrollment.class_id
        db.session.commit()
        flash(f"{class_name} enrollment was marked unenrolled.", "success")
        return redirect(url_for("academic_enrollment_class", class_id=class_id))
    return redirect(academic_redirect("enrollment"))


@app.route("/academics/promotion/<int:class_id>/decisions", methods=["POST"])
def update_promotion_decisions(class_id):
    class_record = AcademicClass.query.get(class_id)
    if class_record is None:
        abort(404)

    bulk_action = request.form.get("bulk_action", "")
    allowed = {"Promoted", "Second sitting", "Repeating", "Discontinued"}
    for student in get_class_students(class_record.name):
        decision = bulk_action or request.form.get(f"student_{student['id']}", "")
        if decision in allowed:
            existing = PromotionDecision.query.filter_by(student_id=student["id"]).first()
            if existing:
                existing.decision = decision
            else:
                db.session.add(PromotionDecision(student_id=student["id"], decision=decision))
    db.session.commit()
    return json_or_redirect("promotion", f"{class_record.name} promotion decisions were updated.")


@app.route("/academics/promotion/run", methods=["POST"])
def run_promotion():
    """Apply year-end promotion to every currently-enrolled student.

    Each student's saved decision (Academics > Promotion) decides what
    happens to them; a student with no decision recorded defaults to
    "Promoted", since most students move up every year and admins are
    only expected to mark the exceptions:
      - Promoted (or no decision): moved to the next class — same stream
        one level up where it exists, otherwise the next plain class.
        Primary 7 students have nowhere further to go, so they're marked
        as having completed primary school instead.
      - Repeating / Second sitting: stay in their current class.
      - Discontinued: unenrolled (current class cleared).
    The whole batch is recorded as a PromotionRun so it — or any single
    student in it — can be undone afterwards.
    """
    class_names = [c["name"] for c in all_academic_classes()]
    decisions = {d.student_id: d.decision for d in PromotionDecision.query.all()}
    students = Student.query.filter(Student.current_class_name != "").order_by(Student.name).all()

    if not students:
        return promotion_json_or_redirect("There are no enrolled students to promote.", "error")

    run = PromotionRun(run_date=date.today(), label=f"Promotion — {date.today().strftime('%d %b %Y')}")
    db.session.add(run)
    db.session.flush()

    counts = {"Moved": 0, "Stayed": 0, "Completed": 0, "Discontinued": 0, "Unresolved": 0}
    no_next_class_names = set()
    ambiguous_class_names = set()
    for student in students:
        decision = decisions.get(student.id, PROMOTION_DEFAULT_DECISION)
        from_class = student.current_class_name
        to_class = from_class

        if decision == "Discontinued":
            outcome = "Discontinued"
            to_class = ""
            student.current_class_name = ""
        elif decision in PROMOTION_STAY_DECISIONS:
            outcome = "Stayed"
        else:
            target = resolve_promotion_target(from_class, class_names)
            if target["outcome"] == "matched":
                outcome = "Moved"
                to_class = target["class_name"]
                student.current_class_name = to_class
            elif target["outcome"] == "final_year":
                outcome = "Completed"
                to_class = ""
                student.current_class_name = ""
            else:
                outcome = "Unresolved"
                if target["reason"] == "no_next_class":
                    no_next_class_names.add(from_class)
                elif target["reason"] == "ambiguous_stream":
                    ambiguous_class_names.add(from_class)

        counts[outcome] += 1
        db.session.add(PromotionRunEntry(
            run_id=run.id,
            student_id=student.id,
            decision=decision,
            from_class_name=from_class,
            to_class_name=to_class,
            outcome=outcome,
        ))

    # Decisions were for this year-end only — clear them so next year starts fresh.
    PromotionDecision.query.delete()
    db.session.commit()

    parts = []
    if counts["Moved"]:
        parts.append(f"{counts['Moved']} promoted")
    if counts["Stayed"]:
        parts.append(f"{counts['Stayed']} kept in their class")
    if counts["Completed"]:
        parts.append(f"{counts['Completed']} completed Primary 7")
    if counts["Discontinued"]:
        parts.append(f"{counts['Discontinued']} discontinued")
    if counts["Unresolved"]:
        parts.append(f"{counts['Unresolved']} left in place, needing manual placement")
    message = "Promotion applied: " + ", ".join(parts) + "."

    if no_next_class_names:
        message += (
            " No next class exists yet for: " + ", ".join(sorted(no_next_class_names))
            + " — create the next class first, then promote those students individually."
        )
    if ambiguous_class_names:
        message += (
            " More than one possible next class (streams) was found for: "
            + ", ".join(sorted(ambiguous_class_names)) + " — choose it manually for those students."
        )

    category = "error" if (no_next_class_names or ambiguous_class_names) and not counts["Moved"] else "success"
    return promotion_json_or_redirect(message, category)


def _revert_promotion_entry(entry):
    """Move one student back to their pre-promotion class and restore the
    decision that was recorded for them, then mark the entry reverted."""
    student = entry.student
    if student is not None:
        student.current_class_name = entry.from_class_name
        if entry.decision and entry.decision != PROMOTION_DEFAULT_DECISION:
            existing = PromotionDecision.query.filter_by(student_id=student.id).first()
            if existing:
                existing.decision = entry.decision
            else:
                db.session.add(PromotionDecision(student_id=student.id, decision=entry.decision))
    entry.reverted = True


@app.route("/academics/promotion/undo", methods=["POST"])
def undo_promotion():
    """Undo the most recent promotion run in full."""
    run = latest_promotion_run()
    if run is None or run.status != "Applied":
        return promotion_json_or_redirect("There's no applied promotion to undo.", "error")

    restored = 0
    for entry in run.entries:
        if entry.reverted:
            continue
        _revert_promotion_entry(entry)
        restored += 1
    run.status = "Reverted"
    db.session.commit()
    return promotion_json_or_redirect(
        f"Promotion undone — {restored} student(s) restored to their previous class.", "success"
    )


@app.route("/academics/promotion/undo-student/<int:student_id>", methods=["POST"])
def undo_promotion_student(student_id):
    """Undo one student's most recent promotion, leaving everyone else's
    promotion in place — for the case where just one student was
    promoted (or held back) by mistake."""
    entry = (
        PromotionRunEntry.query
        .filter_by(student_id=student_id, reverted=False)
        .order_by(PromotionRunEntry.id.desc())
        .first()
    )
    if entry is None:
        return promotion_json_or_redirect("This student has no recent promotion to undo.", "error")

    student = entry.student
    name = student.name if student else "Student"
    from_class = entry.from_class_name
    _revert_promotion_entry(entry)

    run = entry.run
    if run is not None and run.status == "Applied" and all(e.reverted for e in run.entries):
        run.status = "Reverted"

    db.session.commit()
    return promotion_json_or_redirect(
        f"{name}'s promotion was undone — moved back to {from_class or 'Not enrolled'}.", "success"
    )


# --- Placeholder routes for the rest of the main menu ---


@app.route("/grades")
def grades():
    tab = request.args.get("tab", "assessments")
    if tab not in ("assessments", "comments"):
        tab = "assessments"

    search_query = request.args.get("q", "").strip()
    context = base_context("grades")
    class_records = grade_class_records(tab)
    if search_query:
        query = search_query.lower()
        class_records = [
            r for r in class_records
            if query in r["name"].lower()
            or query in r["teacher"].lower()
            or query in r["level"].lower()
        ]
    class_records.sort(key=lambda r: r["name"].lower())
    total_count = len(class_records)
    page_records, pagination = paginate(class_records)

    context.update({
        "active_tab": tab,
        "search_query": search_query,
        "sort": request.args.get("sort", "assessment_type"),
        "classes": all_academic_classes(),
        "students": all_students(),
        "subjects": all_subjects(),
        "teachers": teacher_names(),
        "assessment_types": ASSESSMENT_TYPES,
        "sort_options": [
            {"value": "assessment_type", "label": "Assessment type"},
            {"value": "student", "label": "Student"},
            {"value": "subject", "label": "Subject"},
        ],
        "records": page_records,
        "pagination": pagination,
        "total_count": total_count,
        "singular_label": "Assessment" if tab == "assessments" else "Comment",
        "plural_label": "Classes",
        "grade_detail": False,
        "grade_class": None,
        "comment_students": [],
        "comment_student": None,
        "student_comments": [],
        "comment_report_stages": COMMENT_REPORT_STAGES,
        "comment_allowed_teachers": {},
        "head_teacher": head_teacher_record(),
    })
    return render_template("grades.html", **context)


@app.route("/grades/<tab>/<int:class_id>")
def grades_class(tab, class_id):
    if tab not in ("assessments", "comments"):
        abort(404)

    academic_class = AcademicClass.query.get(class_id)
    if academic_class is None:
        abort(404)

    search_query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "assessment_type")
    context = base_context("grades")
    context.update({
        "active_tab": tab,
        "search_query": search_query,
        "sort": sort,
        "classes": all_academic_classes(),
        "students": get_class_students(academic_class.name),
        "subjects": [s for s in all_subjects() if s["class_name"] == academic_class.name],
        "teachers": teacher_names(),
        "assessment_types": ASSESSMENT_TYPES,
        "sort_options": [
            {"value": "assessment_type", "label": "Assessment type"},
            {"value": "student", "label": "Student"},
            {"value": "subject", "label": "Subject"},
        ],
        "grade_detail": True,
        "grade_class": academic_class,
        "comment_students": [],
        "comment_student": None,
        "student_comments": [],
        "comment_report_stages": COMMENT_REPORT_STAGES,
        "comment_allowed_teachers": {},
        "head_teacher": head_teacher_record(),
    })

    if tab == "assessments":
        records = [r for r in assessment_records() if r["class_name"] == academic_class.name]
        if search_query:
            query = search_query.lower()
            records = [
                r for r in records
                if query in r["subject"].lower()
                or query in r["assessment_type"].lower()
                or any(query in s["name"].lower() for s in r["students"])
            ]
        if sort == "subject":
            records.sort(key=lambda r: (r["subject"].lower(), r["assessment_type"].lower()))
        elif sort == "student":
            records.sort(key=lambda r: (r["recorded_count"], r["subject"].lower()), reverse=True)
        else:
            sort = "assessment_type"
            records.sort(key=lambda r: (r["assessment_type"].lower(), r["subject"].lower()))
            context["sort"] = sort
        total_count = len(records)
        page_records, pagination = paginate(records)
        context.update({
            "records": page_records,
            "pagination": pagination,
            "total_count": total_count,
            "singular_label": "Assessment",
            "plural_label": "Assessments",
        })
    else:
        # Comments: second-level navigation is now a plain student list —
        # one row per student in this class, clickable through to that
        # student's own comments page — matching how Enrollment and Subjects
        # drill from a class into their own second-level list.
        students = get_class_students(academic_class.name)
        if search_query:
            query = search_query.lower()
            students = [
                s for s in students
                if query in s["name"].lower()
                or query in (s.get("registration_number") or "").lower()
            ]
        students.sort(key=lambda s: s["name"].lower())
        comments = [r for r in comment_records() if r["class_name"] == academic_class.name]
        comments_by_student = {}
        for comment in comments:
            comments_by_student.setdefault(comment["student_id"], []).append(comment)
        comment_students = []
        for student in students:
            comment_students.append({
                **student,
                "comments": comments_by_student.get(student["id"], []),
            })
        total_count = len(comment_students)
        page_comment_students, pagination = paginate(comment_students)
        context.update({
            "records": comments,
            "comment_students": page_comment_students,
            "pagination": pagination,
            "total_count": total_count,
            "singular_label": "Comment",
            "plural_label": "Students",
        })

    return render_template("grades.html", **context)


@app.route("/grades/comments/class/<int:class_id>/student/<int:student_id>")
def grades_comment_student(class_id, student_id):
    """Third-level comments view: every comment recorded for one student,
    editable/deletable in place, with an Add comment form restricted to
    this class's own class teacher and the school's head teacher."""
    academic_class = AcademicClass.query.get(class_id)
    if academic_class is None:
        abort(404)

    student = Student.query.get(student_id)
    if student is None or student.current_class_name != academic_class.name:
        abort(404)

    student_comments = [c for c in comment_records() if c["student_id"] == student_id]
    student_comments.sort(key=lambda c: c["id"], reverse=True)
    total_count = len(student_comments)
    page_student_comments, pagination = paginate(student_comments)

    context = base_context("grades")
    context.update({
        "active_tab": "comments",
        "search_query": "",
        "sort": request.args.get("sort", "assessment_type"),
        "classes": all_academic_classes(),
        "students": get_class_students(academic_class.name),
        "subjects": [],
        "teachers": teacher_names(),
        "assessment_types": ASSESSMENT_TYPES,
        "sort_options": [],
        "records": [],
        "grade_detail": True,
        "grade_class": academic_class,
        "comment_students": [],
        "comment_student": student_record(student),
        "student_comments": page_student_comments,
        "pagination": pagination,
        "total_count": total_count,
        "comment_report_stages": COMMENT_REPORT_STAGES,
        "comment_allowed_teachers": allowed_comment_teachers(academic_class.name),
        "head_teacher": head_teacher_record(),
        "singular_label": "Comment",
        "plural_label": "Comments",
    })
    return render_template("grades.html", **context)


@app.route("/grades/assessments/new", methods=["POST"])
def new_assessment():
    assessment_date = request.form.get("date", "").strip()
    subject_id = request.form.get("subject_id", "").strip()
    assessment_type = request.form.get("assessment_type", "").strip()
    maximum = request.form.get("maximum", "").strip()
    subject = Subject.query.get(int(subject_id)) if subject_id.isdigit() else None
    errors = {}
    if not assessment_date:
        errors["date"] = "Date is required."
    if not subject:
        errors["subject_id"] = "Subject is required."
    if not assessment_type:
        errors["assessment_type"] = "Assessment type is required."
    if not maximum.isdigit():
        errors["maximum"] = "Maximum mark must be a number."
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    db.session.add(
        Assessment(
            date=parse_seed_date(assessment_date),
            subject=subject,
            assessment_type=assessment_type,
            maximum=int(maximum),
        )
    )
    db.session.commit()
    return grades_json_or_redirect("assessments", f"{subject.name} assessment was added.", subject.class_id)


@app.route("/grades/assessments/<int:assessment_id>/edit", methods=["POST"])
def edit_assessment(assessment_id):
    assessment = Assessment.query.get(assessment_id)
    if assessment is None:
        abort(404)

    assessment_date = request.form.get("date", "").strip()
    subject_id = request.form.get("subject_id", "").strip()
    assessment_type = request.form.get("assessment_type", "").strip()
    maximum = request.form.get("maximum", "").strip()
    subject = Subject.query.get(int(subject_id)) if subject_id.isdigit() else None
    errors = {}
    if not assessment_date:
        errors["date"] = "Date is required."
    if not subject:
        errors["subject_id"] = "Subject is required."
    if not assessment_type:
        errors["assessment_type"] = "Assessment type is required."
    if not maximum.isdigit():
        errors["maximum"] = "Maximum mark must be a number."
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    assessment.date = parse_seed_date(assessment_date)
    assessment.subject = subject
    assessment.assessment_type = assessment_type
    assessment.maximum = int(maximum)
    db.session.commit()
    return grades_json_or_redirect("assessments", f"{subject.name} assessment was updated.", subject.class_id)


@app.route("/grades/assessments/<int:assessment_id>/results", methods=["POST"])
def update_assessment_results(assessment_id):
    assessment = Assessment.query.get(assessment_id)
    if assessment is None:
        abort(404)

    assessment_dict = assessment_record_dict(assessment)
    letter_mode = is_other_subject_assessment(assessment_dict)

    # Full replace, same as before: clear this assessment's results and
    # re-insert only the rows that actually have something recorded.
    AssessmentResult.query.filter_by(assessment_id=assessment_id).delete()

    for student in get_class_students(assessment_dict["class_name"]):
        if letter_mode:
            grade = request.form.get(f"grade_{student['id']}", "").strip().upper()
            remark = request.form.get(f"remark_{student['id']}", "").strip()
            if grade or remark:
                db.session.add(
                    AssessmentResult(assessment_id=assessment_id, student_id=student["id"], grade=grade, remark=remark)
                )
        else:
            mark = request.form.get(f"mark_{student['id']}", "").strip()
            aggregate = request.form.get(f"aggregate_{student['id']}", "").strip() or aggregate_from_mark(mark)
            if mark or aggregate:
                db.session.add(
                    AssessmentResult(assessment_id=assessment_id, student_id=student["id"], mark=mark, aggregate=aggregate)
                )
    db.session.commit()
    class_record = AcademicClass.query.filter_by(name=assessment_dict["class_name"]).first()
    return grades_json_or_redirect("assessments", f"{assessment_dict['subject']} results were updated.", class_record.id if class_record else None)


@app.route("/grades/assessments/<int:assessment_id>/delete", methods=["POST"])
def delete_assessment(assessment_id):
    assessment = Assessment.query.get(assessment_id)
    if assessment:
        subject_name = assessment.subject.name if assessment.subject else ""
        AssessmentResult.query.filter_by(assessment_id=assessment_id).delete()
        class_id = assessment.subject.class_id if assessment.subject else None
        db.session.delete(assessment)
        db.session.commit()
        flash(f"{subject_name} assessment was removed.", "success")
        if class_id:
            return redirect(url_for("grades_class", tab="assessments", class_id=class_id))
    return redirect(grades_redirect("assessments"))


@app.route("/grades/comments/new", methods=["POST"])
def new_grade_comment():
    student_id = request.form.get("student_id", "").strip()
    comment_type = request.form.get("comment_type", "").strip()
    report_stage = request.form.get("report_stage", "").strip()
    comment = request.form.get("comment", "").strip()
    teacher = request.form.get("teacher", "").strip()
    student = next((s for s in all_students() if str(s["id"]) == student_id), None)
    errors = {}
    if not student:
        errors["student_id"] = "Student is required."
    if not comment_type:
        errors["comment_type"] = "Comment type is required."
    if not report_stage:
        errors["report_stage"] = "Choose whether this is for the end of term report or the mini report."
    if not comment:
        errors["comment"] = "Comment is required."
    if student and teacher:
        allowed = allowed_comment_teachers(student.get("enrolled_class", ""))
        expected = allowed.get(comment_type, "")
        if expected and teacher != expected:
            errors["teacher"] = "Only this class's class teacher or the head teacher can be selected."
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    db.session.add(
        ReportComment(
            student_id=student["id"],
            comment_type=comment_type,
            report_stage=report_stage,
            comment=comment,
            teacher=teacher,
        )
    )
    db.session.commit()
    class_record = AcademicClass.query.filter_by(name=student.get("enrolled_class", "")).first()
    return grades_json_or_redirect(
        "comments",
        f"{student['name']}'s comment was added.",
        class_record.id if class_record else None,
        student["id"],
    )


@app.route("/grades/comments/<int:comment_id>/edit", methods=["POST"])
def edit_grade_comment(comment_id):
    report_comment = ReportComment.query.get(comment_id)
    if report_comment is None:
        abort(404)

    student_id = request.form.get("student_id", "").strip()
    comment_type = request.form.get("comment_type", "").strip()
    report_stage = request.form.get("report_stage", "").strip()
    comment = request.form.get("comment", "").strip()
    teacher = request.form.get("teacher", "").strip()
    student = next((s for s in all_students() if str(s["id"]) == student_id), None)
    errors = {}
    if not student:
        errors["student_id"] = "Student is required."
    if not comment_type:
        errors["comment_type"] = "Comment type is required."
    if not report_stage:
        errors["report_stage"] = "Choose whether this is for the end of term report or the mini report."
    if not comment:
        errors["comment"] = "Comment is required."
    if student and teacher:
        allowed = allowed_comment_teachers(student.get("enrolled_class", ""))
        expected = allowed.get(comment_type, "")
        if expected and teacher != expected:
            errors["teacher"] = "Only this class's class teacher or the head teacher can be selected."
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    report_comment.student_id = student["id"]
    report_comment.comment_type = comment_type
    report_comment.report_stage = report_stage
    report_comment.comment = comment
    report_comment.teacher = teacher
    db.session.commit()
    class_record = AcademicClass.query.filter_by(name=student.get("enrolled_class", "")).first()
    return grades_json_or_redirect(
        "comments",
        f"{student['name']}'s comment was updated.",
        class_record.id if class_record else None,
        student["id"],
    )


@app.route("/grades/comments/<int:comment_id>/delete", methods=["POST"])
def delete_grade_comment(comment_id):
    report_comment = ReportComment.query.get(comment_id)
    if report_comment:
        student = report_comment.student
        class_name = student.current_class_name if student else ""
        class_record = AcademicClass.query.filter_by(name=class_name).first() if class_name else None
        student_id = student.id if student else None
        db.session.delete(report_comment)
        db.session.commit()
        flash("Comment was removed.", "success")
        if class_record and student_id:
            return redirect(url_for("grades_comment_student", class_id=class_record.id, student_id=student_id))
    return redirect(grades_redirect("comments"))


@app.route("/reports")
def reports():
    tab = request.args.get("tab", "cards")
    if tab not in ("cards", "published", "marksheets"):
        tab = "cards"
    class_id = request.args.get("class_id", type=int)
    report_scope = request.args.get("scope", "").strip()
    search_query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "created_desc")

    source_records = all_published_reports() if tab == "published" else all_report_batches()
    records = report_records(source_records)
    selected_class = AcademicClass.query.get(class_id) if class_id else None
    if selected_class:
        records = [r for r in records if r.get("class_name") == selected_class.name]
    elif report_scope in ("All classes", "Lower primary", "Upper primary"):
        scoped_names = set(report_classes_for_scope(report_scope))
        records = [
            r for r in records
            if r.get("class_name") in scoped_names or r.get("attendance_scope") == report_scope
        ]
    if search_query:
        query = search_query.lower()
        records = [
            r for r in records
            if query in r["class_name"].lower()
            or query in r["report_type"].lower()
            or query in r.get("status", "").lower()
        ]

    if sort == "class":
        records.sort(key=lambda r: (r["class_name"].lower(), r["created_at"]))
    elif sort == "type":
        records.sort(key=lambda r: (r["report_type"].lower(), r["created_at"]))
    else:
        sort = "created_desc"
        records.sort(key=lambda r: r["created_at"], reverse=True)

    academic_classes = academic_class_records()
    sorted_classes = sorted(academic_classes, key=lambda c: c["name"].lower())

    total_count = len(records)
    classes_page = []
    if tab == "marksheets" and not selected_class:
        total_count = len(sorted_classes)
        classes_page, pagination = paginate(sorted_classes)
    else:
        records, pagination = paginate(records)

    context = base_context("reports")
    context.update(
        {
            "active_tab": tab,
            "report_scope": report_scope,
            "records": records,
            "pagination": pagination,
            "total_count": total_count,
            "search_query": search_query,
            "sort": sort,
            # Use the class records that include the live enrolled-student
            # count. The reports template renders this value in the Classes
            # table for both Report Cards and Published tabs.
            "classes": sorted_classes,
            "classes_page": classes_page,
            "report_scope_rows": report_scope_rows(records, sorted_classes),
            "selected_class": selected_class,
            "class_id": class_id,
            "report_types": REPORT_TYPES,
            "class_scopes": ["All classes", "Lower primary", "Upper primary"] + [c["name"] for c in all_academic_classes()],
            "school_info": school_info_dict(get_school()),
            "next_term_start": next_term_start_label(get_current_term()),
            "head_teacher": head_teacher_record(),
            "term_title": dict(zip(("word", "year"), term_title_parts(get_current_term()))),
            "sort_options": [
                {"value": "created_desc", "label": "Date created"},
                {"value": "class", "label": "Class"},
                {"value": "type", "label": "Type"},
            ],
            "marksheet_data": (
                {sheet_type: marksheet_data_for_class(selected_class.name, sheet_type)
                 for sheet_type in ("bot", "mid", "internal", "external")}
                if tab == "marksheets" and selected_class else {}
            ),
        }
    )
    return render_template("reports.html", **context)


@app.route("/reports/generate", methods=["POST"])
def generate_report():
    report_type = request.form.get("report_type", "").strip()
    class_scope = request.form.get("class_scope", "").strip()
    errors = {}
    if report_type not in REPORT_TYPES:
        errors["report_type"] = "Report type is required."
    selected_classes = report_classes_for_scope(class_scope)
    if not selected_classes:
        errors["class_scope"] = "Choose a class group."
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    created_at = datetime.now()

    # Group attendance is a single report for the selected scope. Do not create
    # one attendance report per class — the generated report itself contains
    # the class-by-class attendance breakdown. We keep one real class as the
    # required database anchor and store the scope in the status metadata.
    if report_type == "Attendance report" and class_scope in ("All classes", "Lower primary", "Upper primary"):
        selected_scope_classes = report_classes_for_scope(class_scope)
        anchor = AcademicClass.query.filter(AcademicClass.name.in_(selected_scope_classes)).order_by(AcademicClass.id).first()
        if not anchor:
            return jsonify({"success": False, "errors": {"class_scope": "No classes exist in this group."}}), 400
        students = Student.query.filter(Student.current_class_name.in_(selected_scope_classes)).all()
        db.session.add(
            ReportBatch(
                academic_class=anchor,
                report_type=report_type,
                generated_at=created_at,
                status="Generated",
                report_scope=class_scope,
                students=students,
            )
        )
        db.session.commit()
        return reports_json_or_redirect("cards", f"{class_scope} attendance report was created.")

    generated = 0
    for class_name in selected_classes:
        class_record = AcademicClass.query.filter_by(name=class_name).first()
        if not class_record:
            continue
        class_students = Student.query.filter_by(current_class_name=class_name).all()
        if report_type == "Assessment report" and not completed_assessment_subjects(class_name):
            status = "Pending"
            students = []
        else:
            status = "Generated" if class_students else "Pending"
            students = class_students
        db.session.add(
            ReportBatch(
                academic_class=class_record,
                report_type=report_type,
                generated_at=created_at,
                status=status,
                students=students,
            )
        )
        generated += 1
    db.session.commit()
    return reports_json_or_redirect("cards", f"{generated} report batch(es) were created.")


@app.route("/reports/<int:report_id>/publish", methods=["POST"])
def publish_report(report_id):
    report = ReportBatch.query.get(report_id)
    if report is None:
        abort(404)

    publish_here = request.form.get("publish_here") == "on"
    publish_sms = request.form.get("publish_sms") == "on"
    publish_email = request.form.get("publish_email") == "on"
    email = request.form.get("email", "").strip()
    if publish_email and not email:
        return jsonify({"success": False, "errors": {"email": "Email is required when email publishing is on."}}), 400
    if not (publish_here or publish_sms or publish_email):
        return jsonify({"success": False, "errors": {"publish_here": "Choose at least one publish option."}}), 400

    db.session.add(
        PublishedReport(
            academic_class=report.academic_class,
            report_type=report.report_type,
            generated_at=report.generated_at,
            published_at=datetime.now(),
            publish_here=publish_here,
            publish_sms=publish_sms,
            publish_email=publish_email,
            email=email,
            students=list(report.students),
        )
    )
    report.status = "Generated"
    db.session.commit()
    class_name = report.academic_class.name if report.academic_class else ""
    return reports_json_or_redirect("published", f"{class_name} report was published.")


@app.route("/reports/<int:report_id>/delete", methods=["POST"])
def delete_report(report_id):
    tab = request.form.get("tab", "cards")
    model = PublishedReport if tab == "published" else ReportBatch
    report = model.query.get(report_id)
    if report:
        class_name = report.academic_class.name if report.academic_class else ""
        db.session.delete(report)
        db.session.commit()
        flash(f"{class_name} report was removed.", "success")
    return redirect(reports_redirect(tab))


@app.route("/events")
def events():
    search_query = request.args.get("q", "").strip()
    records = event_records()
    if search_query:
        query = search_query.lower()
        records = [
            r for r in records
            if query in r["name"].lower()
            or query in r["audience"].lower()
            or query in r["teacher"].lower()
            or query in r["activity"].lower()
        ]
    records.sort(key=lambda r: parse_date(r["start_date"]) or date.max)
    total_count = len(records)
    page_records, pagination = paginate(records)

    context = base_context("events")
    context.update(
        {
            "records": page_records,
            "pagination": pagination,
            "total_count": total_count,
            "search_query": search_query,
            "classes": all_academic_classes(),
            "teachers": teacher_names() + ["Taaka Beatrice"],
        }
    )
    return render_template("events.html", **context)


@app.route("/events/new", methods=["POST"])
def new_event():
    name = request.form.get("name", "").strip()
    start_date = request.form.get("start_date", "").strip()
    end_date = request.form.get("end_date", "").strip()
    audience_mode = request.form.get("audience_mode", "Whole school")
    audience_classes = request.form.getlist("audience_classes")
    teacher = request.form.get("teacher", "").strip()
    errors = {}

    if not name:
        errors["name"] = "Name is required."
    if not parse_date(start_date):
        errors["start_date"] = "Start date must be DD-MM-YYYY."
    if not parse_date(end_date):
        errors["end_date"] = "End date must be DD-MM-YYYY."
    if parse_date(start_date) and parse_date(end_date) and parse_date(end_date) < parse_date(start_date):
        errors["end_date"] = "End date cannot be before start date."

    class_records = []
    if audience_mode == "Classes":
        class_records = AcademicClass.query.filter(AcademicClass.name.in_(audience_classes)).all()
        if not class_records:
            errors["audience_classes"] = "Choose at least one class."

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    db.session.add(
        Event(
            name=name,
            start_date=parse_date(start_date),
            end_date=parse_date(end_date),
            audience_mode=audience_mode if audience_mode == "Classes" else "Whole school",
            teacher=teacher,
            classes=class_records,
        )
    )
    db.session.commit()
    return events_json_or_redirect(f"{name} was added.")


@app.route("/events/<int:event_id>/edit", methods=["POST"])
def edit_event(event_id):
    event = Event.query.get(event_id)
    if event is None:
        abort(404)

    name = request.form.get("name", "").strip()
    start_date = request.form.get("start_date", "").strip()
    end_date = request.form.get("end_date", "").strip()
    audience_mode = request.form.get("audience_mode", "Whole school")
    audience_classes = request.form.getlist("audience_classes")
    teacher = request.form.get("teacher", "").strip()
    errors = {}

    if not name:
        errors["name"] = "Name is required."
    if not parse_date(start_date):
        errors["start_date"] = "Start date must be DD-MM-YYYY."
    if not parse_date(end_date):
        errors["end_date"] = "End date must be DD-MM-YYYY."
    if parse_date(start_date) and parse_date(end_date) and parse_date(end_date) < parse_date(start_date):
        errors["end_date"] = "End date cannot be before start date."

    class_records = []
    if audience_mode == "Classes":
        class_records = AcademicClass.query.filter(AcademicClass.name.in_(audience_classes)).all()
        if not class_records:
            errors["audience_classes"] = "Choose at least one class."

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    event.name = name
    event.start_date = parse_date(start_date)
    event.end_date = parse_date(end_date)
    event.audience_mode = audience_mode if audience_mode == "Classes" else "Whole school"
    event.teacher = teacher
    event.classes = class_records
    db.session.commit()
    return events_json_or_redirect(f"{name} was updated.")


@app.route("/events/<int:event_id>/delete", methods=["POST"])
def delete_event(event_id):
    event = Event.query.get(event_id)
    if event:
        name = event.name
        db.session.delete(event)
        db.session.commit()
        flash(f"{name} was removed.", "success")
    return redirect(events_redirect())


@app.route("/attendance")
def attendance():
    class_id = request.args.get("class_id", type=int)
    view = request.args.get("view", "classes" if not class_id else "class")
    search_query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "date_desc")
    all_records = attendance_records()
    class_records = academic_class_records()
    # Count every historical Class attendance sheet, including records created
    # before the class-first Attendance page existed. Match by class_id first,
    # then by the stored class name for older records without a class_id.
    for class_record in class_records:
        class_record["attendance_records_count"] = sum(
            1 for r in all_records
            if r.get("attendance_type") == "Class"
            and (r.get("class_id") == class_record["id"] or r.get("class_name") == class_record["name"])
        )

    selected_class = AcademicClass.query.get(class_id) if class_id else None
    students = []
    if selected_class:
        view = "class"
        records = [
            r for r in all_records
            if r.get("attendance_type") == "Class"
            and (r.get("class_id") == selected_class.id or r.get("class_name") == selected_class.name)
        ]
        students = get_class_students(selected_class.name)
    elif view == "records":
        records = all_records
    else:
        records = []

    if search_query:
        query = search_query.lower()
        records = [
            r for r in records
            if query in r["date"].lower()
            or query in r["attendance_type"].lower()
            or query in r["session"].lower()
            or query in r["entity"].lower()
        ]

    if sort == "type":
        records.sort(key=lambda r: (r["attendance_type"].lower(), r["entity"].lower()))
    elif sort == "entity":
        records.sort(key=lambda r: (r["entity"].lower(), r["date"]))
    else:
        sort = "date_desc"
        records.sort(key=lambda r: parse_created_on(r["date"]), reverse=True)

    class_records.sort(key=lambda r: r["name"].lower())

    if not selected_class and view != "records":
        total_count = len(class_records)
        class_rows, pagination = paginate(class_records)
    else:
        total_count = len(records)
        records, pagination = paginate(records)
        class_rows = class_records

    context = base_context("attendance")
    context.update(
        {
            "records": records,
            "search_query": search_query,
            "sort": sort,
            # `classes` stays the full, unpaginated list — it also feeds the
            # "Record attendance" modal's class dropdown, which must always
            # offer every class regardless of which page of the class table
            # is showing. `class_rows` is what the class-list table itself
            # paginates through.
            "classes": class_records,
            "class_rows": class_rows,
            "students": students,
            "selected_class": selected_class,
            "class_id": class_id,
            "subjects": all_subjects(),
            "attendance_types": ATTENDANCE_TYPES,
            "attendance_statuses": ATTENDANCE_STATUSES,
            "pagination": pagination,
            "total_count": total_count,
            "sort_options": [
                {"value": "date_desc", "label": "Date"},
                {"value": "type", "label": "Type"},
                {"value": "entity", "label": "Entity"},
            ],
        }
    )
    return render_template("attendance.html", **context)


@app.route("/attendance/new", methods=["POST"])
def new_attendance():
    attendance_date = request.form.get("date", "").strip()
    attendance_type = request.form.get("attendance_type", "").strip()
    session_label = request.form.get("session", "").strip()
    class_name = request.form.get("class_name", "").strip()
    class_id = request.form.get("class_id", type=int)
    subject_id = request.form.get("subject_id", "").strip()
    event_name = request.form.get("event_name", "").strip()
    errors = {}

    if not attendance_date:
        errors["date"] = "Date is required."
    if attendance_type not in ATTENDANCE_TYPES:
        errors["attendance_type"] = "Type is required."
    if not session_label:
        errors["session"] = "Session is required."

    entity = ""
    academic_class = None
    subject = None
    if attendance_type == "Class":
        academic_class = AcademicClass.query.get(class_id) if class_id else (AcademicClass.query.filter_by(name=class_name).first() if class_name else None)
        if academic_class:
            entity = academic_class.name
        else:
            errors["class_name"] = "Class is required."
    elif attendance_type == "Subject":
        subject = Subject.query.get(int(subject_id)) if subject_id.isdigit() else None
        if subject:
            entity = subject.name
            academic_class = subject.academic_class
        else:
            errors["subject_id"] = "Subject is required."
    elif attendance_type == "Event":
        entity = event_name
        if not event_name:
            errors["event_name"] = "Event is required."

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    db.session.add(
        AttendanceRecord(
            date=parse_seed_date(attendance_date),
            attendance_type=attendance_type,
            session=session_label,
            entity=entity,
            academic_class=academic_class,
            subject=subject,
        )
    )
    db.session.commit()
    # Stay on the class/records view the sheet was created from (instead of
    # bouncing back to the All Classes list) so it can be opened right away
    # to edit the marks.
    if academic_class:
        target = url_for("attendance", class_id=academic_class.id)
    else:
        target = url_for("attendance", view="records")
    return attendance_json_or_redirect(f"{entity} attendance was created.", redirect_url=target)


@app.route("/attendance/<int:attendance_id>/marks", methods=["POST"])
def update_attendance_marks(attendance_id):
    record = AttendanceRecord.query.get(attendance_id)
    if record is None:
        abort(404)

    record_dict = attendance_record_dict(record)
    AttendanceMark.query.filter_by(attendance_record_id=attendance_id).delete()
    for student in attendance_students(record_dict):
        status = request.form.get(f"status_{student['id']}", "").strip()
        time_value = request.form.get(f"time_{student['id']}", "").strip()
        if status:
            db.session.add(
                AttendanceMark(
                    attendance_record_id=attendance_id,
                    student_id=student["id"],
                    status=status,
                    time=time_value,
                )
            )
    db.session.commit()
    if record.academic_class:
        target = url_for("attendance", class_id=record.academic_class.id)
    else:
        target = url_for("attendance", view="records")
    return attendance_json_or_redirect(f"{record_dict['entity']} attendance was saved.", redirect_url=target)


@app.route("/attendance/<int:attendance_id>/delete", methods=["POST"])
def delete_attendance(attendance_id):
    record = AttendanceRecord.query.get(attendance_id)
    if record:
        entity = record.entity
        AttendanceMark.query.filter_by(attendance_record_id=attendance_id).delete()
        db.session.delete(record)
        db.session.commit()
        flash(f"{entity} attendance was removed.", "success")
    return redirect(attendance_redirect())


# --- Timetable ---

def timetable_json_or_redirect(redirect_url, message):
    flash(message, "success")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


@app.route("/timetable")
def timetable():
    tab = request.args.get("tab", "classes")
    if tab not in ("classes", "duty", "gate"):
        tab = "classes"

    context = base_context("timetable")
    context.update({"active_tab": tab})

    if tab == "duty":
        duty_shifts = DutyShift.query.order_by(DutyShift.sort_order).all()
        context.update({"duty_shifts": duty_shifts, "duty_days": TIMETABLE_DAYS, "duty_rota": duty_rota_map()})
    elif tab == "gate":
        context.update({"gate_days": TIMETABLE_DAYS, "gate_weeks": gate_weeks_context()})
    else:
        boards = [
            {"id": b.id, "name": b.name, "classes": b.classes, "created_on": format_display_date(b.created_on), "layout": b.layout,
             "period_count": len(b.periods)}
            for b in TimetableBoard.query.order_by(TimetableBoard.id).all()
        ]
        boards.sort(key=lambda b: b["name"].lower())
        total_count = len(boards)
        page_boards, pagination = paginate(boards)
        context.update({"boards": page_boards, "pagination": pagination, "total_count": total_count, "classes": all_academic_classes()})

    return render_template("timetable.html", **context)


@app.route("/timetable/duty/<day>/<shift_id>/save", methods=["POST"])
def save_duty_entry(day, shift_id):
    if day not in TIMETABLE_DAYS or not DutyShift.query.get(shift_id):
        abort(404)
    names = [n.strip() for n in request.form.get("names", "").split(",") if n.strip()]
    set_duty_entry(day, shift_id, names)
    redirect_url = url_for("timetable", tab="duty")
    return timetable_json_or_redirect(redirect_url, f"{day} duty updated.")


@app.route("/timetable/gate/<int:week_id>/<day>/save", methods=["POST"])
def save_gate_entry(week_id, day):
    if day not in TIMETABLE_DAYS or not GatePickupWeek.query.get(week_id):
        abort(404)
    name = request.form.get("name", "").strip()
    set_gate_entry(week_id, day, name)
    redirect_url = url_for("timetable", tab="gate")
    return timetable_json_or_redirect(redirect_url, "Gate rota updated.")


@app.route("/timetable/gate/weeks/new", methods=["POST"])
def new_gate_week():
    label = request.form.get("label", "").strip()
    date_range = request.form.get("date_range", "").strip()
    if not label:
        flash("Give the new week a label, e.g. WK14.", "error")
        return redirect(url_for("timetable", tab="gate"))
    db.session.add(GatePickupWeek(label=label, date_range=date_range))
    db.session.commit()
    return timetable_json_or_redirect(url_for("timetable", tab="gate"), f"{label} added.")


@app.route("/timetable/gate/weeks/<int:week_id>/edit", methods=["POST"])
def edit_gate_week(week_id):
    week = GatePickupWeek.query.get(week_id)
    if week is None:
        abort(404)
    label = request.form.get("label", "").strip()
    if not label:
        flash("A week needs a label.", "error")
        return redirect(url_for("timetable", tab="gate"))
    week.label = label
    week.date_range = request.form.get("date_range", "").strip()
    db.session.commit()
    return timetable_json_or_redirect(url_for("timetable", tab="gate"), f"{label} updated.")


@app.route("/timetable/gate/weeks/<int:week_id>/delete", methods=["POST"])
def delete_gate_week(week_id):
    week = GatePickupWeek.query.get(week_id)
    if week:
        db.session.delete(week)
        db.session.commit()
        flash(f"{week.label} was removed.", "success")
    return redirect(url_for("timetable", tab="gate"))


@app.route("/timetable/duty/shifts/<shift_id>/edit", methods=["POST"])
def edit_duty_shift(shift_id):
    shift = DutyShift.query.get(shift_id)
    if shift is None:
        abort(404)
    label = request.form.get("label", "").strip()
    time_range = request.form.get("time", "").strip()
    if not label:
        flash("A shift needs a label.", "error")
        return redirect(url_for("timetable", tab="duty"))
    shift.label = label
    shift.time = time_range
    db.session.commit()
    return timetable_json_or_redirect(url_for("timetable", tab="duty"), f"{label} updated.")


@app.route("/timetable/duty/print")
def print_duty_rota():
    context = base_context("timetable")
    duty_shifts = DutyShift.query.order_by(DutyShift.sort_order).all()
    context.update({"duty_shifts": duty_shifts, "duty_days": TIMETABLE_DAYS, "duty_rota": duty_rota_map()})
    return render_template("timetable_duty_print.html", **context)


@app.route("/timetable/gate/print")
def print_gate_rota():
    context = base_context("timetable")
    context.update({"gate_days": TIMETABLE_DAYS, "gate_weeks": gate_weeks_context()})
    return render_template("timetable_gate_print.html", **context)


@app.route("/timetable/new", methods=["POST"])
def new_timetable_board():
    name = request.form.get("name", "").strip()
    class_names = request.form.getlist("classes")
    errors = {}
    if not name:
        errors["name"] = "Give this timetable a name."
    if not class_names:
        errors["classes"] = "Pick at least one class."

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if errors:
        if wants_json:
            return jsonify({"success": False, "errors": errors}), 400
        flash(list(errors.values())[0], "error")
        return redirect(url_for("timetable"))

    class_records = AcademicClass.query.filter(AcademicClass.name.in_(class_names)).all()
    board = TimetableBoard(name=name, layout="class_rows", created_on=date.today(), class_records=class_records)
    db.session.add(board)
    db.session.flush()  # assigns board.id, needed for the default period below
    db.session.add(TimetablePeriod(board=board, start="8:00", end="9:00", label="", is_special=False, sort_order=0))
    db.session.commit()

    redirect_url = url_for("timetable_board", board_id=board.id)
    if wants_json:
        return jsonify({"success": True, "redirect": redirect_url})
    flash(f"{name} was created.", "success")
    return redirect(redirect_url)


@app.route("/timetable/<int:board_id>/edit", methods=["POST"])
def edit_timetable_board(board_id):
    board = find_timetable(board_id)
    if not board:
        abort(404)

    name = request.form.get("name", "").strip()
    class_names = request.form.getlist("classes")
    if not name:
        flash("Give this timetable a name.", "error")
        return redirect(url_for("timetable"))
    if not class_names:
        flash("Pick at least one class.", "error")
        return redirect(url_for("timetable"))

    class_records = AcademicClass.query.filter(AcademicClass.name.in_(class_names)).all()
    kept_class_ids = {c.id for c in class_records}
    TimetableEntry.query.filter(
        TimetableEntry.board_id == board_id, ~TimetableEntry.class_id.in_(kept_class_ids)
    ).delete(synchronize_session=False)

    board.name = name
    board.class_records = class_records
    db.session.commit()
    flash(f"{name} was updated.", "success")
    return redirect(url_for("timetable"))


@app.route("/timetable/<int:board_id>/delete", methods=["POST"])
def delete_timetable_board(board_id):
    board = find_timetable(board_id)
    if board:
        name = board.name
        db.session.delete(board)
        db.session.commit()
        flash(f"{name} was deleted.", "success")
    return redirect(url_for("timetable"))


@app.route("/timetable/<int:board_id>")
def timetable_board(board_id):
    board = find_timetable(board_id)
    if not board:
        abort(404)
    context = base_context("timetable")
    context.update(
        {
            "board": board,
            "periods": timetable_periods(board_id),
            "grid": build_timetable_grid(board),
            "legend": board.legend_entries,
            "days": TIMETABLE_DAYS,
            "all_classes": all_academic_classes(),
            "teachers": timetable_teachers(),
        }
    )
    return render_template("timetable_board.html", **context)


@app.route("/timetable/<int:board_id>/periods/new", methods=["POST"])
def new_timetable_period(board_id):
    board = find_timetable(board_id)
    if not board:
        abort(404)
    start = request.form.get("start", "").strip()
    end = request.form.get("end", "").strip()
    label = request.form.get("label", "").strip()
    is_special = request.form.get("is_special") == "on"

    errors = {}
    if not start:
        errors["start"] = "Start time is required."
    if not end:
        errors["end"] = "End time is required."
    if is_special and not label:
        errors["label"] = "Give this special period a label (e.g. Break, Lunch, Assembly)."

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if errors:
        if wants_json:
            return jsonify({"success": False, "errors": errors}), 400
        flash(list(errors.values())[0], "error")
        return redirect(url_for("timetable_board", board_id=board_id))

    next_sort_order = len(timetable_periods(board_id))
    db.session.add(
        TimetablePeriod(board_id=board_id, start=start, end=end, label=label, is_special=is_special, sort_order=next_sort_order)
    )
    db.session.commit()

    redirect_url = url_for("timetable_board", board_id=board_id)
    if wants_json:
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


@app.route("/timetable/<int:board_id>/periods/<int:period_id>/delete", methods=["POST"])
def delete_timetable_period(board_id, period_id):
    period = TimetablePeriod.query.filter_by(id=period_id, board_id=board_id).first()
    if period:
        TimetableEntry.query.filter_by(board_id=board_id, period_id=period_id).delete()
        db.session.delete(period)
        db.session.commit()
    return redirect(url_for("timetable_board", board_id=board_id))


@app.route("/timetable/<int:board_id>/periods/<int:period_id>/move", methods=["POST"])
def move_timetable_period(board_id, period_id):
    direction = request.form.get("direction")
    periods = timetable_periods(board_id)
    index = next((i for i, p in enumerate(periods) if p.id == period_id), None)
    if index is not None:
        target = index - 1 if direction == "up" else index + 1
        if 0 <= target < len(periods):
            periods[index].sort_order, periods[target].sort_order = periods[target].sort_order, periods[index].sort_order
            db.session.commit()
    return redirect(url_for("timetable_board", board_id=board_id))


@app.route("/timetable/<int:board_id>/cell", methods=["POST"])
def save_timetable_cell(board_id):
    board = find_timetable(board_id)
    if not board:
        abort(404)
    day = request.form.get("day", "")
    period_id = request.form.get("period_id", type=int)
    class_name = request.form.get("class_name", "")
    subject = request.form.get("subject", "").strip().upper()
    teacher = request.form.get("teacher", "").strip()

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if day not in TIMETABLE_DAYS or period_id is None or class_name not in board.classes:
        if wants_json:
            return jsonify({"success": False, "errors": {"_global": "That cell could not be found."}}), 400
        abort(404)

    set_timetable_entry(board_id, day, period_id, class_name, subject, teacher)

    redirect_url = url_for("timetable_board", board_id=board_id)
    if wants_json:
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


@app.route("/timetable/<int:board_id>/legend/new", methods=["POST"])
def new_timetable_legend_entry(board_id):
    board = find_timetable(board_id)
    if not board:
        abort(404)
    code = request.form.get("code", "").strip().upper()
    name = request.form.get("name", "").strip()

    errors = {}
    if not code:
        errors["code"] = "Enter the initials used on the grid (e.g. AA)."
    if not name:
        errors["name"] = "Enter the teacher's full name."

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if errors:
        if wants_json:
            return jsonify({"success": False, "errors": errors}), 400
        flash(list(errors.values())[0], "error")
        return redirect(url_for("timetable_board", board_id=board_id))

    TimetableLegendEntry.query.filter_by(board_id=board_id, code=code).delete()
    db.session.add(TimetableLegendEntry(board_id=board_id, code=code, name=name))
    db.session.commit()

    redirect_url = url_for("timetable_board", board_id=board_id)
    if wants_json:
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)


@app.route("/timetable/<int:board_id>/legend/<code>/delete", methods=["POST"])
def delete_timetable_legend_entry(board_id, code):
    TimetableLegendEntry.query.filter_by(board_id=board_id, code=code).delete()
    db.session.commit()
    return redirect(url_for("timetable_board", board_id=board_id))


@app.route("/timetable/<int:board_id>/print")
def print_timetable_board(board_id):
    board = find_timetable(board_id)
    if not board:
        abort(404)
    context = base_context("timetable")
    context.update(
        {
            "board": board,
            "periods": timetable_periods(board_id),
            "grid": build_timetable_grid(board),
            "legend": board.legend_entries,
            "school_info": school_info_dict(get_school()),
        }
    )
    return render_template("timetable_print.html", **context)
# ===== PYTHONANYWHERE / GIT DEPLOYMENT DATABASE BOOTSTRAP =====
# Version 9 deliberately does not use Alembic/Flask-Migrate.  The database is
# created from the current SQLAlchemy models on first start, which prevents
# old demo migrations from breaking a fresh deployment.
def _initialize_fresh_database():
    with app.app_context():
        try:
            db.create_all()

            # Keep the new installation usable while leaving all school data
            # (students, classes, marks, attendance, reports, etc.) empty.
            school = School.query.first()
            if not school:
                school = School(
                    name="School",
                    type="Primary School",
                    address="",
                    phone="",
                    email="",
                    website="",
                    reg_no="",
                    logo_path="",
                )
                db.session.add(school)

            admin = Staff.query.filter_by(email="admin@school.com").first()
            if not admin:
                admin = Staff(
                    name="Admin",
                    email="admin@school.com",
                    phone="",
                    role="admin",
                    account_created=True,
                    has_logged_in=False,
                    created_on=date.today(),
                    password_hash=generate_password_hash("support"),
                    must_change_password=False,
                    is_active=True,
                    theme="light",
                )
                db.session.add(admin)

            db.session.commit()
            print("[STARTUP] Version 9 database ready (fresh schema; no demo data).")
        except Exception as exc:
            db.session.rollback()
            print(f"[STARTUP] Database initialization failed: {exc}")


_initialize_fresh_database()

if __name__ == "__main__":
    app.run(debug=True)
