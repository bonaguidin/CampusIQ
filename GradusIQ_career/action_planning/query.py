"""Deterministic, read-only dependency-order query over an assembled plan.

Pure function only: no mutation of `UnifiedActionPlan`, no new edges, no
network access, no model/client dependency, no database access. Consumes
already-validated typed objects and returns an already-validated typed
result (`GradusIQ_career.action_planning.models.DependencyOrderResult`).

Answers exactly two questions:
  1. Given the `requires` facts already proven in the graph, what must
     precede what? (dependency precedence, never calendar/term scheduling --
     an IN_PROGRESS or OPEN/PLANNED prerequisite still precedes its
     dependent in this order; actual completion timing is not represented
     here at all.)
  2. Is that ordering complete with respect to every prerequisite fact the
     source `CourseDiscoveryResult` actually knows about, or does real,
     already-known uncertainty exist that the binary `requires` graph cannot
     express (an ANY/OR requirement, an UNRESOLVED catalog grammar, or a
     prerequisite whose student status is UNKNOWN)?

`satisfies` edges have zero effect here -- only `PlanEdge.relation ==
"requires"` participates, matching `detect_cycles()`'s existing default
filter (reused directly, not re-implemented).
"""

import heapq

from GradusIQ_career.course_discovery.agent_models import CourseDiscoveryResult
from GradusIQ_career.course_discovery.models import PrerequisiteMode

from .builder import course_node_id, detect_cycles
from .models import (
    DependencyOrderLimitation,
    DependencyOrderResult,
    PlanFailure,
    UnifiedActionPlan,
)


def _completeness_limitations(
    plan: UnifiedActionPlan, course_discovery_result: CourseDiscoveryResult
) -> list[DependencyOrderLimitation]:
    """Only blocked courses actually represented in `plan` (matched by stable
    course_node_id, never by title/text) can make the ordering PROVISIONAL --
    uncertain evidence about a candidate outside this plan is not relevant.
    """
    known_node_ids = {node.node_id for node in plan.nodes}
    limitations: list[DependencyOrderLimitation] = []
    for blocked in course_discovery_result.prerequisite_blocked:
        node_id = course_node_id(blocked.institution, blocked.course_code)
        if node_id is None or node_id not in known_node_ids:
            continue
        evaluation = blocked.prerequisite_evaluation
        if evaluation.requirement.mode == PrerequisiteMode.ANY:
            limitations.append(DependencyOrderLimitation(
                node_id=node_id, reason_type="ANY_PREREQUISITE",
                course_codes=list(evaluation.requirement.course_codes),
            ))
        if evaluation.requirement.mode == PrerequisiteMode.UNRESOLVED:
            limitations.append(DependencyOrderLimitation(
                node_id=node_id, reason_type="UNRESOLVED_PREREQUISITE",
                course_codes=list(evaluation.requirement.course_codes),
            ))
        if evaluation.unknown_courses:
            limitations.append(DependencyOrderLimitation(
                node_id=node_id, reason_type="UNKNOWN_COURSE_STATE",
                course_codes=list(evaluation.unknown_courses),
            ))
    return sorted(limitations, key=lambda item: (item.node_id, item.reason_type))


def dependency_order(
    plan: UnifiedActionPlan, course_discovery_result: CourseDiscoveryResult
) -> DependencyOrderResult:
    """Topologically order `plan`'s `requires` subgraph.

    Edge orientation reminder: a stored edge is
    `dependent --requires--> prerequisite` (`from_node_id=dependent,
    to_node_id=prerequisite`). Execution order therefore places the
    *prerequisite* before the *dependent* -- the reverse of the edge's own
    from/to direction. Ties (e.g. two prerequisites of the same course, or
    two independent courses with no relation to each other) are broken by
    plain lexicographic node_id -- no insertion order, no ranking, no LLM.

    Only action nodes (`node_type != "skill_need"`) participate; `skill_need`
    nodes and `satisfies` edges never influence the ordering. An action node
    with zero `requires` edges has no proven ordering constraint and is
    reported in `unconstrained_node_ids`, not assigned an arbitrary position
    in `ordered_node_ids`.

    If `plan`'s `requires` subgraph contains a cycle, no ordering is
    returned -- a typed `status="ERROR"` result with a `PlanFailure` is
    returned instead, the same safe-failure envelope `CourseDiscoveryAgent`
    and `build_action_plan()` already use elsewhere in this codebase.
    """
    if detect_cycles(plan.nodes, plan.edges):
        return DependencyOrderResult(
            status="ERROR",
            failure=PlanFailure(
                error_class="CycleDetected",
                safe_message="The dependency graph contains a requires cycle and cannot be ordered safely.",
            ),
        )

    action_node_ids = {node.node_id for node in plan.nodes if node.node_type != "skill_need"}
    requires_edges = [edge for edge in plan.edges if edge.relation == "requires"]

    successors: dict[str, list[str]] = {node_id: [] for node_id in action_node_ids}
    in_degree: dict[str, int] = {node_id: 0 for node_id in action_node_ids}
    participating: set[str] = set()
    for edge in requires_edges:
        dependent, prerequisite = edge.from_node_id, edge.to_node_id
        if dependent not in action_node_ids or prerequisite not in action_node_ids:
            continue  # defensive; UnifiedActionPlan's own validators already prevent this
        participating.add(dependent)
        participating.add(prerequisite)
        successors[prerequisite].append(dependent)
        in_degree[dependent] += 1

    ready = sorted(node_id for node_id in participating if in_degree[node_id] == 0)
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        node_id = heapq.heappop(ready)
        ordered.append(node_id)
        for successor in sorted(successors[node_id]):
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                heapq.heappush(ready, successor)

    if len(ordered) != len(participating):
        # Should be unreachable -- detect_cycles() already proved this
        # requires subgraph is acyclic -- but the query must not silently
        # emit a partial/wrong order if that invariant is ever violated.
        return DependencyOrderResult(
            status="ERROR",
            failure=PlanFailure(
                error_class="IncompleteOrdering",
                safe_message="The requires graph could not be fully ordered.",
            ),
        )

    unconstrained = sorted(action_node_ids - participating)
    limitations = _completeness_limitations(plan, course_discovery_result)

    return DependencyOrderResult(
        ordered_node_ids=ordered,
        unconstrained_node_ids=unconstrained,
        completeness="PROVISIONAL" if limitations else "COMPLETE",
        limitations=limitations,
        status="ORDERED",
        failure=None,
    )
