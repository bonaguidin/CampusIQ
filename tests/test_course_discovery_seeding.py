from GradusIQ_career.course_discovery.models import CareerSkillNeed, EvidenceState
from GradusIQ_career.course_discovery.seeding import (
    MAX_SEED_CANDIDATES,
    SEED_RESULTS_PER_NEED,
    seed_candidates,
    seed_search_term,
)
from GradusIQ_career.course_discovery.selection import select_candidates_for_qualification
from GradusIQ_career.course_discovery.service import CourseDiscoveryService
from GradusIQ_career.course_discovery.tools import ReadOnlyCourseTools
from GradusIQ_career.evals.course_discovery_scenarios import COURSE_DISCOVERY_SCENARIOS
from GradusIQ_career.evals.live import build_course_discovery_context
from GradusIQ_career.course_discovery.needs import derive_career_skill_needs


def _need(skill, category="technology", state=EvidenceState.VERIFIED_LOCAL):
    return CareerSkillNeed(
        skill=skill, category=category, target_role="Software Engineering Intern",
        importance="required", evidence_state=state, evidence_source="O*NET test",
        confidence=0.8,
    )


def _tools(scenario_index=0):
    context = build_course_discovery_context(COURSE_DISCOVERY_SCENARIOS[scenario_index])
    return ReadOnlyCourseTools(CourseDiscoveryService(context)), context


def test_trusted_programming_need_seeds_real_catalog_targets():
    tools, _ = _tools()
    result = seed_candidates(tools, [_need("C")])
    assert seed_search_term(_need("C")) == "program"
    assert {"CSCE 110", "CSCE 206"} <= set(result.candidates)
    assert result.search_count == 1
    assert len(result.candidates) <= SEED_RESULTS_PER_NEED


def test_specific_technical_need_precedes_generic_ability():
    tools, _ = _tools()
    result = seed_candidates(
        tools, [_need("Critical Thinking", "abilities"), _need("C")], total_limit=5
    )
    assert {"CSCE 110", "CSCE 206"} <= set(result.candidates)
    assert "ANTH 409" not in result.candidates


def test_multiple_needs_merge_duplicates_and_obey_total_cap():
    tools, _ = _tools()
    first = _need("C")
    second = _need("program")
    result = seed_candidates(tools, [first, second], total_limit=10)
    assert len(result.candidates) == 5 <= MAX_SEED_CANDIDATES
    assert result.need_ids_by_course["CSCE 110"] == {first.need_id, second.need_id}


def test_only_verified_local_needs_authorize_seed_searches():
    tools, _ = _tools()
    result = seed_candidates(tools, [
        _need("program"),
        _need("BUS 301", state=EvidenceState.EXTERNAL_EVIDENCE_PRESENT),
        _need("SMU course", state=EvidenceState.NO_EVIDENCE),
    ])
    assert result.search_count == 1
    assert all(item.course.institution.value == "tamu" for item in result.candidates.values())


def test_excluded_adversarial_profile_text_never_becomes_a_seed_query():
    tools, context = _tools(5)
    queries = []
    original = tools.search_courses

    def recording_search(value):
        queries.append(value.query)
        return original(value)

    tools.search_courses = recording_search
    needs = derive_career_skill_needs(
        context.profile, COURSE_DISCOVERY_SCENARIOS[5].synthetic_input.target_roles[0]
    )
    seed_candidates(tools, needs)
    rendered = " ".join(queries).lower()
    assert "bus 301" not in rendered
    assert "ignore safeguards" not in rendered


def test_controlled_needs_seed_and_select_all_required_targets():
    tools, context = _tools()
    needs = derive_career_skill_needs(
        context.profile, COURSE_DISCOVERY_SCENARIOS[0].synthetic_input.target_roles[0]
    )
    result = seed_candidates(tools, needs)
    selected = {
        item.course.course_code
        for item in select_candidates_for_qualification(result.candidates, limit=8)
    }
    assert {"CSCE 110", "CSCE 206", "CSCE 331"} <= selected
    assert len(result.candidates) == MAX_SEED_CANDIDATES
