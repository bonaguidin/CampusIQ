import pytest
from pydantic import ValidationError

from GradusIQ_career.action_planning.models import (
    PlanConflict,
    PlanEdge,
    PlanFailure,
    PlanNode,
    UnifiedActionPlan,
)


def node(node_id="need_abc123", node_type="skill_need", source_ref="need_abc123", status="OPEN"):
    return PlanNode(node_id=node_id, node_type=node_type, source_ref=source_ref, status=status)


def edge(from_node_id="need_abc123", to_node_id="CSCE 206", relation="requires"):
    return PlanEdge(from_node_id=from_node_id, to_node_id=to_node_id, relation=relation)


def plan(**overrides):
    defaults = dict(
        target_role="Software Engineering Intern",
        nodes=[],
        edges=[],
        conflicts=[],
        execution_status="SUCCESS",
        failure=None,
        summary="Empty plan; nothing to arrange yet.",
    )
    defaults.update(overrides)
    return UnifiedActionPlan(**defaults)


# --- PlanNode ---------------------------------------------------------------

def test_valid_plan_node():
    result = node()
    assert result.node_id == "need_abc123"
    assert result.node_type == "skill_need"
    assert result.status == "OPEN"


def test_plan_node_rejects_invalid_node_type():
    with pytest.raises(ValidationError):
        PlanNode(node_id="n1", node_type="internship", source_ref="ref", status="OPEN")


def test_plan_node_rejects_invalid_status():
    with pytest.raises(ValidationError):
        PlanNode(node_id="n1", node_type="course", source_ref="ref", status="DONE")


def test_plan_node_rejects_extra_fields():
    with pytest.raises(ValidationError):
        PlanNode(
            node_id="n1", node_type="course", source_ref="ref", status="OPEN",
            course_code="CSCE 206",
        )


# --- PlanEdge ----------------------------------------------------------------

def test_valid_plan_edge():
    result = edge()
    assert result.relation == "requires"


def test_plan_edge_rejects_self_loop():
    with pytest.raises(ValidationError, match="cannot connect a node to itself"):
        PlanEdge(from_node_id="n1", to_node_id="n1", relation="blocks")


def test_plan_edge_rejects_invalid_relation():
    with pytest.raises(ValidationError):
        PlanEdge(from_node_id="n1", to_node_id="n2", relation="unlocks")


# --- PlanConflict --------------------------------------------------------------

def test_valid_plan_conflict():
    result = PlanConflict(node_ids=["n1", "n2"], reason="two nodes satisfy the same need", resolution="UNRESOLVED")
    assert result.resolution == "UNRESOLVED"


def test_plan_conflict_rejects_invalid_resolution():
    with pytest.raises(ValidationError):
        PlanConflict(node_ids=["n1"], reason="ambiguous", resolution="IGNORED")


def test_plan_conflict_rejects_empty_node_ids():
    with pytest.raises(ValidationError):
        PlanConflict(node_ids=[], reason="ambiguous", resolution="UNRESOLVED")


# --- PlanFailure ---------------------------------------------------------------

def test_plan_failure_defaults():
    failure = PlanFailure()
    assert failure.category == "PLANNER_FAILURE"
    assert failure.error_class is None
    assert "could not be assembled safely" in failure.safe_message


# --- UnifiedActionPlan: round-trip, referential integrity ----------------------

def test_unified_action_plan_round_trips_through_dump_and_validate():
    original = plan(
        nodes=[node()],
        edges=[],
        conflicts=[],
        execution_status="SUCCESS",
        summary="One open skill-need node, nothing downstream yet.",
    )
    restored = UnifiedActionPlan.model_validate(original.model_dump(mode="json"))
    assert restored == original


def test_unified_action_plan_rejects_duplicate_node_id():
    with pytest.raises(ValidationError, match="duplicate node_id"):
        plan(
            nodes=[node(node_id="n1"), node(node_id="n1", node_type="course", source_ref="CSCE 206")],
            summary="Two nodes share an id.",
        )


def test_unified_action_plan_rejects_edge_to_unknown_node():
    with pytest.raises(ValidationError, match="unknown node"):
        plan(
            nodes=[node(node_id="n1")],
            edges=[edge(from_node_id="n1", to_node_id="does-not-exist", relation="requires")],
            summary="Edge points at a node that was never declared.",
        )


def test_unified_action_plan_rejects_edge_from_unknown_node():
    with pytest.raises(ValidationError, match="unknown node"):
        plan(
            nodes=[node(node_id="n1")],
            edges=[edge(from_node_id="ghost", to_node_id="n1", relation="requires")],
            summary="Edge originates from a node that was never declared.",
        )


def test_unified_action_plan_rejects_conflict_referencing_unknown_node():
    with pytest.raises(ValidationError, match="unknown node"):
        plan(
            nodes=[node(node_id="n1")],
            conflicts=[PlanConflict(node_ids=["n1", "ghost"], reason="ambiguous", resolution="UNRESOLVED")],
            execution_status="PARTIAL",
            summary="Conflict references a node that was never declared.",
        )


# --- UnifiedActionPlan: SUCCESS / PARTIAL / ERROR invariants -------------------

def test_success_plan_with_nodes_and_no_conflicts_is_valid():
    result = plan(
        nodes=[node()],
        execution_status="SUCCESS",
        summary="Clean plan, nothing outstanding.",
    )
    assert result.execution_status == "SUCCESS"
    assert result.failure is None


def test_success_plan_cannot_carry_a_residual_conflict():
    with pytest.raises(ValidationError, match="cannot carry any residual conflicts"):
        plan(
            nodes=[node(node_id="n1"), node(node_id="n2", node_type="course", source_ref="CSCE 206")],
            conflicts=[PlanConflict(node_ids=["n1", "n2"], reason="ambiguous", resolution="DEFERRED")],
            execution_status="SUCCESS",
            summary="Should be PARTIAL, not SUCCESS.",
        )


def test_partial_plan_requires_at_least_one_conflict():
    with pytest.raises(ValidationError, match="requires at least one residual conflict"):
        plan(
            nodes=[node()],
            execution_status="PARTIAL",
            summary="Nothing actually outstanding; PARTIAL is unjustified.",
        )


def test_partial_plan_with_conflict_is_valid():
    result = plan(
        nodes=[node(node_id="n1"), node(node_id="n2", node_type="course", source_ref="CSCE 206")],
        conflicts=[PlanConflict(node_ids=["n1", "n2"], reason="ambiguous", resolution="UNRESOLVED")],
        execution_status="PARTIAL",
        summary="One residual conflict remains.",
    )
    assert result.execution_status == "PARTIAL"
    assert result.failure is None


def test_error_plan_requires_failure():
    with pytest.raises(ValidationError, match="requires a PlanFailure"):
        plan(execution_status="ERROR", summary="Errored but no failure attached.")


def test_error_plan_cannot_carry_graph_data():
    with pytest.raises(ValidationError, match="cannot carry partial graph data"):
        plan(
            nodes=[node()],
            execution_status="ERROR",
            failure=PlanFailure(error_class="ValueError"),
            summary="Errored but still carrying a node.",
        )


def test_error_plan_with_failure_and_no_graph_data_is_valid():
    result = plan(
        execution_status="ERROR",
        failure=PlanFailure(error_class="ValueError"),
        summary="Could not be assembled.",
    )
    assert result.execution_status == "ERROR"
    assert result.failure.error_class == "ValueError"
    assert result.nodes == [] and result.edges == [] and result.conflicts == []


def test_non_error_plan_cannot_carry_a_failure():
    with pytest.raises(ValidationError, match="must not carry a PlanFailure"):
        plan(execution_status="SUCCESS", failure=PlanFailure(), summary="Success but failure also set.")


# --- Empty plan behavior --------------------------------------------------------

def test_empty_plan_with_no_nodes_is_a_valid_success():
    result = plan()
    assert result.execution_status == "SUCCESS"
    assert result.nodes == [] and result.edges == [] and result.conflicts == []
    assert result.failure is None


def test_empty_plan_cannot_claim_partial():
    with pytest.raises(ValidationError, match="requires at least one residual conflict"):
        plan(execution_status="PARTIAL", summary="Nothing here, but claims PARTIAL.")
