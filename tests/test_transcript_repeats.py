"""Tests for repeat detection (course_records.excluded_from_gpa_by).

Covers the audit's Part 6 test list. The load-bearing one is
test_b_then_retake_excludes_nothing: it is the case that distinguishes Option B
(threshold-gated) from Option A (unconditional latest-wins), and it fails under
A. Several tests here assert that NOTHING happens, which is the whole point --
a silently deleted grade is invisible in a way an over-counted one is not.
"""

from decimal import Decimal

import pytest

from CampusIQ_career.academics.gpa import (
    CourseRecord,
    GradeMapRow,
    Institution,
    compute_gpa,
)
from CampusIQ_career.transcript import repeats
from CampusIQ_career.transcript.review import load_unconfirmed, project_row
from CampusIQ_career.transcript.store import confirm_course_rows


TAMU = "inst-tamu"
SMU = "inst-smu"
UNCLASSIFIED = "inst-unclassified"
STUDENT = "student-0001"

SMU_GRADES = [
    ("A", 4.00), ("A-", 3.70), ("B+", 3.30), ("B", 3.00), ("B-", 2.70),
    ("C+", 2.30), ("C", 2.00), ("C-", 1.70), ("D+", 1.30), ("D", 1.00),
    ("D-", 0.70), ("F", 0.00),
]
TAMU_GRADES = [("A", 4.00), ("B", 3.00), ("C", 2.00), ("D", 1.00), ("F", 0.00)]

SMU_THRESHOLD = Decimal("1.30")  # D+, per migration 20260809180000


# ── fake client ─────────────────────────────────────────────────────────────


class _Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.op = None
        self.payload = None
        self.filters = []

    def select(self, *a, **k):
        self.op = "select"
        return self

    def update(self, payload, **k):
        self.op = "update"
        self.payload = payload
        return self

    def insert(self, payload, **k):
        self.op = "insert"
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def is_(self, column, value):
        self.filters.append(("is", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, list(values)))
        return self

    def _matches(self, row):
        for kind, column, value in self.filters:
            if kind == "eq" and row.get(column) != value:
                return False
            if kind == "is":
                wanted = None if value in (None, "null") else value
                if row.get(column) is not wanted:
                    return False
            if kind == "in" and row.get(column) not in value:
                return False
        return True

    def execute(self):
        rows = self.db.tables[self.table]
        if self.op == "select":
            return _Result([dict(r) for r in rows if self._matches(r)])
        if self.op == "update":
            updated = []
            for row in rows:
                if self._matches(row):
                    row.update(self.payload)
                    updated.append(dict(row))
            return _Result(updated)
        if self.op == "insert":
            row = dict(self.payload)
            row.setdefault("id", self.db.new_id("row"))
            rows.append(row)
            return _Result([dict(row)])
        raise AssertionError(f"unsupported op {self.op}")


class FakeDB:
    def __init__(self):
        self.tables = {
            "course_records": [],
            "academic_terms": [],
            "institutions": [],
            "grade_point_map": [],
        }
        self._n = 0

    def new_id(self, prefix="id"):
        self._n += 1
        return f"{prefix}-{self._n:04d}"

    def table(self, name):
        return FakeQuery(self, name)

    # -- seeding helpers
    def add_institution(self, institution_id, name, policy, threshold, grades, *, verified=True):
        self.tables["institutions"].append(
            {
                "id": institution_id,
                "name": name,
                "repeat_policy": policy,
                "repeat_replacement_max_points": threshold,
                "grade_scale_verified": verified,
            }
        )
        for letter, points in grades:
            self.tables["grade_point_map"].append(
                {
                    "id": self.new_id("gpm"),
                    "institution_id": institution_id,
                    "letter": letter,
                    "points": points,
                    "counts_toward_gpa": True,
                    "counts_toward_credit": True,
                }
            )

    def add_term(self, term_id, year, season, sequence):
        self.tables["academic_terms"].append(
            {
                "id": term_id,
                "student_id": STUDENT,
                "year": year,
                "season": season,
                "sequence": sequence,
                "label": f"{season} {year}",
            }
        )
        return term_id

    def add_course(
        self,
        course_code,
        letter_grade,
        term_id,
        institution_id=SMU,
        *,
        confirmed=True,
        catalog_course_id=None,
        credit_hours="3.00",
        student_id=STUDENT,
    ):
        row = {
            "id": self.new_id("cr"),
            "student_id": student_id,
            "institution_id": institution_id,
            "term_id": term_id,
            "course_code": course_code,
            "title": course_code,
            "credit_hours": credit_hours,
            "letter_grade": letter_grade,
            "credit_type": "resident",
            "counts_toward_credit": True,
            "counts_toward_gpa": True,
            "status": "completed",
            "source": "transcript_parse",
            "catalog_course_id": catalog_course_id,
            "confirmed_at": "2026-08-09T00:00:00Z" if confirmed else None,
            "excluded_from_gpa_by": None,
        }
        self.tables["course_records"].append(row)
        return row


@pytest.fixture
def db():
    store = FakeDB()
    store.add_institution(SMU, "SMU", "latest_replaces", SMU_THRESHOLD, SMU_GRADES)
    store.add_institution(TAMU, "TAMU", "all_attempts_count", None, TAMU_GRADES)
    store.add_institution(UNCLASSIFIED, "Unclassified College", None, None, TAMU_GRADES)
    store.add_term("term-f23", 2023, "Fall", 0)
    store.add_term("term-s24", 2024, "Spring", 1)
    store.add_term("term-f24", 2024, "Fall", 2)
    return store


def code_state(db):
    """course_code -> excluded_from_gpa_by, for compact assertions."""
    return {
        (r["course_code"], r["letter_grade"]): r["excluded_from_gpa_by"]
        for r in db.tables["course_records"]
    }


# ── 1. SMU repeat below threshold: second excludes first ────────────────────


def test_smu_repeat_below_threshold_excludes_the_earlier_attempt(db):
    first = db.add_course("HIST 101", "D", "term-f23", SMU)
    second = db.add_course("HIST 101", "B", "term-s24", SMU)

    report = repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] == second["id"]
    assert second["excluded_from_gpa_by"] is None, "the surviving attempt is never excluded"
    assert len(report.exclusions) == 1
    assert report.exclusions[0].excluded_id == first["id"]
    assert report.exclusions[0].superseded_by == second["id"]


def test_repeat_across_two_separate_confirm_calls(db):
    """The cross-upload case: first attempt confirmed long before the retake."""
    first = db.add_course("HIST 101", "D", "term-f23", SMU)
    confirm_course_rows(db, STUDENT)
    assert first["excluded_from_gpa_by"] is None, "a lone attempt excludes nothing"

    # Second upload, later term, confirmed in a separate call.
    second = db.add_course("HIST 101", "B", "term-s24", SMU, confirmed=False)
    result = confirm_course_rows(db, STUDENT)

    assert result["confirmed"] == 1
    assert first["excluded_from_gpa_by"] == second["id"]
    assert result["repeats"]["excluded"][0]["course_code"] == "HIST 101"


@pytest.mark.parametrize("earlier_grade", ["D+", "D", "D-", "F"])
def test_every_grade_at_or_below_the_threshold_is_replaceable(db, earlier_grade):
    first = db.add_course("HIST 101", earlier_grade, "term-f23", SMU)
    second = db.add_course("HIST 101", "A", "term-s24", SMU)

    repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] == second["id"], (
        f"{earlier_grade} is at or below SMU's D+ threshold and must be replaceable"
    )


# ── 2. THE OPTION A/B DIVIDING LINE ─────────────────────────────────────────


def test_b_then_retake_excludes_nothing(db):
    """A B retaken later keeps BOTH attempts -- per actual SMU policy.

    This is the test that fails under Option A (unconditional latest-wins).
    Everything else about this case is identical to the D-then-B case above:
    same institution, same policy, same ordering, two attempts. The ONLY
    difference is the earlier attempt's points (3.00 > 1.30), so a pass here
    with a fail there proves the threshold comparison is what is doing the
    work -- not merely the presence of a repeat_policy.
    """
    first = db.add_course("HIST 101", "B", "term-f23", SMU)
    second = db.add_course("HIST 101", "A", "term-s24", SMU)

    report = repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] is None, (
        "a B is above SMU's D+ threshold -- replacing it would silently delete "
        "a legitimately-counting grade from the student's GPA"
    )
    assert second["excluded_from_gpa_by"] is None
    assert report.exclusions == []
    # The group WAS examined -- this is a considered no, not an oversight.
    assert report.groups_considered == 1


@pytest.mark.parametrize("earlier_grade", ["C-", "C", "C+", "B-", "B", "A-", "A"])
def test_every_grade_above_the_threshold_is_left_alone(db, earlier_grade):
    first = db.add_course("HIST 101", earlier_grade, "term-f23", SMU)
    db.add_course("HIST 101", "A", "term-s24", SMU)

    repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] is None, (
        f"{earlier_grade} is above SMU's D+ threshold and must keep counting"
    )


def test_the_threshold_boundary_is_inclusive_at_d_plus(db):
    """D+ (1.30) is eligible; C- (1.70), the next grade up, is not."""
    d_plus = db.add_course("HIST 101", "D+", "term-f23", SMU)
    db.add_course("HIST 101", "A", "term-s24", SMU)
    c_minus = db.add_course("MATH 101", "C-", "term-f23", SMU)
    db.add_course("MATH 101", "A", "term-s24", SMU)

    repeats.reconcile_repeats(db, STUDENT)

    assert d_plus["excluded_from_gpa_by"] is not None, "D+ == threshold, inclusive"
    assert c_minus["excluded_from_gpa_by"] is None, "C- is above threshold"


# ── 3. TAMU: the Rule 10.22 trap is NOT implemented ─────────────────────────


@pytest.mark.parametrize(
    "first_grade, second_grade",
    [("D", "A"), ("F", "B"), ("B", "A"), ("A", "D"), ("C", "C")],
)
def test_tamu_never_excludes_anything(db, first_grade, second_grade):
    """all_attempts_count means set nothing, whatever the grades.

    TAMU Rule 10.22 (repeat of a B-or-better excluded by the original) is a
    DEGREE AUDIT rule, not a GPA rule -- Rule 10.21 requires the cumulative GPA
    include every graded attempt. excluded_from_gpa_by feeds GPA and nothing
    else, so modeling 10.22 with it would corrupt the very GPA the rule it is
    named after does not touch.
    """
    first = db.add_course("MATH 151", first_grade, "term-f23", TAMU)
    second = db.add_course("MATH 151", second_grade, "term-s24", TAMU)

    report = repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] is None
    assert second["excluded_from_gpa_by"] is None
    assert report.exclusions == []
    assert report.groups_considered == 0, "the policy short-circuits before grouping"


# ── 4. NULL repeat_policy: the safe direction ───────────────────────────────


def test_null_repeat_policy_sets_nothing(db):
    """An unclassified institution must never have grades silently removed."""
    first = db.add_course("ENGL 101", "D", "term-f23", UNCLASSIFIED)
    second = db.add_course("ENGL 101", "A", "term-s24", UNCLASSIFIED)

    report = repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] is None
    assert second["excluded_from_gpa_by"] is None
    assert report.exclusions == []


def test_latest_replaces_without_a_threshold_replaces_unconditionally(db):
    """Null threshold means no gating -- the column's documented semantics."""
    db.tables["institutions"][0]["repeat_replacement_max_points"] = None
    first = db.add_course("HIST 101", "B", "term-f23", SMU)
    second = db.add_course("HIST 101", "A", "term-s24", SMU)

    repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] == second["id"]


# ── 5. idempotency and full recompute ───────────────────────────────────────


def test_reconcile_is_idempotent(db):
    first = db.add_course("HIST 101", "D", "term-f23", SMU)
    second = db.add_course("HIST 101", "B", "term-s24", SMU)

    first_report = repeats.reconcile_repeats(db, STUDENT)
    state_after_first = code_state(db)

    second_report = repeats.reconcile_repeats(db, STUDENT)
    state_after_second = code_state(db)

    assert state_after_first == state_after_second
    assert [e.to_dict() for e in first_report.exclusions] == [
        e.to_dict() for e in second_report.exclusions
    ]
    assert first["excluded_from_gpa_by"] == second["id"]
    # The second run cleared the first run's exclusion before re-deriving it.
    assert second_report.cleared == 1


def test_grade_correction_in_review_changes_the_outcome(db):
    """Full recompute, not a stale exclusion.

    A student corrects a misread D to a B. On the next pass the exclusion must
    DISAPPEAR -- under an incremental design it would persist invisibly, and
    the course would stay out of the GPA forever on the strength of a grade
    that no longer exists.
    """
    first = db.add_course("HIST 101", "D", "term-f23", SMU)
    second = db.add_course("HIST 101", "B", "term-s24", SMU)

    repeats.reconcile_repeats(db, STUDENT)
    assert first["excluded_from_gpa_by"] == second["id"]

    # The review edit: the first attempt was actually a B.
    first["letter_grade"] = "B"

    report = repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] is None, (
        "the exclusion rested on a D that no longer exists and must be withdrawn"
    )
    assert report.cleared == 1
    assert report.exclusions == []


def test_recompute_moves_the_exclusion_when_a_later_attempt_appears(db):
    first = db.add_course("HIST 101", "D", "term-f23", SMU)
    second = db.add_course("HIST 101", "D", "term-s24", SMU)

    repeats.reconcile_repeats(db, STUDENT)
    assert first["excluded_from_gpa_by"] == second["id"]
    assert second["excluded_from_gpa_by"] is None

    third = db.add_course("HIST 101", "A", "term-f24", SMU)
    repeats.reconcile_repeats(db, STUDENT)

    # Both earlier attempts now defer to the newest one.
    assert first["excluded_from_gpa_by"] == third["id"]
    assert second["excluded_from_gpa_by"] == third["id"]
    assert third["excluded_from_gpa_by"] is None


# ── 6. rows excluded from detection ─────────────────────────────────────────


def test_null_term_id_rows_are_left_untouched(db):
    """No term means no position in time, so no basis for picking a winner."""
    no_term = db.add_course("HIST 101", "D", None, SMU)
    later = db.add_course("HIST 101", "A", "term-s24", SMU)

    report = repeats.reconcile_repeats(db, STUDENT)

    assert no_term["excluded_from_gpa_by"] is None
    assert later["excluded_from_gpa_by"] is None
    assert report.skipped_no_term == 1
    assert report.exclusions == []


def test_unconfirmed_rows_do_not_participate(db):
    """Only confirmed rows count toward GPA, so only they can supersede."""
    first = db.add_course("HIST 101", "D", "term-f23", SMU, confirmed=True)
    second = db.add_course("HIST 101", "A", "term-s24", SMU, confirmed=False)

    repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] is None, (
        "an unconfirmed attempt must not exclude a confirmed one -- that would "
        "drop the course from the GPA entirely until the student confirms"
    )
    assert second["excluded_from_gpa_by"] is None


def test_a_single_attempt_is_never_excluded(db):
    only = db.add_course("HIST 101", "F", "term-f23", SMU)

    report = repeats.reconcile_repeats(db, STUDENT)

    assert only["excluded_from_gpa_by"] is None
    assert report.groups_considered == 0


def test_different_courses_are_not_grouped(db):
    a = db.add_course("HIST 101", "D", "term-f23", SMU)
    b = db.add_course("HIST 102", "D", "term-s24", SMU)

    repeats.reconcile_repeats(db, STUDENT)

    assert a["excluded_from_gpa_by"] is None
    assert b["excluded_from_gpa_by"] is None


def test_same_code_at_different_institutions_is_not_a_repeat(db):
    """Cross-institution repeats are out of scope for v1."""
    tamu_row = db.add_course("MATH 251", "D", "term-f23", TAMU)
    smu_row = db.add_course("MATH 251", "A", "term-s24", SMU)

    repeats.reconcile_repeats(db, STUDENT)

    assert tamu_row["excluded_from_gpa_by"] is None
    assert smu_row["excluded_from_gpa_by"] is None


def test_another_students_rows_are_never_touched(db):
    mine = db.add_course("HIST 101", "D", "term-f23", SMU)
    theirs = db.add_course("HIST 101", "D", "term-f23", SMU, student_id="other-student")
    db.add_course("HIST 101", "A", "term-s24", SMU)

    repeats.reconcile_repeats(db, STUDENT)

    assert mine["excluded_from_gpa_by"] is not None
    assert theirs["excluded_from_gpa_by"] is None


# ── 7. grouping key ─────────────────────────────────────────────────────────


def test_catalog_course_id_groups_across_code_formatting(db):
    """The stronger identity: same catalog row, differently printed codes."""
    first = db.add_course("HIST101", "D", "term-f23", SMU, catalog_course_id="cat-1")
    second = db.add_course("HIST 101", "A", "term-s24", SMU, catalog_course_id="cat-1")

    repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] == second["id"]


def test_normalized_code_groups_when_catalog_id_is_absent(db):
    first = db.add_course("hist-101", "D", "term-f23", SMU)
    second = db.add_course("HIST 101", "A", "term-s24", SMU)

    repeats.reconcile_repeats(db, STUDENT)

    assert first["excluded_from_gpa_by"] == second["id"]


def test_season_ordering_within_a_year(db):
    """Spring precedes Fall in the same year -- not alphabetical, not sequence."""
    db.add_term("term-sp23", 2023, "Spring", 9)  # high sequence, early term
    spring = db.add_course("HIST 101", "D", "term-sp23", SMU)
    fall = db.add_course("HIST 101", "A", "term-f23", SMU)

    repeats.reconcile_repeats(db, STUDENT)

    assert spring["excluded_from_gpa_by"] == fall["id"], (
        "ordering must use (year, season), not academic_terms.sequence"
    )


def test_ordering_ignores_sequence_when_it_contradicts_chronology(db):
    """The exact Part 5 hazard: a later upload gives an EARLIER term a HIGHER
    sequence. Ordering by sequence would exclude the wrong attempt."""
    db.add_term("term-f22", 2022, "Fall", 99)  # added by a second upload
    older = db.add_course("HIST 101", "D", "term-f22", SMU)
    newer = db.add_course("HIST 101", "A", "term-f23", SMU)

    repeats.reconcile_repeats(db, STUDENT)

    assert older["excluded_from_gpa_by"] == newer["id"]
    assert newer["excluded_from_gpa_by"] is None, (
        "sequence 99 > 0 would have wrongly made the 2022 attempt the winner"
    )


# ── 8. gpa.py regression: earned_hours unaffected ───────────────────────────


SMU_GPA_MAP = {
    letter: GradeMapRow(letter=letter, points=points, counts_toward_gpa=True, counts_toward_credit=True)
    for letter, points in SMU_GRADES
}
SMU_INSTITUTION = Institution(
    id=SMU, name="SMU", uses_plus_minus=True, transfer_grades_count_toward_gpa=False
)


def test_excluded_repeat_still_counts_toward_earned_hours():
    """Regression for the Part 1 finding.

    gpa.py tallies earned_hours at :166-171, ABOVE the excluded_from_gpa_by
    check at :177. An excluded repeat is out of the GPA but still earned its
    credit -- the course was taken and passed, it just is not scored twice.
    """
    second = CourseRecord(
        course_code="HIST 101",
        credit_hours=3.0,
        letter_grade="B",
        credit_type="resident",
        status="completed",
        institution_id=SMU,
        confirmed_at="2026-08-09T00:00:00Z",
    )
    first = CourseRecord(
        course_code="HIST 101",
        credit_hours=3.0,
        letter_grade="D",
        credit_type="resident",
        status="completed",
        institution_id=SMU,
        confirmed_at="2026-08-09T00:00:00Z",
        excluded_from_gpa_by="the-second-attempt-id",
    )

    result = compute_gpa([first, second], SMU_INSTITUTION, SMU_GPA_MAP, mode="official")

    # GPA sees only the surviving attempt.
    assert result.included == [second]
    assert result.gpa_hours == 3.0
    assert result.gpa == 3.0
    assert ("excluded_by_repeat",) == tuple(
        reason for record, reason in result.excluded if record is first
    )

    # But BOTH attempts earned credit.
    assert result.earned_hours == 6.0, (
        "exclusion removes a row from the GPA, not from earned credit"
    )


def test_excluded_repeat_is_excluded_in_projected_mode_too():
    """The check sits above the status-scope test, so it applies in both modes."""
    record = CourseRecord(
        course_code="HIST 101",
        credit_hours=3.0,
        letter_grade="D",
        credit_type="resident",
        status="completed",
        institution_id=SMU,
        confirmed_at="2026-08-09T00:00:00Z",
        excluded_from_gpa_by="other-id",
    )

    for mode in ("official", "projected"):
        result = compute_gpa([record], SMU_INSTITUTION, SMU_GPA_MAP, mode=mode)
        assert result.included == [], mode
        assert result.gpa is None, mode


# ── 9. review surfacing (Option C) ──────────────────────────────────────────


def test_review_surfaces_an_excluded_row_with_its_superseding_attempt(db):
    first = db.add_course("HIST 101", "D", "term-f23", SMU)
    second = db.add_course("HIST 101", "B", "term-s24", SMU)
    repeats.reconcile_repeats(db, STUDENT)

    payload = load_unconfirmed(db, STUDENT)

    assert len(payload["excluded_by_repeat"]) == 1
    entry = payload["excluded_by_repeat"][0]
    assert entry["id"] == first["id"]

    context = entry["repeat_exclusion"]
    assert context["excluded_from_gpa"] is True
    assert context["reason"] == "repeat_replacement"
    assert context["superseded_by_id"] == second["id"]
    # Named, not a bare uuid -- enough to render "replaced by your B attempt".
    assert context["superseded_by"]["course_code"] == "HIST 101"
    assert context["superseded_by"]["letter_grade"] == "B"
    # The counter-intuitive half of the rule is stated for the UI.
    assert context["still_counts_toward_earned_hours"] is True


def test_review_reports_no_repeat_context_on_ordinary_rows(db):
    row = db.add_course("HIST 101", "A", "term-f23", SMU, confirmed=False)

    payload = load_unconfirmed(db, STUDENT)

    assert payload["excluded_by_repeat"] == []
    assert payload["course_records"][0]["repeat_exclusion"] is None
    assert payload["course_records"][0]["id"] == row["id"]


def test_excluded_from_gpa_by_is_not_student_editable():
    """System-managed: derived, and recomputed on every confirm.

    Letting it be edited would create a value the next reconcile silently
    overwrites -- worse than not offering the field at all.
    """
    from CampusIQ_career.transcript.review import (
        EDITABLE_FIELDS,
        SYSTEM_MANAGED_FIELDS,
        clean_edit_fields,
    )

    assert "excluded_from_gpa_by" not in EDITABLE_FIELDS
    assert "excluded_from_gpa_by" in SYSTEM_MANAGED_FIELDS

    cleaned = clean_edit_fields({"title": "New", "excluded_from_gpa_by": "some-id"})
    assert cleaned == {"title": "New"}


def test_project_row_without_a_lookup_still_reports_the_exclusion(db):
    """Degrades to the id alone rather than dropping the context entirely."""
    row = db.add_course("HIST 101", "D", "term-f23", SMU)
    row["excluded_from_gpa_by"] = "some-unknown-id"

    projected = project_row(row)

    assert projected["repeat_exclusion"]["superseded_by_id"] == "some-unknown-id"
    assert projected["repeat_exclusion"]["superseded_by"] is None


# ── 10. confirm-flow integration ────────────────────────────────────────────


def test_confirm_reports_the_repeat_outcome(db):
    db.add_course("HIST 101", "D", "term-f23", SMU, confirmed=False)
    db.add_course("HIST 101", "B", "term-s24", SMU, confirmed=False)

    result = confirm_course_rows(db, STUDENT)

    assert result["confirmed"] == 2
    assert result["repeats"]["excluded"][0]["course_code"] == "HIST 101"
    assert result["repeats"]["groups_considered"] == 1


def test_reconciliation_failure_does_not_undo_a_successful_confirm(db, monkeypatch):
    """Confirmation is the student's action; reconciliation is bookkeeping."""
    row = db.add_course("HIST 101", "A", "term-f23", SMU, confirmed=False)

    def boom(*a, **k):
        raise RuntimeError("reconciliation exploded")

    monkeypatch.setattr("CampusIQ_career.transcript.store.reconcile_repeats", boom)

    result = confirm_course_rows(db, STUDENT)

    assert result["confirmed"] == 1
    assert result["repeats"] is None
    assert row["confirmed_at"] is not None, "the confirmation must stand"


def test_confirm_with_nothing_pending_does_not_reconcile(db):
    db.add_course("HIST 101", "D", "term-f23", SMU, confirmed=True)

    result = confirm_course_rows(db, STUDENT)

    assert result["confirmed"] == 0
    # Present-but-null, not absent: the response shape is identical on every path.
    assert "repeats" in result
    assert result["repeats"] is None
