"""Tests for CampusIQ_career.academics.gpa.

Uses inline fixture grade maps only — does not read the migration SQL
or any student JSON file.
"""

import pytest

from CampusIQ_career.academics.gpa import (
    CourseRecord,
    GradeMapRow,
    Institution,
    compute_both,
    compute_gpa,
    resolve_grade,
)


def _row(letter, points, counts_toward_gpa, counts_toward_credit):
    return GradeMapRow(
        letter=letter,
        points=points,
        counts_toward_gpa=counts_toward_gpa,
        counts_toward_credit=counts_toward_credit,
    )


# TAMU-shaped: A/B/C/D/F only, no plus/minus.
TAMU_MAP = {
    "A": _row("A", 4.0, True, True),
    "B": _row("B", 3.0, True, True),
    "C": _row("C", 2.0, True, True),
    "D": _row("D", 1.0, True, True),
    "F": _row("F", 0.0, True, True),
    "W": _row("W", None, False, False),
    "I": _row("I", None, False, False),
}

TAMU = Institution(
    id="tamu",
    name="Texas A&M University",
    uses_plus_minus=False,
    transfer_grades_count_toward_gpa=False,
)

TAMU_TRANSFER_OK = Institution(
    id="tamu-transfer-ok",
    name="Texas A&M University (transfer-inclusive variant)",
    uses_plus_minus=False,
    transfer_grades_count_toward_gpa=True,
)

# SMU-shaped: full plus/minus 4.0 scale.
SMU_MAP = {
    "A": _row("A", 4.0, True, True),
    "A-": _row("A-", 3.7, True, True),
    "B+": _row("B+", 3.3, True, True),
    "B": _row("B", 3.0, True, True),
    "B-": _row("B-", 2.7, True, True),
    "C+": _row("C+", 2.3, True, True),
    "C": _row("C", 2.0, True, True),
    "C-": _row("C-", 1.7, True, True),
    "D+": _row("D+", 1.3, True, True),
    "D": _row("D", 1.0, True, True),
    "D-": _row("D-", 0.7, True, True),
    "F": _row("F", 0.0, True, True),
    "W": _row("W", None, False, False),
    "I": _row("I", None, False, False),
}

SMU = Institution(
    id="smu",
    name="Southern Methodist University",
    uses_plus_minus=True,
    transfer_grades_count_toward_gpa=False,
)

# A plus/minus institution whose map is missing 'B+' entirely.
SPARSE_PLUS_MINUS_MAP = {
    "A": _row("A", 4.0, True, True),
    "A-": _row("A-", 3.7, True, True),
    "B": _row("B", 3.0, True, True),
    "B-": _row("B-", 2.7, True, True),
    "F": _row("F", 0.0, True, True),
}

SPARSE_PLUS_MINUS_INSTITUTION = Institution(
    id="sparse",
    name="Sparse Plus/Minus School",
    uses_plus_minus=True,
    transfer_grades_count_toward_gpa=False,
)


def _course(
    course_code="TEST 101",
    credit_hours=3.0,
    letter_grade="A",
    credit_type="resident",
    status="completed",
    institution_id="tamu",
    confirmed_at="2026-01-01T00:00:00Z",
    excluded_from_gpa_by=None,
):
    return CourseRecord(
        course_code=course_code,
        credit_hours=credit_hours,
        letter_grade=letter_grade,
        credit_type=credit_type,
        status=status,
        institution_id=institution_id,
        confirmed_at=confirmed_at,
        excluded_from_gpa_by=excluded_from_gpa_by,
    )


# 1. Exact match on both maps.
def test_exact_match_on_both_maps():
    tamu_res = resolve_grade("A", TAMU, TAMU_MAP)
    assert tamu_res.match_type == "exact"
    assert tamu_res.points == 4.0
    assert tamu_res.counts_toward_gpa is True

    smu_res = resolve_grade("A", SMU, SMU_MAP)
    assert smu_res.match_type == "exact"
    assert smu_res.points == 4.0
    assert smu_res.counts_toward_gpa is True


# 2. 'B+' against TAMU -> normalized to 'B', points 3.0.
def test_bplus_against_tamu_normalizes_to_b():
    res = resolve_grade("B+", TAMU, TAMU_MAP)
    assert res.match_type == "normalized"
    assert res.letter_resolved == "B"
    assert res.points == 3.0


# 3. 'B+' against SMU -> exact, points 3.3.
def test_bplus_against_smu_is_exact():
    res = resolve_grade("B+", SMU, SMU_MAP)
    assert res.match_type == "exact"
    assert res.letter_resolved == "B+"
    assert res.points == 3.3


# 4. 'B+' against a plus/minus map that lacks 'B+' -> unmapped, NOT normalized.
def test_bplus_against_sparse_plus_minus_map_is_unmapped():
    res = resolve_grade("B+", SPARSE_PLUS_MINUS_INSTITUTION, SPARSE_PLUS_MINUS_MAP)
    assert res.match_type == "unmapped"
    assert res.letter_resolved is None
    assert res.points is None


# 5. 'S' against either map -> unmapped, excluded with a reason.
def test_unrecognized_letter_is_unmapped_and_excluded():
    res_tamu = resolve_grade("S", TAMU, TAMU_MAP)
    assert res_tamu.match_type == "unmapped"

    res_smu = resolve_grade("S", SMU, SMU_MAP)
    assert res_smu.match_type == "unmapped"

    record = _course(letter_grade="S")
    result = compute_gpa([record], TAMU, TAMU_MAP, mode="official")
    assert result.included == []
    assert len(result.excluded) == 1
    excluded_record, reason = result.excluded[0]
    assert excluded_record is record
    assert reason == "unmapped_grade"


# 6. letter None -> unmapped, distinct reason, no exception.
def test_none_letter_is_unmapped_with_distinct_reason():
    res = resolve_grade(None, TAMU, TAMU_MAP)
    assert res.match_type == "unmapped"
    assert res.letter_resolved is None
    assert res.points is None

    record = _course(letter_grade=None, credit_type="exam")
    result = compute_gpa([record], TAMU, TAMU_MAP, mode="official")
    assert result.included == []
    _, reason = result.excluded[0]
    assert reason == "no_letter_grade"

    # Confirm this is a distinct reason from an unrecognized-but-present letter.
    other_record = _course(letter_grade="S")
    other_result = compute_gpa([other_record], TAMU, TAMU_MAP, mode="official")
    _, other_reason = other_result.excluded[0]
    assert other_reason != reason


# 7. W and I rows (points None) excluded from GPA but present in excluded with reasons.
def test_w_and_i_excluded_from_gpa():
    w_record = _course(course_code="TAMU 100", letter_grade="W")
    i_record = _course(course_code="TAMU 200", letter_grade="I")
    result = compute_gpa([w_record, i_record], TAMU, TAMU_MAP, mode="official")

    assert result.included == []
    assert result.gpa_hours == 0.0
    assert result.quality_points == 0.0
    assert result.gpa is None

    reasons = {rec.course_code: reason for rec, reason in result.excluded}
    assert reasons["TAMU 100"] == "grade_excluded_by_map"
    assert reasons["TAMU 200"] == "grade_excluded_by_map"


# 8. All records in_progress: official gpa is None, projected gpa is a number.
def test_all_in_progress_official_none_projected_numeric():
    records = [
        _course(course_code="TEST 101", letter_grade="A", status="in_progress", credit_hours=3.0),
        _course(course_code="TEST 102", letter_grade="B", status="in_progress", credit_hours=3.0),
    ]
    both = compute_both(records, TAMU, TAMU_MAP)

    assert both.official.gpa is None
    assert both.official.gpa_hours == 0.0
    assert both.projected.gpa is not None
    assert isinstance(both.projected.gpa, float)
    assert both.projected.gpa == 3.5


# 9. Empty record list: both None, no exception.
def test_empty_record_list():
    both = compute_both([], TAMU, TAMU_MAP)
    assert both.official.gpa is None
    assert both.projected.gpa is None
    assert both.official.included == []
    assert both.projected.included == []
    assert both.completed_hours == 0.0
    assert both.in_progress_hours == 0.0


# 10. Transfer credit excluded when transfer_grades_count_toward_gpa is False,
#     included when True.
def test_transfer_credit_gpa_inclusion_depends_on_institution_flag():
    record = _course(letter_grade="A", credit_type="transfer", credit_hours=3.0)

    excluded_result = compute_gpa([record], TAMU, TAMU_MAP, mode="official")
    assert excluded_result.included == []
    _, reason = excluded_result.excluded[0]
    assert reason == "transfer_not_included"

    included_result = compute_gpa([record], TAMU_TRANSFER_OK, TAMU_MAP, mode="official")
    assert included_result.included == [record]
    assert included_result.gpa_hours == 3.0
    assert included_result.quality_points == 12.0
    assert included_result.gpa == 4.0


# 11. Exam credit never in gpa_hours but present in earned_hours when completed.
def test_exam_credit_excluded_from_gpa_but_counted_in_earned_hours():
    exam_record = _course(
        letter_grade=None, credit_type="exam", status="completed", credit_hours=4.0
    )
    result = compute_gpa([exam_record], TAMU, TAMU_MAP, mode="official")

    assert result.included == []
    assert result.gpa_hours == 0.0
    assert result.gpa is None
    assert result.earned_hours == 4.0
    _, reason = result.excluded[0]
    assert reason == "no_letter_grade"


# 12. confirmed_at None excluded.
def test_unconfirmed_record_excluded():
    record = _course(letter_grade="A", confirmed_at=None)
    result = compute_gpa([record], TAMU, TAMU_MAP, mode="official")

    assert result.included == []
    assert result.gpa_hours == 0.0
    assert result.gpa is None
    _, reason = result.excluded[0]
    assert reason == "unconfirmed"


# 13. A worked multi-course case with hand-computed quality points and GPA.
def test_worked_multi_course_case():
    records = [
        _course(course_code="ENGR 102", letter_grade="A", credit_hours=2.0),  # 8.0 qp
        _course(course_code="MATH 151", letter_grade="B+", credit_hours=4.0),  # normalized B -> 12.0 qp
        _course(course_code="ENGL 104", letter_grade="C", credit_hours=3.0),  # 6.0 qp
        _course(course_code="AP CREDIT", letter_grade=None, credit_type="exam", credit_hours=3.0),
        _course(course_code="XFER 100", letter_grade="A", credit_type="transfer", credit_hours=3.0),
        _course(course_code="WD 100", letter_grade="W", credit_hours=3.0),
    ]

    result = compute_gpa(records, TAMU, TAMU_MAP, mode="official")

    # Included: ENGR 102 (A, 2h -> 8.0qp), MATH 151 (B+ normalized to B, 4h -> 12.0qp),
    # ENGL 104 (C, 3h -> 6.0qp). Excluded: exam credit, transfer (TAMU doesn't count
    # transfer toward GPA), and the W.
    expected_quality_points = 8.0 + 12.0 + 6.0
    expected_gpa_hours = 2.0 + 4.0 + 3.0
    expected_gpa = round(expected_quality_points / expected_gpa_hours, 2)

    assert result.quality_points == expected_quality_points
    assert result.gpa_hours == expected_gpa_hours
    assert result.gpa == expected_gpa
    assert expected_gpa == 2.89

    included_codes = {r.course_code for r in result.included}
    assert included_codes == {"ENGR 102", "MATH 151", "ENGL 104"}

    excluded_codes = {r.course_code: reason for r, reason in result.excluded}
    assert excluded_codes["AP CREDIT"] == "no_letter_grade"
    assert excluded_codes["XFER 100"] == "transfer_not_included"
    assert excluded_codes["WD 100"] == "grade_excluded_by_map"

    # earned_hours includes transfer and exam credit on top of the GPA-eligible hours.
    assert result.earned_hours == 2.0 + 4.0 + 3.0 + 3.0 + 3.0

    # excluded_from_gpa_by defaults to None on every record here, and none of
    # them are excluded for the 'excluded_by_repeat' reason -- confirms that
    # leaving the field unset does not change this test's pre-existing behavior.
    assert all(r.excluded_from_gpa_by is None for r in records)
    assert "excluded_by_repeat" not in excluded_codes.values()


# 14. A record with excluded_from_gpa_by set is excluded from GPA with
#     reason 'excluded_by_repeat'.
def test_excluded_from_gpa_by_excludes_with_repeat_reason():
    record = _course(letter_grade="A", excluded_from_gpa_by="some-other-record-id")
    result = compute_gpa([record], TAMU, TAMU_MAP, mode="official")

    assert result.included == []
    assert len(result.excluded) == 1
    excluded_record, reason = result.excluded[0]
    assert excluded_record is record
    assert reason == "excluded_by_repeat"


# 15. An excluded-by-repeat record still contributes to earned_hours (only
#     the grade points are dropped, not the earned credit).
def test_excluded_from_gpa_by_still_counts_earned_hours():
    record = _course(
        letter_grade="A", credit_hours=3.0, excluded_from_gpa_by="some-other-record-id"
    )
    result = compute_gpa([record], TAMU, TAMU_MAP, mode="official")

    assert result.earned_hours == 3.0
    assert result.gpa_hours == 0.0
    assert result.quality_points == 0.0


# 16. Two-attempt repeat, SMU-direction: first attempt D excluded by the
#     second attempt B. Only the B counts.
def test_two_attempt_repeat_first_excluded_by_second():
    second_attempt = _course(
        course_code="HIST 101",
        letter_grade="B",
        credit_hours=3.0,
        institution_id="smu",
    )
    first_attempt = _course(
        course_code="HIST 101",
        letter_grade="D",
        credit_hours=3.0,
        institution_id="smu",
        excluded_from_gpa_by=second_attempt.course_code,
    )

    records = [first_attempt, second_attempt]
    result = compute_gpa(records, SMU, SMU_MAP, mode="official")

    # Only the second attempt (B, 3.0 points) is included.
    assert result.included == [second_attempt]
    excluded_codes = {r.course_code: reason for r, reason in result.excluded}
    assert excluded_codes["HIST 101"] == "excluded_by_repeat"

    expected_quality_points = 3.0 * 3.0  # B (3.0 points) x 3.0 hours
    expected_gpa_hours = 3.0
    assert result.quality_points == expected_quality_points
    assert result.gpa_hours == expected_gpa_hours
    assert result.gpa == round(expected_quality_points / expected_gpa_hours, 2)
    assert result.gpa == 3.0

    # Both attempts earned resident credit hours (D and B both earn credit
    # under the TAMU/SMU-shaped maps used here), so both count toward
    # earned_hours regardless of the GPA exclusion.
    assert result.earned_hours == 3.0 + 3.0


# 17. The reverse direction (TAMU Rule 10.22): a repeat excluded by the
#     original, using the same excluded_from_gpa_by mechanism with no
#     special-casing of direction.
def test_repeat_excluded_by_original_reverse_direction():
    original = _course(
        course_code="MATH 151",
        letter_grade="B",
        credit_hours=4.0,
        institution_id="tamu",
    )
    repeat = _course(
        course_code="MATH 151",
        letter_grade="A",
        credit_hours=4.0,
        institution_id="tamu",
        excluded_from_gpa_by=original.course_code,
    )

    records = [original, repeat]
    result = compute_gpa(records, TAMU, TAMU_MAP, mode="official")

    # Only the original (B, 3.0 points) is included; the repeat is excluded.
    assert result.included == [original]
    excluded_codes = {id(r): reason for r, reason in result.excluded}
    assert excluded_codes[id(repeat)] == "excluded_by_repeat"

    expected_quality_points = 3.0 * 4.0  # B (3.0 points) x 4.0 hours
    expected_gpa_hours = 4.0
    assert result.quality_points == expected_quality_points
    assert result.gpa_hours == expected_gpa_hours
    assert result.gpa == round(expected_quality_points / expected_gpa_hours, 2)
    assert result.gpa == 3.0

    assert result.earned_hours == 4.0 + 4.0


# 18. An excluded-by-repeat record whose grade earns no credit adds nothing
#     to earned_hours. TAMU_MAP's 'F' row has counts_toward_credit=True (an
#     attempted F still counts toward attempted-credit accounting under this
#     fixture's institution), so a distinct grade map is used here with an
#     'F' row that earns no credit at all, to exercise that branch.
_NO_CREDIT_F_MAP = {
    **TAMU_MAP,
    "F": _row("F", 0.0, True, False),
}


def test_excluded_from_gpa_by_with_failing_grade_earns_no_credit():
    record = _course(
        letter_grade="F", credit_hours=3.0, excluded_from_gpa_by="some-other-record-id"
    )
    result = compute_gpa([record], TAMU, _NO_CREDIT_F_MAP, mode="official")

    assert result.earned_hours == 0.0
    assert result.gpa_hours == 0.0
    _, reason = result.excluded[0]
    assert reason == "excluded_by_repeat"
