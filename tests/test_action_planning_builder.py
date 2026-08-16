import pytest

from GradusIQ_career.action_planning.builder import (
    build_action_plan,
    course_node_id,
    detect_cycles,
    skill_need_node_id,
)
from GradusIQ_career.action_planning.models import PlanEdge, PlanNode, UnifiedActionPlan
from GradusIQ_career.course_discovery.agent_models import (
    CourseDiscoveryResult,
    PrerequisiteBlockedCourse,
    UnresolvedCourseCandidate,
    VerifiedCourseRecommendation,
)
from GradusIQ_career.course_discovery.models import (
    CareerSkillNeed,
    CatalogInstitution,
    CatalogProvenance,
    CourseEligibilityStatus,
    EvidenceState,
    MatchKind,
    PrerequisiteEvaluation,
    PrerequisiteMode,
    PrerequisiteRequirement,
    PrerequisiteStatus,
    StudentCourseState,
)


def skill_need(skill="Python", target_role="Software Engineering Intern", category="skills"):
    return CareerSkillNeed(
        skill=skill,
        category=category,
        target_role=target_role,
        importance="required",
        evidence_state=EvidenceState.VERIFIED_LOCAL,
        evidence_source="O*NET 15-1252.00 onet",
    )


def provenance(course_code="CSCE 206"):
    return CatalogProvenance(
        institution=CatalogInstitution.TAMU,
        course_code=course_code,
        catalog_year="2026-2027",
        source_url="https://catalog.tamu.edu/undergraduate/course-descriptions/csce/",
        source_last_checked="2026-06-20",
    )


def verified(
    course_code="CSCE 206",
    matched_needs=None,
    student_status=StudentCourseState.NOT_TAKEN,
    institution=CatalogInstitution.TAMU,
):
    return VerifiedCourseRecommendation(
        institution=institution,
        course_code=course_code,
        title="Structured Programming in C",
        description="Programming fundamentals.",
        credit_min=4.0,
        credit_max=4.0,
        matched_needs=matched_needs or [],
        match_kinds=[MatchKind.TITLE],
        matched_terms=["program"],
        student_status=student_status,
        prerequisite_status=PrerequisiteStatus.ELIGIBLE,
        eligibility_status=CourseEligibilityStatus.ELIGIBLE,
        provenance=provenance(course_code),
        ranking_reason="Direct match.",
        skill_alignment_explanation="Covers the need directly.",
    )


def unresolved(course_code="BUS 301", matched_needs=None):
    return UnresolvedCourseCandidate(
        institution=CatalogInstitution.TAMU,
        course_code=course_code,
        title="Unresolved course",
        matched_needs=matched_needs or [],
        match_kinds=[MatchKind.TITLE],
        eligibility_status=CourseEligibilityStatus.UNRESOLVED,
        reasons=["ambiguous restriction"],
        provenance=provenance(course_code),
    )


def all_mode_evaluation(
    required_codes,
    *,
    missing=(),
    in_progress=(),
    planned=(),
    satisfied=(),
    unknown=(),
    status=PrerequisiteStatus.INELIGIBLE,
):
    return PrerequisiteEvaluation(
        status=status,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.ALL, course_codes=list(required_codes)),
        satisfied_courses=list(satisfied),
        missing_courses=list(missing),
        in_progress_courses=list(in_progress),
        planned_courses=list(planned),
        unknown_courses=list(unknown),
        reasons=["test fixture"],
    )


def any_mode_evaluation(required_codes, *, missing=()):
    return PrerequisiteEvaluation(
        status=PrerequisiteStatus.INELIGIBLE,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.ANY, course_codes=list(required_codes)),
        missing_courses=list(missing),
        reasons=["test fixture"],
    )


def unresolved_mode_evaluation():
    return PrerequisiteEvaluation(
        status=PrerequisiteStatus.UNRESOLVED,
        requirement=PrerequisiteRequirement(
            mode=PrerequisiteMode.UNRESOLVED, unresolved_reasons=["mixed AND/OR grouping"],
        ),
        reasons=["test fixture"],
    )


def blocked(course_code, evaluation, *, matched_needs=None, institution=CatalogInstitution.TAMU):
    return PrerequisiteBlockedCourse(
        institution=institution,
        course_code=course_code,
        title=f"{course_code} title",
        matched_needs=matched_needs or [],
        match_kinds=[MatchKind.TITLE],
        eligibility_status=CourseEligibilityStatus.INELIGIBLE,
        prerequisite_status=evaluation.status,
        prerequisite_evaluation=evaluation,
        provenance=provenance(course_code),
    )


def discovery_result(
    target_role, career_needs, verified_recs=None, unresolved_recs=None, blocked_recs=None,
):
    return CourseDiscoveryResult(
        target_role=target_role,
        current_major="Computer Science",
        intended_major="Data Engineering",
        career_needs=career_needs,
        verified_recommendations=verified_recs or [],
        requires_verification=unresolved_recs or [],
        prerequisite_blocked=blocked_recs or [],
        summary="Test fixture.",
    )


TARGET_ROLE = "Software Engineering Intern"


# --- empty inputs -------------------------------------------------------------

def test_empty_inputs_produce_valid_empty_success_plan():
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[], course_discovery_result=None)
    assert plan.execution_status == "SUCCESS"
    assert plan.nodes == [] and plan.edges == [] and plan.conflicts == []
    assert isinstance(plan, UnifiedActionPlan)


# --- one need + one matching verified course -----------------------------------

def test_one_skill_need_with_one_matching_verified_course():
    need = skill_need()
    course = verified(matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    assert plan.execution_status == "SUCCESS"
    node_types = {node.node_id: node.node_type for node in plan.nodes}
    assert node_types == {
        skill_need_node_id(need.need_id): "skill_need",
        course_node_id(CatalogInstitution.TAMU, "CSCE 206"): "course",
    }
    assert len(plan.edges) == 1
    edge = plan.edges[0]
    assert edge.relation == "satisfies"
    assert edge.from_node_id == course_node_id(CatalogInstitution.TAMU, "CSCE 206")
    assert edge.to_node_id == skill_need_node_id(need.need_id)


# --- one course satisfying multiple needs --------------------------------------

def test_one_course_satisfying_multiple_needs_produces_one_course_node_and_two_edges():
    need_a = skill_need(skill="Python")
    need_b = skill_need(skill="Critical Thinking", category="skills")
    course = verified(matched_needs=[need_a, need_b])
    result = discovery_result(TARGET_ROLE, [need_a, need_b], verified_recs=[course])
    plan = build_action_plan(
        target_role=TARGET_ROLE, skill_needs=[need_a, need_b], course_discovery_result=result
    )

    course_nodes = [node for node in plan.nodes if node.node_type == "course"]
    assert len(course_nodes) == 1
    assert len(plan.edges) == 2
    assert {edge.to_node_id for edge in plan.edges} == {
        skill_need_node_id(need_a.need_id),
        skill_need_node_id(need_b.need_id),
    }
    assert all(edge.from_node_id == course_nodes[0].node_id for edge in plan.edges)


# --- multiple courses satisfying one need --------------------------------------

def test_multiple_courses_satisfying_one_need_produces_two_course_nodes():
    need = skill_need()
    course_a = verified(course_code="CSCE 110", matched_needs=[need])
    course_b = verified(course_code="CSCE 206", matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course_a, course_b])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    course_nodes = {node.node_id for node in plan.nodes if node.node_type == "course"}
    assert course_nodes == {
        course_node_id(CatalogInstitution.TAMU, "CSCE 110"),
        course_node_id(CatalogInstitution.TAMU, "CSCE 206"),
    }
    assert len(plan.edges) == 2
    assert all(edge.to_node_id == skill_need_node_id(need.need_id) for edge in plan.edges)


# --- duplicate inputs don't create duplicate nodes -----------------------------

def test_duplicate_skill_need_input_does_not_duplicate_node():
    need = skill_need()
    duplicate = skill_need()  # identical content -> identical need_id
    assert need.need_id == duplicate.need_id
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need, duplicate], course_discovery_result=None)
    assert len(plan.nodes) == 1


def test_duplicate_verified_course_input_does_not_duplicate_node():
    need = skill_need()
    course = verified(matched_needs=[need])
    duplicate_course = verified(matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course, duplicate_course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    course_nodes = [node for node in plan.nodes if node.node_type == "course"]
    assert len(course_nodes) == 1
    assert len(plan.edges) == 1


# --- deterministic ordering + stable IDs ---------------------------------------

def test_output_is_deterministic_regardless_of_input_ordering():
    need_a = skill_need(skill="Python")
    need_b = skill_need(skill="Git")
    course_a = verified(course_code="CSCE 110", matched_needs=[need_a])
    course_b = verified(course_code="CSCE 206", matched_needs=[need_b])

    result_forward = discovery_result(TARGET_ROLE, [need_a, need_b], verified_recs=[course_a, course_b])
    result_reversed = discovery_result(TARGET_ROLE, [need_b, need_a], verified_recs=[course_b, course_a])

    plan_forward = build_action_plan(
        target_role=TARGET_ROLE, skill_needs=[need_a, need_b], course_discovery_result=result_forward
    )
    plan_reversed = build_action_plan(
        target_role=TARGET_ROLE, skill_needs=[need_b, need_a], course_discovery_result=result_reversed
    )

    assert [node.node_id for node in plan_forward.nodes] == [node.node_id for node in plan_reversed.nodes]
    assert [(edge.from_node_id, edge.to_node_id) for edge in plan_forward.edges] == [
        (edge.from_node_id, edge.to_node_id) for edge in plan_reversed.edges
    ]


def test_node_ids_are_stable_and_reproducible_across_calls():
    need = skill_need()
    course = verified(matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course])
    plan_one = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    plan_two = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    assert [node.node_id for node in plan_one.nodes] == [node.node_id for node in plan_two.nodes]
    assert skill_need_node_id(need.need_id) == f"skill_need:{need.need_id}"
    assert course_node_id(CatalogInstitution.TAMU, "csce206") == course_node_id(CatalogInstitution.TAMU, "CSCE 206")


# --- source_ref preserved -------------------------------------------------------

def test_source_ref_points_back_to_original_identifiers_not_display_text():
    need = skill_need()
    course = verified(matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    need_node = next(n for n in plan.nodes if n.node_type == "skill_need")
    course_node = next(n for n in plan.nodes if n.node_type == "course")
    assert need_node.source_ref == need.need_id
    assert course_node.source_ref == course_node_id(CatalogInstitution.TAMU, "CSCE 206")


# --- edge references resolve + round-trip ---------------------------------------

def test_all_edge_references_resolve_within_the_plan():
    need = skill_need()
    course = verified(matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    known = {node.node_id for node in plan.nodes}
    for edge in plan.edges:
        assert edge.from_node_id in known
        assert edge.to_node_id in known


def test_plan_round_trips_through_dump_and_validate():
    need = skill_need()
    course = verified(matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    restored = UnifiedActionPlan.model_validate(plan.model_dump(mode="json"))
    assert restored == plan


# --- self-loop impossible ---------------------------------------------------------

def test_self_loop_edge_is_rejected_by_the_model():
    with pytest.raises(Exception, match="cannot connect a node to itself"):
        PlanEdge(from_node_id="course:tamu:CSCE 206", to_node_id="course:tamu:CSCE 206", relation="satisfies")


# --- cycle detection ---------------------------------------------------------------

def _node(node_id, node_type="skill_need"):
    return PlanNode(node_id=node_id, node_type=node_type, source_ref=node_id, status="OPEN")


def test_detect_cycles_finds_two_node_cycle():
    nodes = [_node("a"), _node("b")]
    edges = [
        PlanEdge(from_node_id="a", to_node_id="b", relation="requires"),
        PlanEdge(from_node_id="b", to_node_id="a", relation="requires"),
    ]
    cycles = detect_cycles(nodes, edges)
    assert cycles
    assert set(cycles[0]) == {"a", "b"}


def test_detect_cycles_finds_three_node_cycle():
    nodes = [_node("a"), _node("b"), _node("c")]
    edges = [
        PlanEdge(from_node_id="a", to_node_id="b", relation="requires"),
        PlanEdge(from_node_id="b", to_node_id="c", relation="requires"),
        PlanEdge(from_node_id="c", to_node_id="a", relation="requires"),
    ]
    cycles = detect_cycles(nodes, edges)
    assert cycles
    assert set(cycles[0]) == {"a", "b", "c"}


def test_detect_cycles_has_no_false_positive_on_a_valid_dag():
    nodes = [_node("a"), _node("b", "course"), _node("c", "course")]
    edges = [
        PlanEdge(from_node_id="b", to_node_id="a", relation="satisfies"),
        PlanEdge(from_node_id="c", to_node_id="a", relation="satisfies"),
    ]
    assert detect_cycles(nodes, edges) == []


def test_build_action_plan_output_never_contains_a_cycle_for_realistic_inputs():
    # The builder only ever emits course -> skill_need "satisfies" edges, a
    # bipartite structure that cannot contain a cycle; this pins that down.
    need = skill_need()
    course = verified(matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    assert plan.execution_status == "SUCCESS"
    assert detect_cycles(plan.nodes, plan.edges) == []


# --- unsupported inputs are not guessed into the graph --------------------------

def test_free_text_gap_information_never_enters_the_graph():
    """GapOutput has no stable identifier back to CareerSkillNeed; the builder's
    signature simply does not accept it, so nothing derived from GAP text -- even
    text that happens to overlap a need's wording -- can reach the plan."""
    from GradusIQ_career.ai.contracts import GapMustHave, GapOutput

    need = skill_need(skill="Python")
    # A GapOutput exists and even mentions "CSCE 206" by name in free text --
    # but it is never passed to build_action_plan, so it cannot influence the
    # result no matter how closely its wording overlaps a real course.
    GapOutput(
        readiness_score=6,
        strengths=["Strong fundamentals"],
        must_have_gaps=[GapMustHave(gap="Python", why_it_matters="core skill", how_to_close="take CSCE 206")],
        nice_to_have_gaps=[],
        recommended_next_steps=["Take CSCE 206"],
    )
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=None)
    # build_action_plan has no parameter for gap_output at all -- there is no
    # code path by which its text could reach the graph. Confirm that directly:
    import inspect

    assert "gap_output" not in inspect.signature(build_action_plan).parameters
    assert not any(node.node_type == "course" for node in plan.nodes)


# --- unverified / invalid recommendations never become actionable nodes ---------

def test_unresolved_candidates_never_become_course_nodes():
    need = skill_need()
    unresolved_candidate = unresolved(matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], unresolved_recs=[unresolved_candidate])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    course_nodes = [node for node in plan.nodes if node.node_type == "course"]
    assert course_nodes == []


# --- already-completed/planned dispositions never become new recommendation nodes ---

@pytest.mark.parametrize("status", [StudentCourseState.COMPLETED, StudentCourseState.PLANNED])
def test_completed_or_planned_verified_recommendation_does_not_become_a_course_node(status):
    need = skill_need()
    course = verified(matched_needs=[need], student_status=status)
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    course_nodes = [node for node in plan.nodes if node.node_type == "course"]
    assert course_nodes == []
    # the skill_need node itself still exists -- only the course is skipped
    assert any(node.node_type == "skill_need" for node in plan.nodes)


def test_in_progress_verified_recommendation_becomes_an_in_progress_course_node():
    need = skill_need()
    course = verified(matched_needs=[need], student_status=StudentCourseState.IN_PROGRESS)
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    course_node = next(n for n in plan.nodes if n.node_type == "course")
    assert course_node.status == "IN_PROGRESS"


# --- prerequisite (requires) edges (feat: add deterministic prerequisite edges) -
# FINC 446 requires FINC 351 AND FINC 361 (ALL mode); ACCT 210 requires ACCT 209
# OR ACCT 229 (ANY mode) -- same real fixtures the Course Discovery prerequisite
# tests use, kept consistent across the codebase.

def test_missing_all_mode_prerequisite_creates_blocked_node_prereq_node_and_edge():
    need = skill_need()
    evaluation = all_mode_evaluation(["FINC 351", "FINC 361"], missing=["FINC 361"], satisfied=["FINC 351"])
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    target_id = course_node_id(CatalogInstitution.TAMU, "FINC 446")
    prereq_id = course_node_id(CatalogInstitution.TAMU, "FINC 361")
    node_ids = {node.node_id for node in plan.nodes}
    assert target_id in node_ids and prereq_id in node_ids
    requires = [edge for edge in plan.edges if edge.relation == "requires"]
    assert len(requires) == 1
    assert requires[0].from_node_id == target_id
    assert requires[0].to_node_id == prereq_id
    prereq_node = next(n for n in plan.nodes if n.node_id == prereq_id)
    assert prereq_node.node_type == "course"
    assert prereq_node.status == "OPEN"
    assert prereq_node.source_ref == prereq_id


def test_multiple_missing_all_mode_prerequisites_create_all_required_edges():
    need = skill_need()
    evaluation = all_mode_evaluation(["FINC 351", "FINC 361"], missing=["FINC 351", "FINC 361"])
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    target_id = course_node_id(CatalogInstitution.TAMU, "FINC 446")
    requires = {edge.to_node_id for edge in plan.edges if edge.relation == "requires"}
    assert requires == {
        course_node_id(CatalogInstitution.TAMU, "FINC 351"),
        course_node_id(CatalogInstitution.TAMU, "FINC 361"),
    }
    assert all(
        edge.from_node_id == target_id for edge in plan.edges if edge.relation == "requires"
    )


def test_satisfied_prerequisite_creates_no_active_dependency_edge():
    need = skill_need()
    # Both required courses satisfied would actually be ELIGIBLE, not blocked --
    # use a partially-satisfied ALL-mode case: FINC 351 satisfied (no edge for
    # it), FINC 361 missing (real edge).
    evaluation = all_mode_evaluation(
        ["FINC 351", "FINC 361"], satisfied=["FINC 351"], missing=["FINC 361"],
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    satisfied_node_id = course_node_id(CatalogInstitution.TAMU, "FINC 351")
    assert satisfied_node_id not in {node.node_id for node in plan.nodes}
    assert not any(edge.to_node_id == satisfied_node_id for edge in plan.edges)


def test_in_progress_prerequisite_produces_in_progress_prerequisite_node():
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351", "FINC 361"], in_progress=["FINC 351"], satisfied=["FINC 361"],
        status=PrerequisiteStatus.UNRESOLVED,
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    prereq_node = next(
        n for n in plan.nodes if n.node_id == course_node_id(CatalogInstitution.TAMU, "FINC 351")
    )
    assert prereq_node.status == "IN_PROGRESS"


def test_planned_prerequisite_produces_open_prerequisite_node_not_a_new_status():
    """PLANNED prerequisites conservatively map to OPEN -- D1 defines only
    OPEN/IN_PROGRESS/SATISFIED and this task deliberately does not add a
    fourth status; "planned but not completed" is still "work remains"."""
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351", "FINC 361"], planned=["FINC 351"], satisfied=["FINC 361"],
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    prereq_node = next(
        n for n in plan.nodes if n.node_id == course_node_id(CatalogInstitution.TAMU, "FINC 351")
    )
    assert prereq_node.status == "OPEN"
    requires = [edge for edge in plan.edges if edge.relation == "requires"]
    assert len(requires) == 1 and requires[0].to_node_id == prereq_node.node_id


def test_any_mode_prerequisite_does_not_become_multiple_mandatory_requires_edges():
    need = skill_need()
    evaluation = any_mode_evaluation(["ACCT 209", "ACCT 229"], missing=["ACCT 209", "ACCT 229"])
    course = blocked("ACCT 210", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    assert [edge for edge in plan.edges if edge.relation == "requires"] == []
    node_ids = {node.node_id for node in plan.nodes}
    assert course_node_id(CatalogInstitution.TAMU, "ACCT 209") not in node_ids
    assert course_node_id(CatalogInstitution.TAMU, "ACCT 229") not in node_ids
    # the target itself still exists (it satisfies the need) even with no requires edges
    assert course_node_id(CatalogInstitution.TAMU, "ACCT 210") in node_ids


def test_unresolved_prerequisite_creates_no_guessed_edges():
    need = skill_need()
    course = blocked("CSCE 221", unresolved_mode_evaluation(), matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    assert [edge for edge in plan.edges if edge.relation == "requires"] == []


def test_none_mode_prerequisite_creates_no_requires_edges():
    need = skill_need()
    evaluation = PrerequisiteEvaluation(
        status=PrerequisiteStatus.ELIGIBLE,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.NONE),
    )
    # NONE-mode is always ELIGIBLE in real data (see prerequisites.py), so a
    # PrerequisiteBlockedCourse with it is a synthetic edge case for this
    # test only -- it still must not fabricate a requires edge.
    course = blocked("CSCE 110", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    assert [edge for edge in plan.edges if edge.relation == "requires"] == []


def test_blocked_course_retains_its_satisfies_edge_alongside_requires():
    need = skill_need()
    evaluation = all_mode_evaluation(["FINC 351"], missing=["FINC 351"])
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    target_id = course_node_id(CatalogInstitution.TAMU, "FINC 446")
    satisfies = [edge for edge in plan.edges if edge.relation == "satisfies"]
    requires = [edge for edge in plan.edges if edge.relation == "requires"]
    assert satisfies == [PlanEdge(from_node_id=target_id, to_node_id=skill_need_node_id(need.need_id), relation="satisfies")]
    assert len(requires) == 1 and requires[0].from_node_id == target_id


def test_one_prerequisite_shared_by_multiple_blocked_targets_produces_one_node():
    need = skill_need()
    evaluation_a = all_mode_evaluation(["FINC 351"], missing=["FINC 351"])
    evaluation_b = all_mode_evaluation(["FINC 351", "ACCT 210"], missing=["FINC 351", "ACCT 210"])
    course_a = blocked("FINC 446", evaluation_a, matched_needs=[need])
    course_b = blocked("MGMT 363", evaluation_b, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course_a, course_b])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    prereq_id = course_node_id(CatalogInstitution.TAMU, "FINC 351")
    matching_nodes = [node for node in plan.nodes if node.node_id == prereq_id]
    assert len(matching_nodes) == 1
    requires_to_prereq = [edge for edge in plan.edges if edge.to_node_id == prereq_id]
    assert len(requires_to_prereq) == 2


def test_prerequisite_already_a_verified_recommendation_is_deduplicated():
    need = skill_need()
    verified_course = verified(course_code="FINC 351", matched_needs=[need])
    evaluation = all_mode_evaluation(["FINC 351"], missing=["FINC 351"])
    blocked_course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(
        TARGET_ROLE, [need], verified_recs=[verified_course], blocked_recs=[blocked_course],
    )
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    prereq_id = course_node_id(CatalogInstitution.TAMU, "FINC 351")
    matching_nodes = [node for node in plan.nodes if node.node_id == prereq_id]
    assert len(matching_nodes) == 1
    # the verified recommendation's own status (NOT_TAKEN -> OPEN) is what survives
    assert matching_nodes[0].status == "OPEN"


def test_prerequisite_already_another_blocked_target_is_reused():
    need = skill_need()
    inner_evaluation = all_mode_evaluation(["ACCT 209"], missing=["ACCT 209"])
    inner_blocked = blocked("FINC 351", inner_evaluation, matched_needs=[need])
    outer_evaluation = all_mode_evaluation(["FINC 351"], missing=["FINC 351"])
    outer_blocked = blocked("FINC 446", outer_evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[inner_blocked, outer_blocked])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    finc351_id = course_node_id(CatalogInstitution.TAMU, "FINC 351")
    matching_nodes = [node for node in plan.nodes if node.node_id == finc351_id]
    assert len(matching_nodes) == 1
    # FINC 351 owns its own requires edge to ACCT 209 (from being blocked itself)
    assert any(
        edge.from_node_id == finc351_id and edge.relation == "requires" for edge in plan.edges
    )
    # and FINC 446 requires FINC 351
    assert any(
        edge.from_node_id == course_node_id(CatalogInstitution.TAMU, "FINC 446")
        and edge.to_node_id == finc351_id and edge.relation == "requires"
        for edge in plan.edges
    )


def test_prerequisite_edges_are_deterministic_regardless_of_input_ordering():
    need = skill_need()
    course_a = blocked("FINC 446", all_mode_evaluation(["FINC 351"], missing=["FINC 351"]), matched_needs=[need])
    course_b = blocked("MGMT 363", all_mode_evaluation(["ACCT 210"], missing=["ACCT 210"]), matched_needs=[need])

    forward = discovery_result(TARGET_ROLE, [need], blocked_recs=[course_a, course_b])
    reversed_result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course_b, course_a])
    plan_forward = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=forward)
    plan_reversed = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=reversed_result)

    assert [n.node_id for n in plan_forward.nodes] == [n.node_id for n in plan_reversed.nodes]
    assert [(e.from_node_id, e.to_node_id, e.relation) for e in plan_forward.edges] == [
        (e.from_node_id, e.to_node_id, e.relation) for e in plan_reversed.edges
    ]


def test_prerequisite_node_ids_are_stable():
    assert course_node_id(CatalogInstitution.TAMU, "finc351") == course_node_id(
        CatalogInstitution.TAMU, "FINC 351"
    )


def test_all_prerequisite_edge_references_resolve():
    need = skill_need()
    evaluation = all_mode_evaluation(["FINC 351", "FINC 361"], missing=["FINC 351", "FINC 361"])
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    known = {node.node_id for node in plan.nodes}
    for edge in plan.edges:
        assert edge.from_node_id in known
        assert edge.to_node_id in known


def test_two_course_prerequisite_cycle_is_detected():
    nodes = [
        PlanNode(node_id="course:tamu:A", node_type="course", source_ref="course:tamu:A", status="OPEN"),
        PlanNode(node_id="course:tamu:B", node_type="course", source_ref="course:tamu:B", status="OPEN"),
    ]
    edges = [
        PlanEdge(from_node_id="course:tamu:A", to_node_id="course:tamu:B", relation="requires"),
        PlanEdge(from_node_id="course:tamu:B", to_node_id="course:tamu:A", relation="requires"),
    ]
    cycles = detect_cycles(nodes, edges)
    assert cycles and set(cycles[0]) == {"course:tamu:A", "course:tamu:B"}


def test_three_course_prerequisite_cycle_is_detected():
    nodes = [
        PlanNode(node_id="course:tamu:A", node_type="course", source_ref="course:tamu:A", status="OPEN"),
        PlanNode(node_id="course:tamu:B", node_type="course", source_ref="course:tamu:B", status="OPEN"),
        PlanNode(node_id="course:tamu:C", node_type="course", source_ref="course:tamu:C", status="OPEN"),
    ]
    edges = [
        PlanEdge(from_node_id="course:tamu:A", to_node_id="course:tamu:B", relation="requires"),
        PlanEdge(from_node_id="course:tamu:B", to_node_id="course:tamu:C", relation="requires"),
        PlanEdge(from_node_id="course:tamu:C", to_node_id="course:tamu:A", relation="requires"),
    ]
    cycles = detect_cycles(nodes, edges)
    assert cycles and set(cycles[0]) == {"course:tamu:A", "course:tamu:B", "course:tamu:C"}


def test_satisfies_edges_never_participate_in_dependency_cycle_detection():
    """A course satisfying two needs plus one need feeding back is not a real
    cycle -- satisfies is not a dependency relation and must be excluded from
    the default cycle check."""
    nodes = [
        PlanNode(node_id="course:tamu:A", node_type="course", source_ref="course:tamu:A", status="OPEN"),
        PlanNode(node_id="skill_need:n1", node_type="skill_need", source_ref="n1", status="OPEN"),
    ]
    edges = [
        PlanEdge(from_node_id="course:tamu:A", to_node_id="skill_need:n1", relation="satisfies"),
        PlanEdge(from_node_id="skill_need:n1", to_node_id="course:tamu:A", relation="satisfies"),
    ]
    assert detect_cycles(nodes, edges) == []
    # explicit relations= override still lets a caller inspect satisfies edges
    # directly if it ever needs to -- the exclusion is a default, not a hard rule.
    assert detect_cycles(nodes, edges, relations=frozenset({"satisfies"})) != []


def test_valid_requires_dag_does_not_false_positive():
    need = skill_need()
    evaluation_a = all_mode_evaluation(["FINC 351"], missing=["FINC 351"])
    evaluation_b = all_mode_evaluation(["ACCT 210"], missing=["ACCT 210"])
    course_a = blocked("FINC 446", evaluation_a, matched_needs=[need])
    course_b = blocked("MGMT 363", evaluation_b, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course_a, course_b])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    assert plan.execution_status == "SUCCESS"
    assert detect_cycles(plan.nodes, plan.edges) == []


def test_dependency_graph_with_blocked_courses_can_still_be_success():
    need = skill_need()
    evaluation = all_mode_evaluation(["FINC 351"], missing=["FINC 351"])
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    assert plan.execution_status == "SUCCESS"
    assert plan.failure is None


def test_no_plan_conflict_is_created_merely_because_a_prerequisite_is_unmet():
    need = skill_need()
    evaluation = all_mode_evaluation(["FINC 351", "FINC 361"], missing=["FINC 351", "FINC 361"])
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    assert plan.conflicts == []


def test_existing_verified_recommendation_graph_behavior_is_unchanged():
    """Re-run of the D2-era one-need-one-course case, now also confirming no
    requires edges appear when there is no prerequisite_blocked input at all."""
    need = skill_need()
    course = verified(matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], verified_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    assert plan.execution_status == "SUCCESS"
    assert [edge for edge in plan.edges if edge.relation == "requires"] == []
    assert len(plan.edges) == 1 and plan.edges[0].relation == "satisfies"


# --- unknown prerequisite (fix: preserve unknown prerequisite states) ------------

def test_unknown_prerequisite_produces_no_requires_edge_or_node():
    """UNKNOWN is not enough deterministic evidence to claim an actionable
    dependency state -- the planner must stay honestly silent, not guess."""
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351", "FINC 361"], unknown=["FINC 351"], satisfied=["FINC 361"],
        status=PrerequisiteStatus.UNRESOLVED,
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    unknown_id = course_node_id(CatalogInstitution.TAMU, "FINC 351")
    assert unknown_id not in {node.node_id for node in plan.nodes}
    assert [edge for edge in plan.edges if edge.relation == "requires"] == []
    # the underlying evidence is not lost -- it just doesn't become graph structure
    assert course.prerequisite_evaluation.unknown_courses == ["FINC 351"]


def test_mixed_missing_and_unknown_prerequisite_only_edges_the_missing_one():
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351", "FINC 361"], missing=["FINC 361"], unknown=["FINC 351"],
        status=PrerequisiteStatus.UNRESOLVED,
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)

    requires = [edge for edge in plan.edges if edge.relation == "requires"]
    assert len(requires) == 1
    assert requires[0].to_node_id == course_node_id(CatalogInstitution.TAMU, "FINC 361")
    unknown_id = course_node_id(CatalogInstitution.TAMU, "FINC 351")
    assert unknown_id not in {node.node_id for node in plan.nodes}


def test_prerequisite_blocked_course_retains_unknown_courses_through_the_builder():
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351"], unknown=["FINC 351"], status=PrerequisiteStatus.UNRESOLVED,
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    # the plan itself doesn't carry PrerequisiteBlockedCourse objects, but the
    # source data the builder consumed still has the evidence -- confirming
    # the builder didn't need to (and didn't) mutate or drop it to produce
    # correct (empty) graph output above.
    assert result.prerequisite_blocked[0].prerequisite_evaluation.unknown_courses == ["FINC 351"]
    assert plan.execution_status == "SUCCESS"


def test_known_missing_prerequisite_behavior_unchanged_by_unknown_courses_field():
    need = skill_need()
    evaluation = all_mode_evaluation(["FINC 351", "FINC 361"], missing=["FINC 351", "FINC 361"])
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    requires = {edge.to_node_id for edge in plan.edges if edge.relation == "requires"}
    assert requires == {
        course_node_id(CatalogInstitution.TAMU, "FINC 351"),
        course_node_id(CatalogInstitution.TAMU, "FINC 361"),
    }


def test_known_in_progress_prerequisite_behavior_unchanged_by_unknown_courses_field():
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351", "FINC 361"], in_progress=["FINC 351"], satisfied=["FINC 361"],
        status=PrerequisiteStatus.UNRESOLVED,
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    prereq_node = next(
        n for n in plan.nodes if n.node_id == course_node_id(CatalogInstitution.TAMU, "FINC 351")
    )
    assert prereq_node.status == "IN_PROGRESS"


def test_known_planned_prerequisite_behavior_unchanged_by_unknown_courses_field():
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351", "FINC 361"], planned=["FINC 351"], satisfied=["FINC 361"],
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    prereq_node = next(
        n for n in plan.nodes if n.node_id == course_node_id(CatalogInstitution.TAMU, "FINC 351")
    )
    assert prereq_node.status == "OPEN"


def test_any_mode_behavior_unchanged_by_unknown_courses_field():
    need = skill_need()
    evaluation = any_mode_evaluation(["ACCT 209", "ACCT 229"], missing=["ACCT 209", "ACCT 229"])
    course = blocked("ACCT 210", evaluation, matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    assert [edge for edge in plan.edges if edge.relation == "requires"] == []


def test_unresolved_mode_behavior_unchanged_by_unknown_courses_field():
    need = skill_need()
    course = blocked("CSCE 221", unresolved_mode_evaluation(), matched_needs=[need])
    result = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result)
    assert [edge for edge in plan.edges if edge.relation == "requires"] == []
