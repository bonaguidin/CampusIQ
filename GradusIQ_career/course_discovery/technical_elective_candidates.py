"""Deterministic provisional candidates for open technical-elective slots.

This module implements only the catalog-structured normal path: courses at or
above an institution's own technical-elective department-prefix/level rule
(see TECHNICAL_ELECTIVE_RULES below). Adviser approval, track exclusions, and
exceptional cross-department substitutions remain explicit limitations; this
never claims degree satisfaction or mutates a schedule.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from pydantic import Field

from .models import CatalogInstitution, CourseCatalogRecord, StrictModel
from .prerequisites import structured_prerequisite


# TECHNICAL_ELECTIVE_RULE_ID/NAME identify SMU's specific "Technical
# Electives (9 Credit Hours)" freeform requirement group by its coursedog
# rule id -- this is a route-level MATCHING concern (which requirement
# group(s) in a program's tree this candidate pool is for), separate from
# the eligibility RULE below (which courses in the catalog count once you
# know you're building that pool).
TECHNICAL_ELECTIVE_RULE_ID = "AjzAZTn4"
TECHNICAL_ELECTIVE_NAME = "Technical Electives (9 Credit Hours)"

# TAMU has no single equivalent group -- its Computer Engineering-BS program
# splits open-elective slots across 3 separate, differently-named,
# term-scoped freeform groups instead of SMU's one combined bucket. Exact
# strings confirmed against both the source JSON
# (data/catalog/tamu/requirements_computer-engineering-bs.json) and the live
# `requirement_groups` table for a real TAMU student -- verbatim, including
# the em dashes. Explicit allowlist, not a substring/prefix match: TAMU also
# has "Senior design"/"Senior Design" and "University Core Curriculum"
# freeform groups in the same tree that must NOT match, and a name-pattern
# match (e.g. "contains 'elective'") would have no way to exclude those by
# construction.
TAMU_TECHNICAL_ELECTIVE_GROUP_NAMES = frozenset({
    "Fourth Year — Fall — Area elective",
    "Fourth Year — Fall — Engineering elective",
    "Fourth Year — Spring — Area elective",
})


def technical_elective_group_matches(row: Mapping[str, object], institution: CatalogInstitution) -> bool:
    """Whether `row` (a raw requirement_groups row) is one of the freeform,
    manually-defined groups this module builds a candidate pool for, at the
    given institution.

    Institution-keyed and explicit on both sides -- SMU's exact
    rule_id+name check is unchanged from before this function existed;
    TAMU's is a membership check against TAMU_TECHNICAL_ELECTIVE_GROUP_NAMES
    above. No fuzzy/substring matching anywhere: a catalog re-import that
    renames or adds a freeform group must not silently start or stop
    matching.
    """
    if row.get("group_type") != "freeform" or row.get("requires_manual_definition") is not True:
        return False
    if institution == CatalogInstitution.SMU:
        return (
            row.get("coursedog_rule_id") == TECHNICAL_ELECTIVE_RULE_ID
            and row.get("name") == TECHNICAL_ELECTIVE_NAME
        )
    if institution == CatalogInstitution.TAMU:
        return row.get("name") in TAMU_TECHNICAL_ELECTIVE_GROUP_NAMES
    return False
# 3 or 4 digits: SMU's catalog is exclusively 4-digit (CS 3341), TAMU's is
# exclusively 3-digit (CSCE 313) -- confirmed against both catalogs on disk,
# 3249/3249 SMU rows 4-digit, 0 TAMU rows 4-digit. A 4-digit-only pattern
# silently parsed every TAMU course code as invalid (returned None), which
# would have filtered TAMU out entirely regardless of the prefix/level rule
# below -- this was the numbering-scale gap the confirmed TAMU rule
# (course_level >= 300, not >= 3000) was pointing at.
_COURSE_CODE = re.compile(r"^([A-Z]{2,8})\s+(\d{3,4})$")


@dataclass(frozen=True)
class TechnicalElectiveRule:
    prefixes: tuple[str, ...]
    min_level: int


# Which department prefix(es) and minimum course_level count as a technical
# elective, per institution's own numbering convention -- SMU's "CS 3000+"
# and TAMU's "CSCE or ECEN 300+" are not directly comparable numbers (SMU's
# catalog runs roughly 1000-7000 per level-of-study; TAMU's runs 100-700), so
# this is keyed per institution rather than a single shared threshold. SMU's
# single-prefix case is the degenerate (len == 1) case of the same
# prefixes-tuple shape TAMU's two-prefix rule needs -- not a special case.
TECHNICAL_ELECTIVE_RULES: dict[CatalogInstitution, TechnicalElectiveRule] = {
    CatalogInstitution.SMU: TechnicalElectiveRule(prefixes=("CS",), min_level=3000),
    CatalogInstitution.TAMU: TechnicalElectiveRule(prefixes=("CSCE", "ECEN"), min_level=300),
}


class TechnicalElectiveEligibility(str, Enum):
    READY = "READY"
    PREREQUISITES_PLANNED = "PREREQUISITES_PLANNED"
    PREREQUISITES_MISSING = "PREREQUISITES_MISSING"


class TechnicalElectiveLimitation(str, Enum):
    ADVISER_APPROVAL_REQUIRED = "ADVISER_APPROVAL_REQUIRED"
    TRACK_EXCLUSION_NOT_EVALUATED = "TRACK_EXCLUSION_NOT_EVALUATED"
    CROSS_DEPARTMENT_EXCEPTIONS_NOT_INCLUDED = "CROSS_DEPARTMENT_EXCEPTIONS_NOT_INCLUDED"


class TechnicalElectiveCandidate(StrictModel):
    course_code: str
    title: str
    description: str
    credit_min: float = Field(ge=0)
    credit_max: float = Field(ge=0)
    eligibility: TechnicalElectiveEligibility
    satisfied_prerequisite_codes: list[str] = Field(default_factory=list)
    planned_prerequisite_codes: list[str] = Field(default_factory=list)
    missing_prerequisite_options: list[list[str]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    catalog_year: str
    source_url: str
    source_last_checked: str


class TechnicalElectiveCandidateStats(StrictModel):
    catalog_courses_considered: int = Field(ge=0)
    # Name predates institution-generalization; kept as-is (not renamed to
    # something institution-neutral) so the response contract -- and every
    # existing SMU consumer of this field name -- is unchanged. Counts
    # whichever institution's TECHNICAL_ELECTIVE_RULES prefixes/level
    # matched, not literally "CS 3000+" once this runs for TAMU too.
    cs_3000_plus_courses: int = Field(ge=0)
    excluded_already_used: int = Field(ge=0)
    excluded_zero_credit: int = Field(ge=0)
    excluded_restriction_or_review: int = Field(ge=0)
    candidate_count: int = Field(ge=0)


class TechnicalElectiveCandidateResult(StrictModel):
    student_id: str
    program_id: str
    requirement_group_id: str
    requirement_name: str
    credits_required: int = Field(ge=1)
    review_required: bool
    institution: CatalogInstitution
    catalog_year: str
    candidates: list[TechnicalElectiveCandidate]
    limitations: list[TechnicalElectiveLimitation]
    stats: TechnicalElectiveCandidateStats


def course_subject_and_number(course_code: str) -> tuple[str, int] | None:
    """Parse a canonical single course code; reject cross-list prose safely."""
    match = _COURSE_CODE.fullmatch(" ".join(course_code.upper().split()))
    return (match.group(1), int(match.group(2))) if match else None


def _candidate_prerequisite_state(
    course: CourseCatalogRecord,
    *,
    completed_or_in_progress: set[str],
    planned: set[str],
) -> tuple[TechnicalElectiveEligibility, list[str], list[str], list[list[str]], list[str]] | None:
    parsed = structured_prerequisite(course)
    # Permission, standing, major restrictions, and unresolved parser output
    # are not safe recommendation candidates. They are counted explicitly by
    # the caller rather than silently disappearing into the primary pool.
    if course.restrictions or parsed.restrictions or parsed.needs_review:
        return None

    satisfied: list[str] = []
    planned_matches: list[str] = []
    missing: list[list[str]] = []
    limitations: list[str] = []
    coreq = set(parsed.coreq_allowed)
    for clause in parsed.requires_all:
        completed_match = next(
            (code for code in clause.course_codes if code in completed_or_in_progress), None
        )
        if completed_match:
            satisfied.append(completed_match)
            continue
        planned_match = next((code for code in clause.course_codes if code in planned), None)
        if planned_match:
            planned_matches.append(planned_match)
            if planned_match in coreq:
                limitations.append(f"{planned_match} may be taken concurrently.")
            continue
        missing.append(sorted(clause.course_codes))

    # Pure corequisites do not occur in requires_all and must still be visible.
    required_codes = {code for clause in parsed.requires_all for code in clause.course_codes}
    for code in parsed.coreq_allowed:
        if code in required_codes or code in completed_or_in_progress:
            continue
        if code in planned:
            planned_matches.append(code)
            limitations.append(f"{code} must be completed earlier or taken concurrently.")
        else:
            missing.append([code])

    if missing:
        state = TechnicalElectiveEligibility.PREREQUISITES_MISSING
        limitations.append("One or more catalog prerequisites are not in the current academic plan.")
    elif planned_matches:
        state = TechnicalElectiveEligibility.PREREQUISITES_PLANNED
        limitations.append("Catalog prerequisites are present in the current academic plan.")
    else:
        state = TechnicalElectiveEligibility.READY
    return (
        state,
        sorted(set(satisfied)),
        sorted(set(planned_matches)),
        missing,
        list(dict.fromkeys(limitations)),
    )


def generate_technical_elective_candidates(
    *,
    student_id: str,
    program_id: str,
    requirement_group_id: str,
    requirement_name: str,
    catalog_year: str,
    institution: CatalogInstitution,
    catalog_courses: Iterable[CourseCatalogRecord],
    completed_or_in_progress_codes: Iterable[str],
    planned_or_selected_codes: Iterable[str],
) -> TechnicalElectiveCandidateResult:
    """Build a stable read-only pool; no course is selected or scheduled."""
    rule = TECHNICAL_ELECTIVE_RULES.get(institution)
    if rule is None:
        # A named, explicit failure rather than silently falling back to some
        # other institution's rule -- mirrors import_catalog.py's
        # subtrees_for(): a missing map entry is a bug to surface, not a
        # default to paper over.
        raise ValueError(f"no technical-elective rule configured for institution: {institution!r}")
    completed = set(completed_or_in_progress_codes)
    planned = set(planned_or_selected_codes)
    used = completed | planned
    considered = used_count = zero_credit_count = unsafe_count = cs_count = 0
    candidates: list[TechnicalElectiveCandidate] = []

    for course in catalog_courses:
        if course.institution != institution or course.catalog_year != catalog_year:
            continue
        considered += 1
        parsed_code = course_subject_and_number(course.course_code)
        if parsed_code is None or parsed_code[0] not in rule.prefixes or parsed_code[1] < rule.min_level:
            continue
        cs_count += 1
        if course.course_code in used:
            used_count += 1
            continue
        if course.credit_max <= 0:
            zero_credit_count += 1
            continue
        prerequisite_state = _candidate_prerequisite_state(
            course, completed_or_in_progress=completed, planned=planned
        )
        if prerequisite_state is None:
            unsafe_count += 1
            continue
        eligibility, satisfied, planned_matches, missing, limitations = prerequisite_state
        candidates.append(TechnicalElectiveCandidate(
            course_code=course.course_code,
            title=course.title,
            description=course.description,
            credit_min=course.credit_min,
            credit_max=course.credit_max,
            eligibility=eligibility,
            satisfied_prerequisite_codes=satisfied,
            planned_prerequisite_codes=planned_matches,
            missing_prerequisite_options=missing,
            limitations=limitations,
            catalog_year=course.catalog_year,
            source_url=course.source_url,
            source_last_checked=course.source_last_checked,
        ))

    state_order = {
        TechnicalElectiveEligibility.READY: 0,
        TechnicalElectiveEligibility.PREREQUISITES_PLANNED: 1,
        TechnicalElectiveEligibility.PREREQUISITES_MISSING: 2,
    }
    candidates.sort(key=lambda item: (
        state_order[item.eligibility], len(item.missing_prerequisite_options), item.course_code
    ))
    return TechnicalElectiveCandidateResult(
        student_id=student_id,
        program_id=program_id,
        requirement_group_id=requirement_group_id,
        requirement_name=requirement_name,
        credits_required=9,
        review_required=True,
        institution=institution,
        catalog_year=catalog_year,
        candidates=candidates,
        limitations=[
            TechnicalElectiveLimitation.ADVISER_APPROVAL_REQUIRED,
            TechnicalElectiveLimitation.TRACK_EXCLUSION_NOT_EVALUATED,
            TechnicalElectiveLimitation.CROSS_DEPARTMENT_EXCEPTIONS_NOT_INCLUDED,
        ],
        stats=TechnicalElectiveCandidateStats(
            catalog_courses_considered=considered,
            cs_3000_plus_courses=cs_count,
            excluded_already_used=used_count,
            excluded_zero_credit=zero_credit_count,
            excluded_restriction_or_review=unsafe_count,
            candidate_count=len(candidates),
        ),
    )
