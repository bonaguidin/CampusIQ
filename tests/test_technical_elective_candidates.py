import re

from GradusIQ_career.course_discovery.models import CatalogInstitution, CourseCatalogRecord
from GradusIQ_career.course_discovery.technical_elective_candidates import (
    TAMU_TECHNICAL_ELECTIVE_GROUP_NAMES,
    TECHNICAL_ELECTIVE_NAME,
    TECHNICAL_ELECTIVE_RULE_ID,
    TechnicalElectiveEligibility,
    course_subject_and_number,
    generate_technical_elective_candidates,
    technical_elective_group_matches,
)


def _course(
    code, *, credits=3, prerequisites=None, restrictions=None, year="2026-2027",
    institution=CatalogInstitution.SMU,
):
    source_url = "https://catalog.smu.edu/" if institution == CatalogInstitution.SMU else "https://catalog.tamu.edu/"
    return CourseCatalogRecord(
        institution=institution,
        course_code=code,
        title=f"Title for {code}",
        description="",
        department=code.split()[0],
        credit_min=credits,
        credit_max=credits,
        course_level=int(code.split()[1][0]) * 100 if " " in code else None,
        prerequisite_text=prerequisites,
        prerequisite_courses=re.findall(r"[A-Z]{2,8}\s+\d{3,4}", prerequisites or ""),
        restrictions=restrictions or [],
        catalog_year=year,
        source_url=source_url,
        source_last_checked="2026-08-22",
    )


def _generate(courses, *, completed=(), planned=(), institution=CatalogInstitution.SMU):
    return generate_technical_elective_candidates(
        student_id="student", program_id="program", requirement_group_id="technical",
        requirement_name="Technical Electives (9 Credit Hours)", catalog_year="2026-2027",
        institution=institution, catalog_courses=courses,
        completed_or_in_progress_codes=completed, planned_or_selected_codes=planned,
    )


def test_course_number_parser_is_exact_and_safe():
    assert course_subject_and_number("CS 1341") == ("CS", 1341)
    assert course_subject_and_number("CS 2341") == ("CS", 2341)
    assert course_subject_and_number("CS 3341") == ("CS", 3341)
    assert course_subject_and_number("CS 4341") == ("CS", 4341)
    assert course_subject_and_number("CS 5341") == ("CS", 5341)
    assert course_subject_and_number(" cs   5323 ") == ("CS", 5323)
    assert course_subject_and_number("CS 4340/STAT 4340") is None
    # 3-digit is TAMU's real convention (CSCE 313), not a malformed SMU code --
    # both catalogs verified on disk to be exclusively one or the other.
    assert course_subject_and_number("CSCE 313") == ("CSCE", 313)
    assert course_subject_and_number("ECEN 449") == ("ECEN", 449)
    assert course_subject_and_number("CS 99") is None
    assert course_subject_and_number("CS 99999") is None


def test_filters_subject_level_year_credit_usage_and_manual_restrictions():
    result = _generate([
        _course("CS 2341"), _course("CS 3341"), _course("MATH 3304"),
        _course("CS 4000", credits=0), _course("CS 4390", restrictions=["Permission required"]),
        _course("CS 5000", year="2025-2026"),
    ], completed={"CS 3341"})
    assert result.candidates == []
    assert result.stats.cs_3000_plus_courses == 3
    assert result.stats.excluded_already_used == 1
    assert result.stats.excluded_zero_credit == 1
    assert result.stats.excluded_restriction_or_review == 1


def test_prerequisite_states_and_order_are_deterministic():
    result = _generate([
        _course("CS 5002", prerequisites="Prerequisite: CS 4002."),
        _course("CS 5001"),
        _course("CS 5003", prerequisites="Prerequisite: CS 4003."),
    ], completed={"CS 4002"}, planned={"CS 4003"})
    assert [item.course_code for item in result.candidates] == ["CS 5001", "CS 5002", "CS 5003"]
    assert [item.eligibility for item in result.candidates] == [
        TechnicalElectiveEligibility.READY,
        TechnicalElectiveEligibility.READY,
        TechnicalElectiveEligibility.PREREQUISITES_PLANNED,
    ]
    assert result.candidates[2].planned_prerequisite_codes == ["CS 4003"]


def test_missing_prerequisite_is_visible_and_not_auto_added():
    result = _generate([_course("CS 5004", prerequisites="Prerequisite: CS 4004 or CS 4005.")])
    candidate = result.candidates[0]
    assert candidate.eligibility == TechnicalElectiveEligibility.PREREQUISITES_MISSING
    assert candidate.missing_prerequisite_options == [["CS 4004", "CS 4005"]]
    assert result.stats.candidate_count == 1


def test_order_is_stable_across_input_order():
    courses = [_course("CS 5003"), _course("CS 5001"), _course("CS 5002")]
    forward = _generate(courses)
    reverse = _generate(reversed(courses))
    assert [item.course_code for item in forward.candidates] == ["CS 5001", "CS 5002", "CS 5003"]
    assert forward == reverse


# ── SMU output pinned exactly, to prove the institution-generalization
# refactor (SMU -> per-institution TECHNICAL_ELECTIVE_RULES) changes nothing
# about SMU's own behavior. ──────────────────────────────────────────────────

def test_smu_output_is_unchanged_by_the_institution_generalization():
    result = _generate([
        _course("CS 2341"), _course("CS 3341"), _course("CS 4341"),
        _course("MATH 3304"), _course("CSCE 313", institution=CatalogInstitution.TAMU),
    ], completed={"CS 3341"}, institution=CatalogInstitution.SMU)
    assert result.institution == CatalogInstitution.SMU
    assert [item.course_code for item in result.candidates] == ["CS 4341"]
    assert result.credits_required == 9
    assert result.review_required is True
    assert result.stats.model_dump() == {
        "catalog_courses_considered": 4,
        "cs_3000_plus_courses": 2,
        "excluded_already_used": 1,
        "excluded_zero_credit": 0,
        "excluded_restriction_or_review": 0,
        "candidate_count": 1,
    }


# ── TAMU: CSCE/ECEN 300+, a genuinely different numbering scale from SMU's
# CS 3000+ (not the same threshold on a different school's courses). ────────

def test_tamu_includes_csce_and_ecen_at_or_above_300():
    result = _generate([
        _course("CSCE 313", institution=CatalogInstitution.TAMU),
        _course("ECEN 449", institution=CatalogInstitution.TAMU),
        _course("CSCE 481", institution=CatalogInstitution.TAMU),
    ], institution=CatalogInstitution.TAMU)
    assert result.institution == CatalogInstitution.TAMU
    assert {item.course_code for item in result.candidates} == {"CSCE 313", "ECEN 449", "CSCE 481"}


def test_tamu_excludes_below_300_and_outside_csce_ecen():
    result = _generate([
        _course("CSCE 121", institution=CatalogInstitution.TAMU),  # below threshold
        _course("MATH 311", institution=CatalogInstitution.TAMU),  # wrong prefix
        _course("CSCE 314", institution=CatalogInstitution.TAMU),  # eligible
    ], institution=CatalogInstitution.TAMU)
    assert [item.course_code for item in result.candidates] == ["CSCE 314"]
    assert result.stats.cs_3000_plus_courses == 1


def test_tamu_excludes_courses_already_claimed_elsewhere_in_the_plan():
    result = _generate([
        _course("CSCE 314", institution=CatalogInstitution.TAMU),
        _course("ECEN 449", institution=CatalogInstitution.TAMU),
    ], planned={"CSCE 314"}, institution=CatalogInstitution.TAMU)
    assert [item.course_code for item in result.candidates] == ["ECEN 449"]
    assert result.stats.excluded_already_used == 1


def test_tamu_courses_do_not_leak_into_an_smu_pool_or_vice_versa():
    # A catalog list can legitimately hold rows from both institutions (the
    # caller filters by state.catalog_institution upstream, but the module's
    # own institution filter is the real guarantee) -- the institution field
    # on each row, not which _generate() call it happens to be passed to, is
    # what must gate inclusion.
    mixed = [
        _course("CS 3341", institution=CatalogInstitution.SMU),
        _course("CSCE 314", institution=CatalogInstitution.TAMU),
    ]
    smu_result = _generate(mixed, institution=CatalogInstitution.SMU)
    tamu_result = _generate(mixed, institution=CatalogInstitution.TAMU)
    assert [item.course_code for item in smu_result.candidates] == ["CS 3341"]
    assert [item.course_code for item in tamu_result.candidates] == ["CSCE 314"]


# ── technical_elective_group_matches: institution-keyed route matching.
# Explicit allowlist, no fuzzy/substring matching. ──────────────────────────

def _group_row(name, *, coursedog_rule_id=None, group_type="freeform", requires_manual_definition=True):
    return {
        "id": f"gid-{name}",
        "name": name,
        "coursedog_rule_id": coursedog_rule_id,
        "group_type": group_type,
        "requires_manual_definition": requires_manual_definition,
        "catalog_year": "2026-2027",
    }


def test_smu_matching_is_unchanged_exact_rule_id_and_name():
    matching = _group_row(TECHNICAL_ELECTIVE_NAME, coursedog_rule_id=TECHNICAL_ELECTIVE_RULE_ID)
    assert technical_elective_group_matches(matching, CatalogInstitution.SMU) is True
    # Right name, wrong (or missing) rule id -- still rejected, matching the
    # pre-existing SMU behavior exactly.
    wrong_rule_id = _group_row(TECHNICAL_ELECTIVE_NAME, coursedog_rule_id="not-the-real-id")
    assert technical_elective_group_matches(wrong_rule_id, CatalogInstitution.SMU) is False
    # Right rule id, wrong name -- also rejected.
    wrong_name = _group_row("Some Other Group", coursedog_rule_id=TECHNICAL_ELECTIVE_RULE_ID)
    assert technical_elective_group_matches(wrong_name, CatalogInstitution.SMU) is False


def test_tamu_matches_all_three_confirmed_elective_group_names():
    assert TAMU_TECHNICAL_ELECTIVE_GROUP_NAMES == {
        "Fourth Year — Fall — Area elective",
        "Fourth Year — Fall — Engineering elective",
        "Fourth Year — Spring — Area elective",
    }
    for name in TAMU_TECHNICAL_ELECTIVE_GROUP_NAMES:
        assert technical_elective_group_matches(_group_row(name), CatalogInstitution.TAMU) is True


def test_tamu_non_elective_freeform_groups_do_not_match():
    non_elective_names = [
        "First Year — Fall — University Core Curriculum",
        "First Year — Spring — University Core Curriculum",
        "Third Year — Spring — University Core Curriculum",
        "Fourth Year — Fall — Senior design",
        "Fourth Year — Fall — University Core Curriculum",
        "Fourth Year — Spring — Senior Design",
        "Fourth Year — Spring — University Core Curriculum",
    ]
    for name in non_elective_names:
        assert technical_elective_group_matches(_group_row(name), CatalogInstitution.TAMU) is False


def test_matching_still_requires_freeform_and_manual_definition_for_both_institutions():
    # A row with an otherwise-matching name/rule_id that isn't actually a
    # freeform, manually-defined group must never match -- this predates the
    # institution split and must hold for both.
    smu_row = _group_row(TECHNICAL_ELECTIVE_NAME, coursedog_rule_id=TECHNICAL_ELECTIVE_RULE_ID, group_type="structured")
    assert technical_elective_group_matches(smu_row, CatalogInstitution.SMU) is False
    tamu_row = _group_row("Fourth Year — Fall — Area elective", requires_manual_definition=False)
    assert technical_elective_group_matches(tamu_row, CatalogInstitution.TAMU) is False


def test_no_institution_matches_anything_by_accident():
    # An institution with no configured allowlist (there is none today besides
    # SMU/TAMU, but this guards the fallthrough branch) matches nothing.
    row = _group_row("Fourth Year — Fall — Area elective")
    assert technical_elective_group_matches(row, None) is False
