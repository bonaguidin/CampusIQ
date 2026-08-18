"""Course lifecycle: PLANNED -> IN_PROGRESS -> COMPLETED (with an explicit
DROPPED exit), and its effect on GPA.

Self-contained fake Supabase client (select/insert/upsert/update/delete over
plain filters) -- the same shape test_api_v2_transcript.py's FakeQuery uses,
but generic rather than RLS-scoped, since lifecycle.py's own .eq("student_id",
...) filters are exactly what is under test here.
"""

from datetime import date, timedelta

import pytest

from GradusIQ_career.academics.gpa import CourseRecord, GradeMapRow, Institution, compute_both
from GradusIQ_career.planning.lifecycle import (
    ACTIVATION_WINDOW_DAYS,
    CourseNotEditable,
    LifecycleError,
    add_course_respecting_activation,
    edit_in_progress_course,
    finalize_course_grade,
    is_activated,
    promote_due_planned_courses,
    unresolved_prior_courses,
)

STUDENT = "student-1"
TAMU = "tamu"


# ── fake client ──────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table):
        self.table = table
        self.filters = []
        self.op = None
        self.payload = None
        self.on_conflict = None
        self.ignore_duplicates = False

    def select(self, *_a, **_k):
        self.op = self.op or "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def upsert(self, payload, *, ignore_duplicates=False, on_conflict="", **_k):
        self.op = "upsert"
        self.payload = payload
        self.ignore_duplicates = ignore_duplicates
        self.on_conflict = on_conflict
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def _matches(self, row):
        for _, column, value in self.filters:
            if row.get(column) != value:
                return False
        return True

    def execute(self):
        rows = self.table.rows
        if self.op in (None, "select"):
            return FakeResponse([dict(r) for r in rows if self._matches(r)])

        if self.op == "insert":
            row = dict(self.payload)
            row.setdefault("id", f"{self.table.name}-{len(rows) + 1}")
            rows.append(row)
            return FakeResponse([dict(row)])

        if self.op == "upsert":
            columns = tuple(c.strip() for c in (self.on_conflict or "").split(",") if c.strip())
            key = tuple(self.payload.get(c) for c in columns)
            for existing in rows:
                if tuple(existing.get(c) for c in columns) == key:
                    assert self.ignore_duplicates
                    return FakeResponse([])
            row = dict(self.payload)
            row.setdefault("id", f"{self.table.name}-{len(rows) + 1}")
            rows.append(row)
            return FakeResponse([dict(row)])

        if self.op == "update":
            updated = []
            for row in rows:
                if self._matches(row):
                    row.update(self.payload)
                    updated.append(dict(row))
            return FakeResponse(updated)

        if self.op == "delete":
            matched = [row for row in rows if self._matches(row)]
            for row in matched:
                rows.remove(row)
            return FakeResponse(matched)

        raise AssertionError(f"unsupported op {self.op}")


class FakeTable:
    def __init__(self, name, rows):
        self.name = name
        self.rows = list(rows)


class FakeClient:
    def __init__(self, **tables):
        self.tables = {name: FakeTable(name, rows) for name, rows in tables.items()}

    def table(self, name):
        self.tables.setdefault(name, FakeTable(name, []))
        return FakeQuery(self.tables[name])


# ── fixtures ─────────────────────────────────────────────────────────────────


def make_client(*, terms=(), dates=(), planned=(), courses=(), grade_map=()):
    return FakeClient(
        academic_terms=list(terms),
        academic_term_dates=list(dates),
        planned_courses=list(planned),
        course_records=list(courses),
        grade_point_map=list(grade_map),
    )


TAMU_GRADE_MAP = [
    {"institution_id": TAMU, "letter": "A", "points": 4.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    {"institution_id": TAMU, "letter": "B", "points": 3.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    {"institution_id": TAMU, "letter": "C", "points": 2.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    {"institution_id": TAMU, "letter": "F", "points": 0.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    {"institution_id": TAMU, "letter": "W", "points": None, "counts_toward_gpa": False, "counts_toward_credit": False},
]


# ── activation ────────────────────────────────────────────────────────────────


def test_is_activated_exactly_at_window_boundary():
    start = date(2027, 1, 19)  # a Spring term starting mid-January
    activation = start - timedelta(days=ACTIVATION_WINDOW_DAYS)
    assert not is_activated(start, activation - timedelta(days=1))
    assert is_activated(start, activation)
    assert is_activated(start, start)


def test_is_activated_none_start_never_activates():
    assert not is_activated(None, date(2099, 1, 1))


# ── promotion ─────────────────────────────────────────────────────────────────


def test_future_spring_course_remains_planned_before_activation():
    client = make_client(
        terms=[{"id": "term-spring27", "student_id": STUDENT, "institution_id": TAMU, "year": 2027, "season": "Spring"}],
        dates=[{"institution_id": TAMU, "year": 2027, "season": "Spring", "start_date": "2027-01-19", "end_date": "2027-05-06"}],
        planned=[{"id": "plan-1", "student_id": STUDENT, "term_id": "term-spring27", "course_code": "CSCE 313"}],
    )
    today = date(2026, 8, 17)  # well before the Dec 20 activation date
    promoted = promote_due_planned_courses(client, STUDENT, TAMU, today)
    assert promoted == []
    assert len(client.tables["planned_courses"].rows) == 1
    assert client.tables["course_records"].rows == []


def test_spring_course_promotes_inside_pre_term_window():
    client = make_client(
        terms=[{"id": "term-spring27", "student_id": STUDENT, "institution_id": TAMU, "year": 2027, "season": "Spring"}],
        dates=[{"institution_id": TAMU, "year": 2027, "season": "Spring", "start_date": "2027-01-19", "end_date": "2027-05-06"}],
        planned=[{"id": "plan-1", "student_id": STUDENT, "term_id": "term-spring27", "course_code": "CSCE 313"}],
    )
    today = date(2026, 12, 20)  # inside the 30-day pre-Spring window
    promoted = promote_due_planned_courses(client, STUDENT, TAMU, today)
    assert [p["course_code"] for p in promoted] == ["CSCE 313"]
    assert client.tables["planned_courses"].rows == []
    [row] = client.tables["course_records"].rows
    assert row["status"] == "in_progress"
    assert row["confirmed_at"] is not None
    assert row["counts_toward_credit"] is False
    assert row["counts_toward_gpa"] is False


def test_fall_course_promotes_inside_its_own_pre_term_window():
    client = make_client(
        terms=[{"id": "term-fall26", "student_id": STUDENT, "institution_id": TAMU, "year": 2026, "season": "Fall"}],
        dates=[{"institution_id": TAMU, "year": 2026, "season": "Fall", "start_date": "2026-08-24", "end_date": "2026-12-10"}],
        planned=[{"id": "plan-1", "student_id": STUDENT, "term_id": "term-fall26", "course_code": "ECEN 214"}],
    )
    # July 25 is inside the 30-day window before Aug 24; July 24 is not.
    assert promote_due_planned_courses(client, STUDENT, TAMU, date(2026, 7, 24)) == []
    assert promote_due_planned_courses(client, STUDENT, TAMU, date(2026, 7, 25)) != []


def test_term_with_no_calendar_row_never_promotes():
    client = make_client(
        terms=[{"id": "term-x", "student_id": STUDENT, "institution_id": TAMU, "year": 2099, "season": "Fall"}],
        planned=[{"id": "plan-1", "student_id": STUDENT, "term_id": "term-x", "course_code": "CSCE 999"}],
    )
    promoted = promote_due_planned_courses(client, STUDENT, TAMU, date(2099, 8, 1))
    assert promoted == []
    assert len(client.tables["planned_courses"].rows) == 1


def test_repeated_reconciliation_does_not_duplicate_or_corrupt():
    client = make_client(
        terms=[{"id": "term-spring27", "student_id": STUDENT, "institution_id": TAMU, "year": 2027, "season": "Spring"}],
        dates=[{"institution_id": TAMU, "year": 2027, "season": "Spring", "start_date": "2027-01-19", "end_date": "2027-05-06"}],
        planned=[{"id": "plan-1", "student_id": STUDENT, "term_id": "term-spring27", "course_code": "CSCE 313"}],
    )
    today = date(2026, 12, 20)
    promote_due_planned_courses(client, STUDENT, TAMU, today)
    # Second call: nothing left in planned_courses to promote, and the
    # already-promoted course_records row must not be touched or duplicated.
    second = promote_due_planned_courses(client, STUDENT, TAMU, today)
    assert second == []
    assert len(client.tables["course_records"].rows) == 1
    third = promote_due_planned_courses(client, STUDENT, TAMU, today)
    assert third == []
    assert len(client.tables["course_records"].rows) == 1


# ── adding a course that respects activation ──────────────────────────────────


def test_add_course_before_activation_is_planned():
    client = make_client(
        dates=[{"institution_id": TAMU, "year": 2027, "season": "Spring", "start_date": "2027-01-19", "end_date": "2027-05-06"}],
    )
    result = add_course_respecting_activation(
        client, STUDENT, TAMU,
        term_id="term-spring27", year=2027, season="Spring",
        course_code="MATH 251", today=date(2026, 8, 17),
    )
    assert result["kind"] == "planned"
    assert len(client.tables["planned_courses"].rows) == 1
    assert client.tables["course_records"].rows == []


def test_add_course_after_activation_becomes_in_progress_directly():
    client = make_client(
        dates=[{"institution_id": TAMU, "year": 2027, "season": "Spring", "start_date": "2027-01-19", "end_date": "2027-05-06"}],
    )
    result = add_course_respecting_activation(
        client, STUDENT, TAMU,
        term_id="term-spring27", year=2027, season="Spring",
        course_code="MATH 251", today=date(2026, 12, 20),
    )
    assert result["kind"] == "in_progress"
    assert result["status"] == "in_progress"
    assert client.tables["planned_courses"].rows == []
    [row] = client.tables["course_records"].rows
    assert row["status"] == "in_progress"


# ── previous-term reconciliation (read-only) ──────────────────────────────────


def test_ended_term_with_unresolved_course_generates_grade_request():
    client = make_client(
        terms=[{"id": "term-fall25", "student_id": STUDENT, "institution_id": TAMU, "year": 2025, "season": "Fall", "label": "Fall 2025"}],
        dates=[{"institution_id": TAMU, "year": 2025, "season": "Fall", "start_date": "2025-08-25", "end_date": "2025-12-10"}],
        courses=[{
            "id": "cr-1", "student_id": STUDENT, "term_id": "term-fall25",
            "course_code": "CSCE 222", "status": "in_progress", "confirmed_at": "2025-08-25T00:00:00Z",
        }],
    )
    pending = unresolved_prior_courses(client, STUDENT, TAMU, today=date(2026, 1, 15))
    assert [p["course_code"] for p in pending] == ["CSCE 222"]


def test_completed_course_is_not_requested_again():
    client = make_client(
        terms=[{"id": "term-fall25", "student_id": STUDENT, "institution_id": TAMU, "year": 2025, "season": "Fall", "label": "Fall 2025"}],
        dates=[{"institution_id": TAMU, "year": 2025, "season": "Fall", "start_date": "2025-08-25", "end_date": "2025-12-10"}],
        courses=[{
            "id": "cr-1", "student_id": STUDENT, "term_id": "term-fall25",
            "course_code": "CSCE 222", "status": "completed", "confirmed_at": "2025-08-25T00:00:00Z",
        }],
    )
    assert unresolved_prior_courses(client, STUDENT, TAMU, today=date(2026, 1, 15)) == []


def test_multiple_unresolved_courses_all_appear():
    client = make_client(
        terms=[{"id": "term-fall25", "student_id": STUDENT, "institution_id": TAMU, "year": 2025, "season": "Fall", "label": "Fall 2025"}],
        dates=[{"institution_id": TAMU, "year": 2025, "season": "Fall", "start_date": "2025-08-25", "end_date": "2025-12-10"}],
        courses=[
            {"id": "cr-1", "student_id": STUDENT, "term_id": "term-fall25", "course_code": "CSCE 222", "status": "in_progress", "confirmed_at": "x"},
            {"id": "cr-2", "student_id": STUDENT, "term_id": "term-fall25", "course_code": "PHYS 207", "status": "in_progress", "confirmed_at": "x"},
        ],
    )
    pending = unresolved_prior_courses(client, STUDENT, TAMU, today=date(2026, 1, 15))
    assert {p["course_code"] for p in pending} == {"CSCE 222", "PHYS 207"}


def test_ongoing_term_in_progress_course_not_requested():
    client = make_client(
        terms=[{"id": "term-fall26", "student_id": STUDENT, "institution_id": TAMU, "year": 2026, "season": "Fall", "label": "Fall 2026"}],
        dates=[{"institution_id": TAMU, "year": 2026, "season": "Fall", "start_date": "2026-08-24", "end_date": "2026-12-10"}],
        courses=[{
            "id": "cr-1", "student_id": STUDENT, "term_id": "term-fall26",
            "course_code": "CSCE 222", "status": "in_progress", "confirmed_at": "x",
        }],
    )
    # Mid-semester: end_date has not passed yet.
    assert unresolved_prior_courses(client, STUDENT, TAMU, today=date(2026, 10, 1)) == []


# ── finalize ──────────────────────────────────────────────────────────────────


def test_finalize_transitions_to_completed_and_stores_grade():
    client = make_client(
        courses=[{"id": "cr-1", "student_id": STUDENT, "institution_id": TAMU, "status": "in_progress", "course_code": "CSCE 222"}],
        grade_map=TAMU_GRADE_MAP,
    )
    result = finalize_course_grade(client, STUDENT, "cr-1", "B")
    assert result == {"id": "cr-1", "status": "completed", "already_finalized": False}
    [row] = client.tables["course_records"].rows
    assert row["status"] == "completed"
    assert row["letter_grade"] == "B"
    assert row["counts_toward_gpa"] is True
    assert row["counts_toward_credit"] is True


def test_finalize_is_idempotent_and_does_not_double_count():
    client = make_client(
        courses=[{"id": "cr-1", "student_id": STUDENT, "institution_id": TAMU, "status": "in_progress", "course_code": "CSCE 222"}],
        grade_map=TAMU_GRADE_MAP,
    )
    first = finalize_course_grade(client, STUDENT, "cr-1", "B")
    assert first["already_finalized"] is False
    second = finalize_course_grade(client, STUDENT, "cr-1", "A")  # a resubmit with a different grade
    assert second["already_finalized"] is True
    # The second call must not have overwritten the stored grade.
    [row] = client.tables["course_records"].rows
    assert row["letter_grade"] == "B"


def test_finalize_requires_a_letter_grade():
    client = make_client(
        courses=[{"id": "cr-1", "student_id": STUDENT, "institution_id": TAMU, "status": "in_progress"}],
    )
    with pytest.raises(LifecycleError):
        finalize_course_grade(client, STUDENT, "cr-1", "")


def test_finalize_unknown_course_raises_not_editable():
    client = make_client()
    with pytest.raises(CourseNotEditable):
        finalize_course_grade(client, STUDENT, "nope", "A")


# ── editing ───────────────────────────────────────────────────────────────────


def test_planned_course_can_be_changed():
    client = make_client(
        planned=[{"id": "plan-1", "student_id": STUDENT, "course_code": "CSCE 313", "credit_hours": None}],
    )
    from GradusIQ_career.planning.planned import add_planned

    add_planned(client, STUDENT, TAMU, course_code="CSCE 314", term_id=None)
    codes = {row["course_code"] for row in client.tables["planned_courses"].rows}
    assert "CSCE 314" in codes


def test_planned_course_can_be_removed():
    client = make_client(
        planned=[{"id": "plan-1", "student_id": STUDENT, "course_code": "CSCE 313"}],
    )
    from GradusIQ_career.planning.planned import remove_planned

    assert remove_planned(client, STUDENT, "plan-1") is True
    assert client.tables["planned_courses"].rows == []


def test_in_progress_course_current_grade_can_be_edited():
    client = make_client(
        courses=[{"id": "cr-1", "student_id": STUDENT, "institution_id": TAMU, "status": "in_progress", "course_code": "CSCE 222"}],
    )
    updated = edit_in_progress_course(client, STUDENT, "cr-1", {"letter_grade": "B"})
    assert updated["letter_grade"] == "B"
    assert updated["status"] == "in_progress"


def test_in_progress_course_can_be_dropped():
    client = make_client(
        courses=[{"id": "cr-1", "student_id": STUDENT, "institution_id": TAMU, "status": "in_progress", "course_code": "CSCE 222"}],
    )
    updated = edit_in_progress_course(client, STUDENT, "cr-1", {"status": "dropped"})
    assert updated["status"] == "dropped"
    assert updated["counts_toward_gpa"] is False


def test_cannot_set_status_to_completed_through_edit_endpoint():
    client = make_client(
        courses=[{"id": "cr-1", "student_id": STUDENT, "status": "in_progress"}],
    )
    with pytest.raises(LifecycleError):
        edit_in_progress_course(client, STUDENT, "cr-1", {"status": "completed"})


def test_completed_academic_history_cannot_be_edited_through_this_path():
    client = make_client(
        courses=[{"id": "cr-1", "student_id": STUDENT, "status": "completed", "letter_grade": "A"}],
    )
    with pytest.raises(CourseNotEditable):
        edit_in_progress_course(client, STUDENT, "cr-1", {"letter_grade": "F"})
    # Unchanged.
    [row] = client.tables["course_records"].rows
    assert row["letter_grade"] == "A"


def test_dropped_course_cannot_be_edited_again_through_this_path():
    client = make_client(
        courses=[{"id": "cr-1", "student_id": STUDENT, "status": "dropped"}],
    )
    with pytest.raises(CourseNotEditable):
        edit_in_progress_course(client, STUDENT, "cr-1", {"letter_grade": "A"})


def test_edit_with_no_fields_is_a_lifecycle_error():
    client = make_client(
        courses=[{"id": "cr-1", "student_id": STUDENT, "status": "in_progress"}],
    )
    with pytest.raises(LifecycleError):
        edit_in_progress_course(client, STUDENT, "cr-1", {})


# ── GPA: official vs projected ─────────────────────────────────────────────────


TAMU_INSTITUTION = Institution(
    id=TAMU, name="TAMU", uses_plus_minus=False, transfer_grades_count_toward_gpa=False
)
TAMU_GPA_MAP = {
    "A": GradeMapRow("A", 4.0, True, True),
    "B": GradeMapRow("B", 3.0, True, True),
    "C": GradeMapRow("C", 2.0, True, True),
    "F": GradeMapRow("F", 0.0, True, True),
}


def test_current_grade_change_moves_projected_not_official_gpa():
    completed = CourseRecord(
        course_code="MATH 151", credit_hours=3, letter_grade="A", credit_type="resident",
        status="completed", institution_id=TAMU, confirmed_at="x",
    )
    in_progress_no_grade = CourseRecord(
        course_code="CSCE 222", credit_hours=3, letter_grade=None, credit_type="resident",
        status="in_progress", institution_id=TAMU, confirmed_at="x",
    )
    before = compute_both([completed, in_progress_no_grade], TAMU_INSTITUTION, TAMU_GPA_MAP)
    assert before.official.gpa == 4.0
    assert before.projected.gpa == 4.0  # no current grade entered yet -- projected == official

    in_progress_with_grade = CourseRecord(
        course_code="CSCE 222", credit_hours=3, letter_grade="B", credit_type="resident",
        status="in_progress", institution_id=TAMU, confirmed_at="x",
    )
    after = compute_both([completed, in_progress_with_grade], TAMU_INSTITUTION, TAMU_GPA_MAP)
    assert after.official.gpa == 4.0  # unchanged -- official never reads an in_progress row
    assert after.projected.gpa == 3.5  # (4*3 + 3*3) / 6


def test_finalizing_a_grade_updates_official_gpa():
    client = make_client(
        courses=[{
            "id": "cr-1", "student_id": STUDENT, "institution_id": TAMU,
            "course_code": "CSCE 222", "status": "in_progress", "credit_hours": 3,
        }],
        grade_map=TAMU_GRADE_MAP,
    )
    finalize_course_grade(client, STUDENT, "cr-1", "B")
    row = client.tables["course_records"].rows[0]
    record = CourseRecord(
        course_code=row["course_code"], credit_hours=row["credit_hours"],
        letter_grade=row["letter_grade"], credit_type="resident",
        status=row["status"], institution_id=TAMU, confirmed_at="x",
    )
    result = compute_both([record], TAMU_INSTITUTION, TAMU_GPA_MAP)
    assert result.official.gpa == 3.0
    assert result.projected.gpa == 3.0


def test_missing_current_grade_does_not_corrupt_projected_gpa():
    completed = CourseRecord(
        course_code="MATH 151", credit_hours=3, letter_grade="A", credit_type="resident",
        status="completed", institution_id=TAMU, confirmed_at="x",
    )
    in_progress_no_grade = CourseRecord(
        course_code="CSCE 222", credit_hours=3, letter_grade=None, credit_type="resident",
        status="in_progress", institution_id=TAMU, confirmed_at="x",
    )
    result = compute_both([completed, in_progress_no_grade], TAMU_INSTITUTION, TAMU_GPA_MAP)
    # The ungraded in-progress course is excluded, not treated as a zero.
    assert result.projected.gpa == 4.0
    assert result.projected.gpa_hours == 3.0


def test_dropped_course_excluded_from_both_gpa_modes():
    completed = CourseRecord(
        course_code="MATH 151", credit_hours=3, letter_grade="A", credit_type="resident",
        status="completed", institution_id=TAMU, confirmed_at="x",
    )
    dropped = CourseRecord(
        course_code="CSCE 222", credit_hours=3, letter_grade=None, credit_type="resident",
        status="dropped", institution_id=TAMU, confirmed_at="x",
    )
    result = compute_both([completed, dropped], TAMU_INSTITUTION, TAMU_GPA_MAP)
    assert result.official.gpa == 4.0
    assert result.projected.gpa == 4.0
    assert result.official.earned_hours == 3.0  # only the completed course
