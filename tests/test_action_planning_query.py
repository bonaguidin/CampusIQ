import pytest
from pydantic import ValidationError

from GradusIQ_career.action_planning.builder import build_action_plan, course_node_id
from GradusIQ_career.action_planning.models import (
    DependencyOrderResult,
    PlanEdge,
    PlanFailure,
    PlanNode,
    UnifiedActionPlan,
)
from GradusIQ_career.action_planning.query import dependency_order
from GradusIQ_career.course_discovery.models import (
    CatalogInstitution,
    PrerequisiteMode,
    PrerequisiteStatus,
)
from tests.test_action_planning_builder import (
    TARGET_ROLE,
    all_mode_evaluation,
    any_mode_evaluation,
    blocked,
    discovery_result,
    skill_need,
    unresolved_mode_evaluation,
    verified,
)
from tests.test_course_discovery import context
from tests.test_course_discovery_agent import (
    SequenceClient,
    grounded_calls,
    need as agent_need,
    proposal,
    run_agent,
)


def node(node_id, node_type="course", status="OPEN"):
    return PlanNode(node_id=node_id, node_type=node_type, source_ref=node_id, status=status)


def edge(from_id, to_id, relation="requires"):
    return PlanEdge(from_node_id=from_id, to_node_id=to_id, relation=relation)


def plan(nodes, edges, *, conflicts=None):
    return UnifiedActionPlan(
        target_role=TARGET_ROLE, nodes=nodes, edges=edges,
        conflicts=conflicts or [], execution_status="SUCCESS", failure=None,
        summary="test fixture plan",
    )


def empty_result():
    return discovery_result(TARGET_ROLE, [])


# --- empty / unconstrained plans --------------------------------------------------

def test_empty_plan_is_ordered_and_complete():
    result = dependency_order(plan([], []), empty_result())
    assert result.status == "ORDERED"
    assert result.ordered_node_ids == []
    assert result.unconstrained_node_ids == []
    assert result.completeness == "COMPLETE"
    assert result.limitations == []


def test_skill_need_only_plan_produces_no_ordered_or_unconstrained_nodes():
    need = skill_need()
    course = verified(matched_needs=[need])
    result_data = discovery_result(TARGET_ROLE, [need], verified_recs=[course])
    built_plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result_data)
    # one skill_need node, one course node, one satisfies edge, zero requires
    result = dependency_order(built_plan, result_data)
    assert result.ordered_node_ids == []
    need_node_id = next(n.node_id for n in built_plan.nodes if n.node_type == "skill_need")
    course_node_id_value = next(n.node_id for n in built_plan.nodes if n.node_type == "course")
    assert need_node_id not in result.unconstrained_node_ids
    assert course_node_id_value in result.unconstrained_node_ids
    assert result.completeness == "COMPLETE"


# --- basic topological shapes ------------------------------------------------------

def test_single_requires_edge_orders_prerequisite_before_dependent():
    p = plan([node("A"), node("B")], [edge("B", "A")])  # B requires A
    result = dependency_order(p, empty_result())
    assert result.ordered_node_ids == ["A", "B"]
    assert result.unconstrained_node_ids == []


def test_chain_orders_from_root_prerequisite_to_final_dependent():
    p = plan(
        [node("A"), node("B"), node("C")],
        [edge("C", "B"), edge("B", "A")],  # C requires B, B requires A
    )
    result = dependency_order(p, empty_result())
    assert result.ordered_node_ids == ["A", "B", "C"]


def test_fan_out_deterministic_tie_order():
    # B requires A, C requires A
    p = plan([node("A"), node("B"), node("C")], [edge("B", "A"), edge("C", "A")])
    result = dependency_order(p, empty_result())
    assert result.ordered_node_ids == ["A", "B", "C"]


def test_fan_in_both_prerequisites_precede_dependent():
    # C requires A, C requires B
    p = plan([node("A"), node("B"), node("C")], [edge("C", "A"), edge("C", "B")])
    result = dependency_order(p, empty_result())
    assert result.ordered_node_ids.index("A") < result.ordered_node_ids.index("C")
    assert result.ordered_node_ids.index("B") < result.ordered_node_ids.index("C")
    assert result.ordered_node_ids == ["A", "B", "C"]


def test_multiple_disconnected_dependency_components():
    # B requires A; D requires C -- two independent chains
    p = plan(
        [node("A"), node("B"), node("C"), node("D")],
        [edge("B", "A"), edge("D", "C")],
    )
    result = dependency_order(p, empty_result())
    assert result.ordered_node_ids.index("A") < result.ordered_node_ids.index("B")
    assert result.ordered_node_ids.index("C") < result.ordered_node_ids.index("D")
    assert result.ordered_node_ids == ["A", "B", "C", "D"]


def test_ordering_is_deterministic_regardless_of_input_ordering():
    forward = plan([node("A"), node("B"), node("C")], [edge("B", "A"), edge("C", "A")])
    reversed_plan = plan([node("C"), node("B"), node("A")], [edge("C", "A"), edge("B", "A")])
    assert dependency_order(forward, empty_result()).ordered_node_ids == dependency_order(
        reversed_plan, empty_result()
    ).ordered_node_ids


def test_multiple_valid_orderings_resolve_via_lexicographic_tie_break():
    # Z requires A, Y requires A -- both Y and Z become ready simultaneously;
    # lexicographic tie-break must pick Y before Z, not insertion order (Z was
    # declared first here).
    p = plan([node("A"), node("Z"), node("Y")], [edge("Z", "A"), edge("Y", "A")])
    result = dependency_order(p, empty_result())
    assert result.ordered_node_ids == ["A", "Y", "Z"]


# --- satisfies edges and skill_need nodes are ignored -----------------------------

def test_satisfies_edges_do_not_affect_ordering():
    p = plan(
        [node("A"), node("B"), node("skill_need:n1", node_type="skill_need")],
        [
            edge("B", "A"),  # real dependency
            edge("A", "skill_need:n1", relation="satisfies"),
            edge("B", "skill_need:n1", relation="satisfies"),
        ],
    )
    result = dependency_order(p, empty_result())
    assert result.ordered_node_ids == ["A", "B"]
    assert "skill_need:n1" not in result.ordered_node_ids
    assert "skill_need:n1" not in result.unconstrained_node_ids


def test_skill_need_nodes_never_create_false_dependencies():
    p = plan(
        [node("skill_need:n1", node_type="skill_need")],
        [],
    )
    result = dependency_order(p, empty_result())
    assert result.ordered_node_ids == []
    assert result.unconstrained_node_ids == []


# --- completeness: COMPLETE vs PROVISIONAL -----------------------------------------

def test_fully_known_all_mode_dependency_is_complete():
    need = skill_need()
    evaluation = all_mode_evaluation(["FINC 351"], missing=["FINC 351"])
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result_data = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    built_plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result_data)
    result = dependency_order(built_plan, result_data)
    assert result.completeness == "COMPLETE"
    assert result.limitations == []
    target_id = course_node_id(CatalogInstitution.TAMU, "FINC 446")
    prereq_id = course_node_id(CatalogInstitution.TAMU, "FINC 351")
    assert result.ordered_node_ids == [prereq_id, target_id]


def test_any_mode_prerequisite_marks_ordering_provisional_with_no_fake_edge():
    need = skill_need()
    evaluation = any_mode_evaluation(["ACCT 209", "ACCT 229"], missing=["ACCT 209", "ACCT 229"])
    course = blocked("ACCT 210", evaluation, matched_needs=[need])
    result_data = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    built_plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result_data)
    result = dependency_order(built_plan, result_data)

    target_id = course_node_id(CatalogInstitution.TAMU, "ACCT 210")
    assert target_id in result.unconstrained_node_ids  # no requires edge fabricated
    assert result.ordered_node_ids == []
    assert result.completeness == "PROVISIONAL"
    assert len(result.limitations) == 1
    limitation = result.limitations[0]
    assert limitation.node_id == target_id
    assert limitation.reason_type == "ANY_PREREQUISITE"
    assert set(limitation.course_codes) == {"ACCT 209", "ACCT 229"}


def test_unresolved_mode_prerequisite_marks_ordering_provisional():
    need = skill_need()
    course = blocked("CSCE 221", unresolved_mode_evaluation(), matched_needs=[need])
    result_data = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    built_plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result_data)
    result = dependency_order(built_plan, result_data)
    assert result.completeness == "PROVISIONAL"
    assert any(item.reason_type == "UNRESOLVED_PREREQUISITE" for item in result.limitations)


def test_unknown_course_state_marks_ordering_provisional():
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351"], unknown=["FINC 351"], satisfied=[], status=PrerequisiteStatus.UNRESOLVED,
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result_data = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    built_plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result_data)
    result = dependency_order(built_plan, result_data)
    assert result.completeness == "PROVISIONAL"
    limitation = next(item for item in result.limitations if item.reason_type == "UNKNOWN_COURSE_STATE")
    assert limitation.course_codes == ["FINC 351"]


def test_mixed_known_and_unknown_evidence_orders_the_known_edge_but_stays_provisional():
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351", "FINC 361"], missing=["FINC 361"], unknown=["FINC 351"],
        status=PrerequisiteStatus.UNRESOLVED,
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result_data = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    built_plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result_data)
    result = dependency_order(built_plan, result_data)

    target_id = course_node_id(CatalogInstitution.TAMU, "FINC 446")
    known_prereq_id = course_node_id(CatalogInstitution.TAMU, "FINC 361")
    assert result.ordered_node_ids == [known_prereq_id, target_id]
    assert result.completeness == "PROVISIONAL"
    assert any(item.reason_type == "UNKNOWN_COURSE_STATE" for item in result.limitations)


def test_uncertain_evidence_outside_the_plan_does_not_mark_it_provisional():
    """An ANY-mode blocked course that matches none of the plan's skill_needs
    and has no dependencies never becomes a node at all (build_action_plan's
    orphan-avoidance rule) -- its uncertainty must not leak into a plan it
    isn't even represented in."""
    need = skill_need()
    course = verified(matched_needs=[need])
    unrelated_evaluation = any_mode_evaluation(["ACCT 209", "ACCT 229"])
    unrelated_blocked = blocked("ACCT 210", unrelated_evaluation, matched_needs=[])
    result_data = discovery_result(
        TARGET_ROLE, [need], verified_recs=[course], blocked_recs=[unrelated_blocked],
    )
    built_plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result_data)
    assert course_node_id(CatalogInstitution.TAMU, "ACCT 210") not in {n.node_id for n in built_plan.nodes}

    result = dependency_order(built_plan, result_data)
    assert result.completeness == "COMPLETE"
    assert result.limitations == []


# --- IN_PROGRESS / PLANNED precedence (dependency order, not calendar time) --------

def test_in_progress_prerequisite_still_precedes_its_dependent():
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351", "FINC 361"], in_progress=["FINC 351"], satisfied=["FINC 361"],
        status=PrerequisiteStatus.UNRESOLVED,
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result_data = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    built_plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result_data)
    result = dependency_order(built_plan, result_data)

    target_id = course_node_id(CatalogInstitution.TAMU, "FINC 446")
    prereq_id = course_node_id(CatalogInstitution.TAMU, "FINC 351")
    assert result.ordered_node_ids == [prereq_id, target_id]
    prereq_node = next(n for n in built_plan.nodes if n.node_id == prereq_id)
    assert prereq_node.status == "IN_PROGRESS"  # precedence holds regardless of node status


def test_planned_prerequisite_still_precedes_dependent_without_claiming_term_timing():
    need = skill_need()
    evaluation = all_mode_evaluation(
        ["FINC 351", "FINC 361"], planned=["FINC 351"], satisfied=["FINC 361"],
    )
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result_data = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    built_plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result_data)
    result = dependency_order(built_plan, result_data)

    target_id = course_node_id(CatalogInstitution.TAMU, "FINC 446")
    prereq_id = course_node_id(CatalogInstitution.TAMU, "FINC 351")
    assert result.ordered_node_ids == [prereq_id, target_id]
    prereq_node = next(n for n in built_plan.nodes if n.node_id == prereq_id)
    assert prereq_node.status == "OPEN"  # PLANNED maps to OPEN in PlanNode, not a calendar claim


# --- cycle / malformed-input safety -------------------------------------------------

def test_two_node_cycle_is_safely_rejected_with_typed_error():
    p = plan([node("A"), node("B")], [edge("A", "B"), edge("B", "A")])
    result = dependency_order(p, empty_result())
    assert result.status == "ERROR"
    assert isinstance(result.failure, PlanFailure)
    assert result.failure.error_class == "CycleDetected"
    assert result.ordered_node_ids == []
    assert result.unconstrained_node_ids == []
    assert result.limitations == []


def test_three_node_cycle_is_safely_rejected():
    p = plan(
        [node("A"), node("B"), node("C")],
        [edge("A", "B"), edge("B", "C"), edge("C", "A")],
    )
    result = dependency_order(p, empty_result())
    assert result.status == "ERROR"
    assert result.failure.error_class == "CycleDetected"


def test_dangling_edge_reference_is_prevented_at_the_plan_level():
    """UnifiedActionPlan's own validators reject a dangling reference before
    dependency_order() ever sees it -- defense in depth, not this query's job
    to re-check."""
    with pytest.raises(ValidationError, match="unknown node"):
        UnifiedActionPlan(
            target_role=TARGET_ROLE,
            nodes=[node("A")],
            edges=[edge("A", "does-not-exist")],
            execution_status="SUCCESS",
            summary="malformed",
        )


# --- round trip ----------------------------------------------------------------------

def test_dependency_order_result_round_trips():
    need = skill_need()
    evaluation = all_mode_evaluation(["FINC 351"], missing=["FINC 351"])
    course = blocked("FINC 446", evaluation, matched_needs=[need])
    result_data = discovery_result(TARGET_ROLE, [need], blocked_recs=[course])
    built_plan = build_action_plan(target_role=TARGET_ROLE, skill_needs=[need], course_discovery_result=result_data)
    result = dependency_order(built_plan, result_data)
    restored = DependencyOrderResult.model_validate(result.model_dump(mode="json"))
    assert restored == result


# --- regression: unused ANY-mode alternatives never imply unresolved dependency ----
# ACCT 210 requires ACCT 209 OR ACCT 229 (real TAMU catalog data, same fixture the
# Course Discovery prerequisite tests already use). Driving the real agent, not a
# hand-built object, so the target is a genuine VerifiedCourseRecommendation --
# prerequisite_status == ELIGIBLE is the only state that type can ever carry.

def _real_any_mode_verified_recommendation():
    ctx = context(courses=(("a", "ACCT 229", "completed"),))  # ACCT 209 left NOT_TAKEN
    career_need = agent_need("ACCT 210")
    client = SequenceClient(
        {"content": "", "tool_calls": grounded_calls("ACCT 210")},
        {"content": proposal("ACCT 210", career_need.need_id)},
    )
    outcome = run_agent(client, ctx=ctx, needs=[career_need])
    return career_need, outcome.result


def test_verified_recommendation_with_missing_any_alternative_does_not_make_ordering_provisional():
    career_need, course_discovery_result = _real_any_mode_verified_recommendation()
    recommendation = course_discovery_result.verified_recommendations[0]
    evaluation = recommendation.prerequisite_evaluation

    # structural proof this is the real "unused missing alternative" state, not
    # an assumption -- see semantic audit Step 2/4.
    assert recommendation.prerequisite_status == PrerequisiteStatus.ELIGIBLE
    assert evaluation.requirement.mode == PrerequisiteMode.ANY
    assert evaluation.satisfied_courses == ["ACCT 229"]
    assert evaluation.missing_courses == ["ACCT 209"]

    built_plan = build_action_plan(
        target_role=TARGET_ROLE, skill_needs=[career_need], course_discovery_result=course_discovery_result,
    )
    result = dependency_order(built_plan, course_discovery_result)

    assert result.status == "ORDERED"
    assert result.completeness == "COMPLETE"
    assert result.limitations == []
    # the unused missing alternative (ACCT 209) never became a node or an edge
    unused_id = course_node_id(CatalogInstitution.TAMU, "ACCT 209")
    known_node_ids = {n.node_id for n in built_plan.nodes}
    assert unused_id not in known_node_ids
    assert not any(edge.to_node_id == unused_id or edge.from_node_id == unused_id for edge in built_plan.edges)
    assert [edge for edge in built_plan.edges if edge.relation == "requires"] == []


def test_verified_recommendation_with_unknown_any_alternative_does_not_make_ordering_provisional():
    career_need, course_discovery_result = _real_any_mode_verified_recommendation()
    recommendation = course_discovery_result.verified_recommendations[0]
    # Reaching a genuine StudentCourseState.UNKNOWN for a real catalog alternative
    # requires a code absent from the local catalog snapshot, which the real
    # fixture data doesn't happen to exercise for ACCT 209/229. Starting from the
    # real agent-produced recommendation (same course, same title, same
    # provenance, same matched_needs) and moving the one unused alternative from
    # "missing" to "unknown" -- a state my semantic audit already proved is
    # reachable for ANY-mode ELIGIBLE -- is the minimal realistic construction,
    # not a hand-built impossible object. status stays ELIGIBLE throughout.
    evaluation = recommendation.prerequisite_evaluation.model_copy(update={
        "missing_courses": [],
        "unknown_courses": ["ACCT 209"],
    })
    recommendation = recommendation.model_copy(update={"prerequisite_evaluation": evaluation})
    course_discovery_result = course_discovery_result.model_copy(
        update={"verified_recommendations": [recommendation]}
    )

    assert recommendation.prerequisite_status == PrerequisiteStatus.ELIGIBLE
    assert evaluation.requirement.mode == PrerequisiteMode.ANY
    assert evaluation.satisfied_courses == ["ACCT 229"]
    assert evaluation.unknown_courses == ["ACCT 209"]

    built_plan = build_action_plan(
        target_role=TARGET_ROLE, skill_needs=[career_need], course_discovery_result=course_discovery_result,
    )
    result = dependency_order(built_plan, course_discovery_result)

    assert result.status == "ORDERED"
    assert result.completeness == "COMPLETE"
    assert result.limitations == []
    # the unknown unused alternative never became a node, an edge, or a limitation
    unused_id = course_node_id(CatalogInstitution.TAMU, "ACCT 209")
    known_node_ids = {n.node_id for n in built_plan.nodes}
    assert unused_id not in known_node_ids
    assert [edge for edge in built_plan.edges if edge.relation == "requires"] == []
    assert not any(item.node_id == unused_id for item in result.limitations)
    # the UNKNOWN fact itself is not erased -- it just doesn't affect ordering
    assert course_discovery_result.verified_recommendations[0].prerequisite_evaluation.unknown_courses == ["ACCT 209"]
