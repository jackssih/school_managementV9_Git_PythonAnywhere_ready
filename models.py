from datetime import date, datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class School(db.Model, TimestampMixin):
    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    type: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    website: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    reg_no: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    logo_path: Mapped[str] = mapped_column(String(260), default="", nullable=False)
    # The logo image itself, stored in the database rather than on local disk —
    # Render's free web service filesystem is wiped on every restart/redeploy,
    # so anything saved only to static/ is lost the moment the instance sleeps.
    # logo_path is kept for the couple of images shipped inside the repo (git
    # survives restarts); logo_data takes over once someone uploads their own.
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    logo_mimetype: Mapped[str] = mapped_column(String(80), default="", nullable=False)


class Term(db.Model, TimestampMixin):
    __tablename__ = "terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Staff(db.Model, TimestampMixin):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    phone: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(40), default="teacher", nullable=False)
    photo_path: Mapped[str] = mapped_column(String(260), default="", nullable=False)
    signature_path: Mapped[str] = mapped_column(String(260), default="", nullable=False)
    # Same database-backed storage as School.logo_data, and for the same reason
    # — see the comment there. photo_path/signature_path are kept only for the
    # sample images already committed to the repo.
    photo_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    photo_mimetype: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    signature_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    signature_mimetype: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    account_created: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    has_logged_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_on: Mapped[date] = mapped_column(Date, nullable=False)

    # --- Login & access control ---
    #
    # password_hash is set the moment an account is created (Settings > Users,
    # or the "New staff" form) with a random temporary password shown once to
    # whoever created it, so it can be relayed to the person's registered
    # email. must_change_password forces them onto the "set a new password"
    # screen the moment they first sign in. is_active is the admin's kill
    # switch for an account without deleting the staff record itself.
    #
    # role drives what the account can reach: "admin" gets the whole system,
    # anything else ("teacher") is limited to student-facing areas (Students,
    # Grades, Attendance, Reports) — see ADMIN_ONLY_ENDPOINTS in app.py.
    password_hash: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    theme: Mapped[str] = mapped_column(String(10), default="light", nullable=False)

    # Plaintext copy of the password last issued *by an admin* (account creation or a
    # password reset), kept only so an admin can re-open Settings > Users and read it
    # back without generating a new one. Cleared the moment the person sets their own
    # password (see set_staff_password / change_password), so nothing is retained once
    # the account is no longer using an admin-issued password.
    temp_password_plain: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    classes: Mapped[list["AcademicClass"]] = relationship(back_populates="class_teacher")
    subjects: Mapped[list["Subject"]] = relationship(back_populates="teacher")


class Student(db.Model, TimestampMixin):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    registration_number: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    gender: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    lin: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    current_class_name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    created_on: Mapped[date] = mapped_column(Date, nullable=False)


class AcademicClass(db.Model, TimestampMixin):
    __tablename__ = "academic_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    level: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    stream: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    class_teacher_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))

    class_teacher: Mapped[Staff | None] = relationship(back_populates="classes")
    subjects: Mapped[list["Subject"]] = relationship(back_populates="academic_class", cascade="all, delete-orphan")


class Subject(db.Model, TimestampMixin):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("class_id", "name", name="uq_subject_class_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("academic_classes.id"), nullable=False)
    maximum_mark: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_compulsory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))

    academic_class: Mapped[AcademicClass] = relationship(back_populates="subjects")
    teacher: Mapped[Staff | None] = relationship(back_populates="subjects")


enrollment_students = Table(
    "enrollment_students",
    Base.metadata,
    Column("enrollment_id", ForeignKey("enrollments.id"), primary_key=True),
    Column("student_id", ForeignKey("students.id"), primary_key=True),
)


class Enrollment(db.Model, TimestampMixin):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("academic_classes.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="Enrolled", nullable=False)

    academic_class: Mapped[AcademicClass] = relationship()
    students: Mapped[list["Student"]] = relationship(secondary=enrollment_students)


class PromotionDecision(db.Model, TimestampMixin):
    __tablename__ = "promotion_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False, unique=True)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)

    student: Mapped[Student] = relationship()


class PromotionRun(db.Model, TimestampMixin):
    """One 'move everyone up to the next class' action, applied at the end
    of a school year. Kept as its own row (with a PromotionRunEntry per
    student) rather than just mutating Student.current_class_name in
    place, so the whole batch — or any single student in it — can be
    undone later without having to guess what changed."""

    __tablename__ = "promotion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    # "Applied" while the move is in effect, "Reverted" once undone as a whole.
    status: Mapped[str] = mapped_column(String(20), default="Applied", nullable=False)

    entries: Mapped[list["PromotionRunEntry"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="PromotionRunEntry.id"
    )


class PromotionRunEntry(db.Model, TimestampMixin):
    """One student's outcome within a PromotionRun: which class they moved
    from/to (if any), what kind of outcome it was, and whether that one
    line has since been undone on its own — independent of whether the
    rest of the run has been."""

    __tablename__ = "promotion_run_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("promotion_runs.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    from_class_name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    to_class_name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    # Moved | Stayed | Completed | Discontinued | Unresolved
    outcome: Mapped[str] = mapped_column(String(20), default="Moved", nullable=False)
    reverted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run: Mapped[PromotionRun] = relationship(back_populates="entries")
    student: Mapped[Student] = relationship()


class Assessment(db.Model, TimestampMixin):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    assessment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    maximum: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    subject: Mapped[Subject] = relationship()


class AssessmentResult(db.Model, TimestampMixin):
    __tablename__ = "assessment_results"
    __table_args__ = (UniqueConstraint("assessment_id", "student_id", name="uq_assessment_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    mark: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    aggregate: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    grade: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    remark: Mapped[str] = mapped_column(Text, default="", nullable=False)

    assessment: Mapped[Assessment] = relationship()
    student: Mapped[Student] = relationship()


class ReportComment(db.Model, TimestampMixin):
    __tablename__ = "report_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    comment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    teacher: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    # Which printed report this comment belongs to: the full "End of term"
    # report card, or the short "Mini report" slip class teachers also fill
    # in for the Beginning-of-term and Mid-term checkpoints.
    report_stage: Mapped[str] = mapped_column(String(60), default="End of term", nullable=False)

    student: Mapped[Student] = relationship()


report_batch_students = Table(
    "report_batch_students",
    Base.metadata,
    Column("report_batch_id", ForeignKey("report_batches.id"), primary_key=True),
    Column("student_id", ForeignKey("students.id"), primary_key=True),
)


class ReportBatch(db.Model, TimestampMixin):
    """A generated set of report cards for one class. Kept separate from
    PublishedReport (below) because the app treats "generate" and "publish"
    as two independent lists — a batch can be deleted without touching
    anything already published from it, and vice versa."""

    __tablename__ = "report_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("academic_classes.id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(60), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="Pending", nullable=False)
    report_scope: Mapped[str | None] = mapped_column(String(40), nullable=True)

    academic_class: Mapped[AcademicClass] = relationship()
    students: Mapped[list["Student"]] = relationship(secondary=report_batch_students)


published_report_students = Table(
    "published_report_students",
    Base.metadata,
    Column("published_report_id", ForeignKey("published_reports.id"), primary_key=True),
    Column("student_id", ForeignKey("students.id"), primary_key=True),
)


class PublishedReport(db.Model, TimestampMixin):
    """A standalone snapshot created when a ReportBatch is published — its
    own row, own student list, independent of the batch it came from."""

    __tablename__ = "published_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("academic_classes.id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(60), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    publish_here: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    publish_sms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    publish_email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email: Mapped[str] = mapped_column(String(160), default="", nullable=False)

    academic_class: Mapped[AcademicClass] = relationship()
    students: Mapped[list["Student"]] = relationship(secondary=published_report_students)

class AttendanceRecord(db.Model, TimestampMixin):
    """One attendance sheet — a Class register for a day, a Subject period,
    or an Event. class_id/subject_id are set depending on attendance_type;
    Event records leave both null since they aren't tied to a class."""

    __tablename__ = "attendance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    attendance_type: Mapped[str] = mapped_column(String(20), nullable=False)
    session: Mapped[str] = mapped_column(String(80), nullable=False)
    entity: Mapped[str] = mapped_column(String(160), nullable=False)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("academic_classes.id"), nullable=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)

    academic_class: Mapped[AcademicClass | None] = relationship()
    subject: Mapped[Subject | None] = relationship()


class AttendanceMark(db.Model, TimestampMixin):
    __tablename__ = "attendance_marks"
    __table_args__ = (UniqueConstraint("attendance_record_id", "student_id", name="uq_attendance_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attendance_record_id: Mapped[int] = mapped_column(ForeignKey("attendance_records.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    time: Mapped[str] = mapped_column(String(20), default="", nullable=False)

    attendance_record: Mapped[AttendanceRecord] = relationship()
    student: Mapped[Student] = relationship()


timetable_board_classes = Table(
    "timetable_board_classes",
    Base.metadata,
    Column("board_id", ForeignKey("timetable_boards.id"), primary_key=True),
    Column("class_id", ForeignKey("academic_classes.id"), primary_key=True),
)


class TimetableBoard(db.Model, TimestampMixin):
    """One timetable grid covering a group of classes — e.g. 'Upper Primary'."""

    __tablename__ = "timetable_boards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    layout: Mapped[str] = mapped_column(String(20), default="class_rows", nullable=False)
    created_on: Mapped[date] = mapped_column(Date, nullable=False)

    class_records: Mapped[list["AcademicClass"]] = relationship(secondary=timetable_board_classes, order_by="AcademicClass.name")
    periods: Mapped[list["TimetablePeriod"]] = relationship(
        back_populates="board", cascade="all, delete-orphan", order_by="TimetablePeriod.sort_order"
    )
    entries: Mapped[list["TimetableEntry"]] = relationship(back_populates="board", cascade="all, delete-orphan")
    legend_entries: Mapped[list["TimetableLegendEntry"]] = relationship(
        back_populates="board", cascade="all, delete-orphan", order_by="TimetableLegendEntry.code"
    )

    @property
    def classes(self):
        """Class names for this board, e.g. ['Primary 5', 'Primary 6'] — kept
        as a plain string list (not the AcademicClass objects themselves) so
        templates and grid-building code can keep treating a board's classes
        as names, same as before the database conversion."""
        return [c.name for c in self.class_records]


class TimetablePeriod(db.Model, TimestampMixin):
    """A time column shared by every day on a board. 'is_special' periods
    (Assembly/Break/Lunch) span the row instead of holding a per-class
    subject+teacher. sort_order controls left-to-right / top-to-bottom
    position and is what the move-up/move-down actions swap."""

    __tablename__ = "timetable_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("timetable_boards.id"), nullable=False)
    start: Mapped[str] = mapped_column(String(20), nullable=False)
    end: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    is_special: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    board: Mapped[TimetableBoard] = relationship(back_populates="periods")


class TimetableEntry(db.Model, TimestampMixin):
    """What's actually taught in one board/day/period/class cell."""

    __tablename__ = "timetable_entries"
    __table_args__ = (UniqueConstraint("board_id", "day", "period_id", "class_id", name="uq_timetable_cell"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("timetable_boards.id"), nullable=False)
    day: Mapped[str] = mapped_column(String(20), nullable=False)
    period_id: Mapped[int] = mapped_column(ForeignKey("timetable_periods.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("academic_classes.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))

    board: Mapped[TimetableBoard] = relationship(back_populates="entries")
    period: Mapped["TimetablePeriod"] = relationship()
    academic_class: Mapped[AcademicClass] = relationship()
    teacher: Mapped[Staff | None] = relationship()


class TimetableLegendEntry(db.Model, TimestampMixin):
    """The teacher-code -> full-name key shown at the bottom of a printed grid."""

    __tablename__ = "timetable_legend_entries"
    __table_args__ = (UniqueConstraint("board_id", "code", name="uq_legend_board_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("timetable_boards.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)

    board: Mapped[TimetableBoard] = relationship(back_populates="legend_entries")


class DutyShift(db.Model, TimestampMixin):
    """A fixed daily duty slot (Morning, Home time (Lower), ...). The id is
    the short string key already used throughout the app/URLs (e.g. 'morning')
    rather than a surrogate integer, so no route or template needs to change."""

    __tablename__ = "duty_shifts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    time: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DutyEntry(db.Model, TimestampMixin):
    """One staff member covering one shift on one day. A shift/day can have
    several entries (e.g. three staff on 'home_upper' on Monday); staff_name
    is stored as free text (matching the source rota, e.g. 'Tr. Emma') rather
    than a Staff foreign key, since duty-rota names don't consistently match
    real Staff records."""

    __tablename__ = "duty_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(20), nullable=False)
    shift_id: Mapped[str] = mapped_column(ForeignKey("duty_shifts.id"), nullable=False)
    staff_name: Mapped[str] = mapped_column(String(160), nullable=False)

    shift: Mapped[DutyShift] = relationship()


class GatePickupWeek(db.Model, TimestampMixin):
    __tablename__ = "gate_pickup_weeks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    date_range: Mapped[str] = mapped_column(String(80), default="", nullable=False)

    entries: Mapped[list["GatePickupEntry"]] = relationship(back_populates="week", cascade="all, delete-orphan")


class GatePickupEntry(db.Model, TimestampMixin):
    """One staff name covering the gate/pickup rota for one day of one week."""

    __tablename__ = "gate_pickup_entries"
    __table_args__ = (UniqueConstraint("week_id", "day", name="uq_gate_week_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_id: Mapped[int] = mapped_column(ForeignKey("gate_pickup_weeks.id"), nullable=False)
    day: Mapped[str] = mapped_column(String(20), nullable=False)
    staff_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)

    week: Mapped["GatePickupWeek"] = relationship(back_populates="entries")


event_classes = Table(
    "event_classes",
    Base.metadata,
    Column("event_id", ForeignKey("events.id"), primary_key=True),
    Column("class_id", ForeignKey("academic_classes.id"), primary_key=True),
)


class Event(db.Model, TimestampMixin):
    """audience_mode is "Whole school" or "Classes". When it's "Classes",
    the actual classes live in the event_classes join table and the
    display string ("Primary 3, Primary 5") is derived at read time —
    never stored — so renaming a class is instantly reflected everywhere
    an event mentions it.

    teacher is a plain name string rather than a Staff FK: the seed data
    references a "Taaka Beatrice" who isn't a row in the Staff table at
    all (a head teacher, tracked the same freeform way ReportComment.teacher
    already is), so a strict FK would reject that value."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    audience_mode: Mapped[str] = mapped_column(String(20), default="Whole school", nullable=False)
    teacher: Mapped[str] = mapped_column(String(160), default="", nullable=False)

    classes: Mapped[list["AcademicClass"]] = relationship(secondary=event_classes)