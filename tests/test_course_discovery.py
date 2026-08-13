import inspect
import json

import pytest
from pydantic import ValidationError

from GradusIQ_career.course_discovery.catalog import LocalCatalogRepository, _catalogs
from GradusIQ_career.course_discovery.evidence import (
    GapFieldClassification,
    career_needs_from_gap_output,
    classify_gap_output_fields,
)
from GradusIQ_career.course_discovery.models import (
    CareerSkillNeed,
    CatalogInstitution,
    CourseCodeInput,
    CourseDiscoveryContext,
    CourseEligibilityStatus,
    CourseSearchQuery,
    EvidenceState,
    PlannedCourseEvidence,
    PrerequisiteMode,
    PrerequisiteStatus,
    SearchCoursesInput,
    StudentCourseState,
    VerificationDisposition,
    canonical_course_code,
)
from GradusIQ_career.course_discovery.prerequisites import prerequisite_requirement
from GradusIQ_career.course_discovery.service import CourseDiscoveryService
from GradusIQ_career.course_discovery.tools import ReadOnlyCourseTools
from GradusIQ_career.student_intelligence_profile import StudentIntelligenceProfile
from tests.test_ai_runtime_chat import canonical_profile


def context(*, courses=(), planned=(), exclusions=(), institution=CatalogInstitution.TAMU):
    profile_payload = canonical_profile().model_dump(mode="json")
    institution_id = f"institution-{institution.value}"
    profile_payload["institution"] = {
        "id": institution_id,
        "name": (
            "Texas A&M University" if institution == CatalogInstitution.TAMU
            else "Southern Methodist University"
        ),
        "relationship": "home",
    }
    profile_payload["academics"]["courses"] = [
        {
            "id": course_id,
            "institution_id": institution_id,
            "course_code": code,
            "title": code,
            "credit_hours": 3,
            "letter_grade": "A" if status == "completed" else None,
            "credit_type": "resident",
            "status": status,
            "source": "synthetic_test",
        }
        for course_id, code, status in courses
    ]
    profile_payload["academics"]["repeat_exclusions"] = [
        {
            "excluded_course_id": excluded,
            "superseded_by_course_id": replacement,
        }
        for excluded, replacement in exclusions
    ]
    return CourseDiscoveryContext(
        profile=StudentIntelligenceProfile.model_validate(profile_payload),
        institution=institution,
        planned_courses=[
            PlannedCourseEvidence(
                id=planned_id, institution=institution, course_code=code
            )
            for planned_id, code in planned
        ],
    )


@pytest.fixture(scope="module")
def catalog():
    return LocalCatalogRepository()


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("CSCE 221", "CSCE 221"),
        ("CSCE-221", "CSCE 221"),
        ("csce 221", "CSCE 221"),
        ("CSCE221", "CSCE 221"),
        ("Principles of Management", None),
    ),
)
def test_course_identifier_normalization(raw, expected):
    assert canonical_course_code(raw) == expected


def test_catalog_lookup_is_institution_scoped_and_provenance_backed(catalog):
    tamu = catalog.get(CatalogInstitution.TAMU, "csce-221")
    smu = catalog.get(CatalogInstitution.SMU, "CS 2341")
    assert tamu and tamu.title == "Data Structures and Algorithms"
    assert smu and smu.title == "Data Structures"
    assert catalog.get(CatalogInstitution.SMU, "CSCE 221") is None
    assert tamu.provenance.catalog_year == "2026-2027"
    assert tamu.provenance.source_url.startswith("https://catalog.tamu.edu/")
    assert tamu.provenance.source_last_checked


def test_catalog_counts_coverage_and_cache_are_real(catalog):
    assert catalog.count(CatalogInstitution.TAMU) == 2565
    assert catalog.count(CatalogInstitution.SMU) == 3249
    coverage = catalog.prerequisite_coverage(CatalogInstitution.TAMU)
    assert coverage.prerequisite_text_courses == 2312
    assert coverage.parsed_course_code_courses == 1551
    assert coverage.parsed_restriction_courses == 1791
    before = _catalogs.cache_info().hits
    second = LocalCatalogRepository()
    assert second.get(CatalogInstitution.TAMU, "CSCE 221") is catalog.get(
        CatalogInstitution.TAMU, "CSCE 221"
    )
    assert _catalogs.cache_info().hits > before


def test_search_supports_code_title_description_scope_and_bounds(catalog):
    exact = catalog.search(CourseSearchQuery(
        institution=CatalogInstitution.TAMU, query="CSCE-221", limit=5
    ))
    title = catalog.search(CourseSearchQuery(
        institution=CatalogInstitution.TAMU, query="data structures", limit=5
    ))
    description = catalog.search(CourseSearchQuery(
        institution=CatalogInstitution.TAMU, query="Python", limit=3
    ))
    assert exact[0].course.course_code == "CSCE 221"
    assert any(item.course.course_code == "CSCE 221" for item in title)
    assert description and len(description) <= 3
    assert all(item.course.institution == CatalogInstitution.TAMU for item in description)


def test_existence_verifier_rejects_fabricated_and_free_form_courses(catalog):
    assert catalog.verify_course_exists(
        CatalogInstitution.TAMU, "CSCE 221"
    ).status.value == "EXISTS"
    assert catalog.verify_course_exists(
        CatalogInstitution.TAMU, "BUS 301"
    ).status.value == "NOT_FOUND"
    assert catalog.verify_course_exists(
        CatalogInstitution.TAMU, "Principles of Management"
    ).status.value == "NOT_FOUND"


@pytest.mark.parametrize(
    ("courses", "planned", "code", "expected"),
    (
        ((("done", "CSCE 110", "completed"),), (), "CSCE 110", StudentCourseState.COMPLETED),
        ((("active", "CSCE 110", "in_progress"),), (), "CSCE 110", StudentCourseState.IN_PROGRESS),
        ((), (("plan", "CSCE 110"),), "CSCE 110", StudentCourseState.PLANNED),
        ((), (), "CSCE 110", StudentCourseState.NOT_TAKEN),
        ((), (), "BUS 301", StudentCourseState.UNKNOWN),
    ),
)
def test_student_course_status(courses, planned, code, expected):
    service = CourseDiscoveryService(context(courses=courses, planned=planned))
    assert service.student_course_status(code).state == expected


def test_repeat_exclusion_does_not_erase_completed_course_history():
    service = CourseDiscoveryService(context(
        courses=(
            ("old", "CSCE 110", "completed"),
            ("new", "CSCE 110", "completed"),
        ),
        exclusions=(("old", "new"),),
    ))
    status = service.student_course_status("CSCE 110")
    assert status.state == StudentCourseState.COMPLETED
    assert status.repeat_excluded_record_ids == ["old"]


def test_wrong_institution_history_is_not_used():
    ctx = context(courses=(("foreign", "CSCE 110", "completed"),))
    payload = ctx.model_dump(mode="json")
    payload["profile"]["academics"]["courses"][0]["institution_id"] = "other-school"
    service = CourseDiscoveryService(CourseDiscoveryContext.model_validate(payload))
    assert service.student_course_status("CSCE 110").state == StudentCourseState.NOT_TAKEN


def test_single_and_or_prerequisite_shapes(catalog):
    single = prerequisite_requirement(catalog.get(CatalogInstitution.SMU, "CEE 2321"))
    both = prerequisite_requirement(catalog.get(CatalogInstitution.TAMU, "FINC 446"))
    either = prerequisite_requirement(catalog.get(CatalogInstitution.TAMU, "ACCT 210"))
    assert single.mode == PrerequisiteMode.ALL and single.course_codes == ["CHEM 1303"]
    assert both.mode == PrerequisiteMode.ALL and both.course_codes == ["FINC 351", "FINC 361"]
    assert either.mode == PrerequisiteMode.ANY and either.course_codes == ["ACCT 209", "ACCT 229"]


def test_and_prerequisites_require_all_courses():
    eligible = CourseDiscoveryService(context(courses=(
        ("a", "FINC 351", "completed"), ("b", "FINC 361", "completed"),
    ))).check_eligibility("FINC 446")
    missing = CourseDiscoveryService(context(courses=(
        ("a", "FINC 351", "completed"),
    ))).check_eligibility("FINC 446")
    assert eligible.status == CourseEligibilityStatus.ELIGIBLE
    assert missing.status == CourseEligibilityStatus.INELIGIBLE
    assert missing.prerequisite_evaluation.missing_courses == ["FINC 361"]


def test_or_prerequisites_accept_either_course():
    result = CourseDiscoveryService(context(courses=(
        ("a", "ACCT 229", "completed"),
    ))).check_eligibility("ACCT 210")
    assert result.status == CourseEligibilityStatus.ELIGIBLE
    assert result.prerequisite_evaluation.status == PrerequisiteStatus.ELIGIBLE


def test_planned_prerequisite_is_not_satisfied_and_in_progress_is_unresolved():
    planned = CourseDiscoveryService(context(
        planned=(("plan", "FINC 351"),),
        courses=(("b", "FINC 361", "completed"),),
    )).check_eligibility("FINC 446")
    active = CourseDiscoveryService(context(courses=(
        ("a", "FINC 351", "in_progress"),
        ("b", "FINC 361", "completed"),
    ))).check_eligibility("FINC 446")
    assert planned.status == CourseEligibilityStatus.INELIGIBLE
    assert planned.prerequisite_evaluation.planned_courses == ["FINC 351"]
    assert active.status == CourseEligibilityStatus.UNRESOLVED
    assert active.prerequisite_evaluation.in_progress_courses == ["FINC 351"]


def test_unsupported_restriction_and_mixed_logic_are_unresolved(catalog):
    restricted = CourseDiscoveryService(context(courses=(
        ("a", "ACCT 229", "completed"),
    ))).check_eligibility("ACCT 230")
    mixed = prerequisite_requirement(catalog.get(CatalogInstitution.TAMU, "CSCE 221"))
    assert restricted.status == CourseEligibilityStatus.UNRESOLVED
    assert mixed.mode == PrerequisiteMode.UNRESOLVED
    assert mixed.unresolved_reasons


def test_natural_language_prerequisite_without_parsed_codes_is_unresolved(catalog):
    requirement = prerequisite_requirement(catalog.get(CatalogInstitution.TAMU, "ACCT 200"))
    assert requirement.mode == PrerequisiteMode.UNRESOLVED
    assert requirement.course_codes == []
    assert any("no safely parsed" in reason for reason in requirement.unresolved_reasons)


def test_valid_smu_course_eligibility_uses_smu_history_only():
    service = CourseDiscoveryService(context(
        institution=CatalogInstitution.SMU,
        courses=(("chem", "CHEM 1303", "completed"),),
    ))
    result = service.check_eligibility("CEE 2321")
    assert result.status == CourseEligibilityStatus.ELIGIBLE
    assert result.provenance.institution == CatalogInstitution.SMU


@pytest.mark.parametrize(
    ("courses", "planned", "code", "expected"),
    (
        ((), (), "CSCE 110", CourseEligibilityStatus.ELIGIBLE),
        ((("done", "CSCE 110", "completed"),), (), "CSCE 110", CourseEligibilityStatus.ALREADY_COMPLETED),
        ((("active", "CSCE 110", "in_progress"),), (), "CSCE 110", CourseEligibilityStatus.IN_PROGRESS),
        ((), (("plan", "CSCE 110"),), "CSCE 110", CourseEligibilityStatus.ALREADY_PLANNED),
        ((), (), "BUS 301", CourseEligibilityStatus.COURSE_NOT_FOUND),
        ((), (), "CS 2341", CourseEligibilityStatus.WRONG_INSTITUTION),
    ),
)
def test_course_eligibility_final_states(courses, planned, code, expected):
    result = CourseDiscoveryService(context(courses=courses, planned=planned)).check_eligibility(code)
    assert result.status == expected
    assert result.reasons
    assert result.degree_applicability == result.offering_status == "UNKNOWN"


def test_final_verifier_accepts_rejects_and_flags():
    service = CourseDiscoveryService(context())
    assert service.verify_final_recommendation("CSCE 110").disposition == VerificationDisposition.ACCEPT
    assert service.verify_final_recommendation("BUS 301").disposition == VerificationDisposition.REJECT
    assert service.verify_final_recommendation("CSCE 221").disposition == VerificationDisposition.FLAG


@pytest.mark.parametrize(
    "skill",
    ("program design", "Python", "embedded systems", "data structures", "technical communication"),
)
def test_candidate_discovery_is_catalog_backed_with_status_and_eligibility(skill):
    service = CourseDiscoveryService(context())
    need = CareerSkillNeed(
        skill=skill,
        target_role="Synthetic Role",
        importance="required",
        evidence_state=EvidenceState.VERIFIED_LOCAL,
        evidence_source="local deterministic role requirements",
    )
    candidates = service.discover_candidates(need, limit=5)
    assert candidates
    assert len(candidates) <= 5
    assert all(candidate.search_result.course.provenance.source_url for candidate in candidates)
    assert all(candidate.eligibility.reasons for candidate in candidates)


def test_candidate_discovery_retains_completed_and_planned_status():
    need = CareerSkillNeed(
        skill="CSCE 110", target_role="Software Engineering Intern",
        importance="required", evidence_state=EvidenceState.VERIFIED_LOCAL,
        evidence_source="local role grounding",
    )
    completed = CourseDiscoveryService(context(courses=(
        ("done", "CSCE 110", "completed"),
    ))).discover_candidates(need, limit=10)
    planned = CourseDiscoveryService(context(planned=(
        ("plan", "CSCE 110"),
    ))).discover_candidates(need, limit=10)
    assert any(item.student_status.state == StudentCourseState.COMPLETED for item in completed)
    assert any(item.student_status.state == StudentCourseState.PLANNED for item in planned)


def test_no_evidence_needs_do_not_become_course_authority():
    service = CourseDiscoveryService(context())
    need = CareerSkillNeed(
        skill="current market trend", target_role="Analyst",
        importance="exploratory", evidence_state=EvidenceState.NO_EVIDENCE,
        evidence_source="research_status:no_evidence",
    )
    assert service.discover_candidates(need) == []


def test_gap_narrative_boundary_rejects_b2r_failures():
    gap = {
        "must_have_gaps": [{"gap": "customer service", "why_it_matters": "current research"}],
        "recommended_next_steps": [
            "Take BUS 301 by Fall 2024", "Take Principles of Management",
        ],
        "readiness_score": 3,
    }
    assert career_needs_from_gap_output(gap) == ()
    mapping = classify_gap_output_fields()
    assert mapping["must_have_gaps"] == GapFieldClassification.UNVERIFIED_NARRATIVE
    assert mapping["recommended_next_steps"] == GapFieldClassification.COURSE_CERT_RECOMMENDATION
    assert "BUS 301" not in json.dumps(career_needs_from_gap_output(gap))


def test_read_only_tools_are_trusted_scope_bounded_and_strict():
    service = CourseDiscoveryService(context())
    tools = ReadOnlyCourseTools(service, monotonic=lambda: 1.0)
    assert len(tools.search_courses(SearchCoursesInput(query="data", limit=2)).results) <= 2
    assert tools.get_course(CourseCodeInput(course_code="CSCE 110")).course
    assert tools.get_student_course_status(
        CourseCodeInput(course_code="CSCE 110")
    ).student_status.state == StudentCourseState.NOT_TAKEN
    assert tools.check_course_eligibility(
        CourseCodeInput(course_code="CSCE 110")
    ).eligibility.status == CourseEligibilityStatus.ELIGIBLE
    with pytest.raises(ValidationError):
        CourseCodeInput.model_validate({"course_code": "CSCE 110", "student_id": "other"})
    public_methods = {
        name for name, value in inspect.getmembers(ReadOnlyCourseTools, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == {
        "search_courses", "get_course", "get_student_course_status",
        "check_course_eligibility",
    }
    assert all("student_id" not in inspect.signature(getattr(ReadOnlyCourseTools, name)).parameters
               for name in public_methods)


def test_context_rejects_mismatched_home_institution():
    payload = context().model_dump(mode="json")
    payload["institution"] = "smu"
    with pytest.raises(ValidationError, match="home institution"):
        CourseDiscoveryContext.model_validate(payload)


def test_eight_deterministic_c1_scenarios():
    need = CareerSkillNeed(
        skill="CSCE 110", target_role="Software Engineering Intern",
        importance="required", evidence_state=EvidenceState.VERIFIED_LOCAL,
        evidence_source="local role grounding",
    )
    cases = {
        "eligible": CourseDiscoveryService(context()).check_eligibility("CSCE 110").status,
        "completed": CourseDiscoveryService(context(courses=(
            ("done", "CSCE 110", "completed"),
        ))).discover_candidates(need, 5)[0].student_status.state,
        "planned": CourseDiscoveryService(context(planned=(
            ("plan", "CSCE 110"),
        ))).discover_candidates(need, 5)[0].student_status.state,
        "unmet_prerequisite": CourseDiscoveryService(context()).check_eligibility("FINC 446").status,
        "ambiguous_restriction": CourseDiscoveryService(context()).check_eligibility("ACCT 230").status,
        "fabricated_code": CourseDiscoveryService(context()).check_eligibility("BUS 301").status,
        "generic_name": CourseDiscoveryService(context()).check_eligibility("Principles of Management").status,
        "wrong_institution": CourseDiscoveryService(context()).check_eligibility("CS 2341").status,
    }
    assert cases == {
        "eligible": CourseEligibilityStatus.ELIGIBLE,
        "completed": StudentCourseState.COMPLETED,
        "planned": StudentCourseState.PLANNED,
        "unmet_prerequisite": CourseEligibilityStatus.INELIGIBLE,
        "ambiguous_restriction": CourseEligibilityStatus.UNRESOLVED,
        "fabricated_code": CourseEligibilityStatus.COURSE_NOT_FOUND,
        "generic_name": CourseEligibilityStatus.COURSE_NOT_FOUND,
        "wrong_institution": CourseEligibilityStatus.WRONG_INSTITUTION,
    }
