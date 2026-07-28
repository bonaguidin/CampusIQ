"""Pure GPA computation: institution-agnostic grade resolution and GPA math.

No database calls, no file I/O, no network. All grading-scale knowledge
comes from the grade_map passed in by the caller — nothing here assumes
a particular institution's letters, points, or plus/minus policy.
"""

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple

CreditType = Literal["resident", "transfer", "exam", "dual_enrollment"]
Status = Literal["completed", "in_progress"]
MatchType = Literal["exact", "normalized", "unmapped"]
Mode = Literal["official", "projected"]


@dataclass(frozen=True)
class GradeMapRow:
    letter: str
    points: Optional[float]
    counts_toward_gpa: bool
    counts_toward_credit: bool


@dataclass(frozen=True)
class Institution:
    id: str
    name: str
    uses_plus_minus: bool
    transfer_grades_count_toward_gpa: bool


@dataclass(frozen=True)
class CourseRecord:
    course_code: str
    credit_hours: float
    letter_grade: Optional[str]
    credit_type: CreditType
    status: Status
    institution_id: str
    confirmed_at: Optional[str] = None


@dataclass(frozen=True)
class GradeResolution:
    letter_input: Optional[str]
    letter_resolved: Optional[str]
    match_type: MatchType
    points: Optional[float]
    counts_toward_gpa: bool
    counts_toward_credit: bool


@dataclass(frozen=True)
class GpaResult:
    gpa: Optional[float]
    quality_points: float
    gpa_hours: float
    earned_hours: float
    included: List[CourseRecord]
    excluded: List[Tuple[CourseRecord, str]]


@dataclass(frozen=True)
class BothGpaResult:
    official: GpaResult
    projected: GpaResult
    completed_hours: float
    in_progress_hours: float


GradeMap = Dict[str, GradeMapRow]

_UNMAPPED_RESOLUTION_POINTS = None
_UNMAPPED_COUNTS_TOWARD_GPA = False
_UNMAPPED_COUNTS_TOWARD_CREDIT = False


def resolve_grade(
    letter: Optional[str],
    institution: Institution,
    grade_map: GradeMap,
) -> GradeResolution:
    """Resolve a letter grade against an institution's grade map.

    Never raises on an unrecognized letter — unmapped is a return value.
    Matching is case-sensitive; letters are used exactly as given.
    """
    if letter is None:
        return GradeResolution(
            letter_input=None,
            letter_resolved=None,
            match_type="unmapped",
            points=_UNMAPPED_RESOLUTION_POINTS,
            counts_toward_gpa=_UNMAPPED_COUNTS_TOWARD_GPA,
            counts_toward_credit=_UNMAPPED_COUNTS_TOWARD_CREDIT,
        )

    row = grade_map.get(letter)
    if row is not None:
        return GradeResolution(
            letter_input=letter,
            letter_resolved=row.letter,
            match_type="exact",
            points=row.points,
            counts_toward_gpa=row.counts_toward_gpa,
            counts_toward_credit=row.counts_toward_credit,
        )

    if not institution.uses_plus_minus and len(letter) >= 2 and letter[-1] in ("+", "-"):
        stripped = letter[:-1]
        stripped_row = grade_map.get(stripped)
        if stripped_row is not None:
            return GradeResolution(
                letter_input=letter,
                letter_resolved=stripped_row.letter,
                match_type="normalized",
                points=stripped_row.points,
                counts_toward_gpa=stripped_row.counts_toward_gpa,
                counts_toward_credit=stripped_row.counts_toward_credit,
            )

    return GradeResolution(
        letter_input=letter,
        letter_resolved=None,
        match_type="unmapped",
        points=_UNMAPPED_RESOLUTION_POINTS,
        counts_toward_gpa=_UNMAPPED_COUNTS_TOWARD_GPA,
        counts_toward_credit=_UNMAPPED_COUNTS_TOWARD_CREDIT,
    )


def compute_gpa(
    records: List[CourseRecord],
    institution: Institution,
    grade_map: GradeMap,
    mode: Mode,
) -> GpaResult:
    """Compute a GPA for one scope ('official' or 'projected').

    'official' considers only completed courses. 'projected' additionally
    considers in-progress courses using their current letter_grade as-is —
    a future caller may substitute hypothetical grades for in-progress
    records before calling this; that substitution is out of scope here.
    """
    if mode == "official":
        scope_statuses = {"completed"}
    elif mode == "projected":
        scope_statuses = {"completed", "in_progress"}
    else:
        raise ValueError(f"unrecognized mode: {mode!r}")

    included: List[CourseRecord] = []
    excluded: List[Tuple[CourseRecord, str]] = []
    quality_points = 0.0
    gpa_hours = 0.0
    earned_hours = 0.0

    for record in records:
        resolution = resolve_grade(record.letter_grade, institution, grade_map)

        # earned_hours is a separate tally from gpa_hours: it is scoped to
        # completed courses only (independent of `mode`) and includes
        # transfer and exam credit as long as credit was actually earned.
        if record.status == "completed":
            counts_toward_credit = (
                True if record.credit_type == "exam" else resolution.counts_toward_credit
            )
            if counts_toward_credit:
                earned_hours += record.credit_hours

        if record.status not in scope_statuses:
            excluded.append((record, "status_out_of_scope"))
            continue

        if resolution.match_type == "unmapped":
            reason = "no_letter_grade" if record.letter_grade is None else "unmapped_grade"
            excluded.append((record, reason))
            continue

        if not resolution.counts_toward_gpa:
            excluded.append((record, "grade_excluded_by_map"))
            continue

        if record.credit_type == "exam":
            excluded.append((record, "exam_credit"))
            continue

        if record.credit_type == "transfer" and not institution.transfer_grades_count_toward_gpa:
            excluded.append((record, "transfer_not_included"))
            continue

        if record.confirmed_at is None:
            excluded.append((record, "unconfirmed"))
            continue

        included.append(record)
        quality_points += resolution.points * record.credit_hours
        gpa_hours += record.credit_hours

    gpa = round(quality_points / gpa_hours, 2) if gpa_hours else None

    return GpaResult(
        gpa=gpa,
        quality_points=quality_points,
        gpa_hours=gpa_hours,
        earned_hours=earned_hours,
        included=included,
        excluded=excluded,
    )


def compute_both(
    records: List[CourseRecord],
    institution: Institution,
    grade_map: GradeMap,
) -> BothGpaResult:
    """Compute official and projected GPA together with hour provenance."""
    official = compute_gpa(records, institution, grade_map, mode="official")
    projected = compute_gpa(records, institution, grade_map, mode="projected")
    completed_hours = sum(r.credit_hours for r in records if r.status == "completed")
    in_progress_hours = sum(r.credit_hours for r in records if r.status == "in_progress")

    return BothGpaResult(
        official=official,
        projected=projected,
        completed_hours=completed_hours,
        in_progress_hours=in_progress_hours,
    )
