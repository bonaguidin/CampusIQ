"""Deterministic graph assembly for the Phase D unified action plan.

Pure functions only: no network access, no model/client dependency, no
database writes, no side effects. Every function here accepts already
validated typed objects and returns already validated planning-domain
objects (`GradusIQ_career.action_planning.models`).

Supported inputs (Phase D2 + D-prereq):
  * `CareerSkillNeed` -- has a stable, content-derived `need_id`
    (`course_discovery/models.py::CareerSkillNeed.assign_stable_id`), safe
    to use as a node identifier.
  * `CourseDiscoveryResult.verified_recommendations` -- each
    `VerifiedCourseRecommendation` carries a catalog `institution` +
    `course_code`, and `matched_needs: list[CareerSkillNeed]` with real
    `need_id`s. `course --satisfies--> skill_need`.
  * `CourseDiscoveryResult.prerequisite_blocked` -- each
    `PrerequisiteBlockedCourse` carries the same `institution`/`course_code`/
    `matched_needs` shape (so it also gets a `satisfies` edge) plus a
    required `PrerequisiteEvaluation` -- the source of `requires` edges.
    Only `PrerequisiteMode.ALL` requirements produce edges; see the ANY-mode
    note below. Only `missing_courses`/`in_progress_courses`/
    `planned_courses` are consulted -- never `satisfied_courses` (already
    resolved, not an active dependency) and never `requirement.course_codes`
    directly (that list can silently omit a code whose student status came
    back UNKNOWN -- see `_prerequisite_dependency_codes`).

Deliberately NOT supported (documented, not silently dropped):
  * `CourseDiscoveryResult.requires_verification` (`UnresolvedCourseCandidate`)
    -- eligibility_status is UNRESOLVED by construction; these are not
    actionable recommendations and must never become course PlanNodes.
  * `GapOutput` / `FitOutput` / `ShiftOutput` -- their gap/signal/task fields
    are free text with no stable identifier connecting them back to a
    `CareerSkillNeed`. Linking them would require fuzzy string matching,
    embeddings, or LLM-assisted matching, all explicitly disallowed for this
    layer. There is currently no typed bridge from GAP/FIT/SHIFT output back
    to `CareerSkillNeed`; building one is a separate, later unit.
  * `PrerequisiteMode.ANY` requires edges -- CONTRACT GAP, not an oversight.
    `PlanEdge` is a plain binary (from_node_id, to_node_id, relation) edge
    with no group/alternative construct. "A requires B OR C" cannot be
    represented as two `requires` edges without silently changing its
    meaning to "A requires B AND C". Emitting nothing is the only choice
    that doesn't misrepresent the requirement. The evidence is not lost --
    `PrerequisiteBlockedCourse.prerequisite_evaluation` on the source
    `CourseDiscoveryResult` still carries the full ANY-mode requirement
    (`requirement.mode`, `requirement.course_codes`) untouched; only the
    graph is silent about it. Representing OR-alternatives correctly would
    need a new typed construct (e.g. a dependency-group id shared by
    alternative edges) -- out of scope for this unit.
  * `PrerequisiteMode.UNRESOLVED` / `NONE` requires edges -- UNRESOLVED means
    C1 could not determine the requirement at all (ambiguous catalog
    grammar); inventing an edge from ambiguous text would not be
    deterministic. NONE has no course codes to emit edges from.
"""

from GradusIQ_career.course_discovery.agent_models import (
    CourseDiscoveryResult,
    PrerequisiteBlockedCourse,
    VerifiedCourseRecommendation,
)
from GradusIQ_career.course_discovery.models import (
    CareerSkillNeed,
    CatalogInstitution,
    PrerequisiteEvaluation,
    PrerequisiteMode,
    StudentCourseState,
    canonical_course_code,
)

from .models import (
    EdgeRelation,
    NodeStatus,
    PlanEdge,
    PlanFailure,
    PlanNode,
    UnifiedActionPlan,
)


# Node ID convention (deterministic, reproducible, debuggable):
#   skill_need:<need_id>                      e.g. skill_need:need_800c5636a44a
#   course:<institution_value>:<course_code>  e.g. course:tamu:CSCE 206
#
# need_id is already a stable, content-derived hash (assign_stable_id on
# CareerSkillNeed); course_code is passed through canonical_course_code(),
# the same normalizer the catalog itself uses, so two spellings of the same
# course always collapse to the same node id. No UUIDs, no hash(), no ids
# derived from display/free text.

def skill_need_node_id(need_id: str) -> str:
    return f"skill_need:{need_id}"


def course_node_id(institution: CatalogInstitution, course_code: str) -> str | None:
    normalized = canonical_course_code(course_code)
    if normalized is None:
        return None
    return f"course:{institution.value}:{normalized}"


# A verified recommendation whose student_status is already COMPLETED or
# PLANNED is not a new actionable item -- it must not become a course node.
_SKIPPED_COURSE_STATUSES = {StudentCourseState.COMPLETED, StudentCourseState.PLANNED}

_COURSE_NODE_STATUS_BY_STUDENT_STATE: dict[StudentCourseState, NodeStatus] = {
    StudentCourseState.NOT_TAKEN: "OPEN",
    StudentCourseState.IN_PROGRESS: "IN_PROGRESS",
    StudentCourseState.UNKNOWN: "OPEN",
}


def _skill_need_nodes(skill_needs: list[CareerSkillNeed]) -> dict[str, PlanNode]:
    nodes: dict[str, PlanNode] = {}
    for need in skill_needs:
        node_id = skill_need_node_id(need.need_id)
        if node_id in nodes:
            continue
        nodes[node_id] = PlanNode(
            node_id=node_id,
            node_type="skill_need",
            source_ref=need.need_id,
            # D2 has no visibility into whether this need is already met
            # independent of a course (that would require reading the
            # student's demonstrated-skills data, out of scope here), so
            # every skill_need node starts OPEN.
            status="OPEN",
        )
    return nodes


def _course_node(recommendation: VerifiedCourseRecommendation) -> PlanNode | None:
    if recommendation.student_status in _SKIPPED_COURSE_STATUSES:
        return None
    node_id = course_node_id(recommendation.institution, recommendation.course_code)
    if node_id is None:
        return None
    status = _COURSE_NODE_STATUS_BY_STUDENT_STATE.get(recommendation.student_status, "OPEN")
    return PlanNode(
        node_id=node_id,
        node_type="course",
        source_ref=node_id,
        status=status,
    )


def _blocked_course_node(blocked: PrerequisiteBlockedCourse) -> PlanNode | None:
    """A prerequisite-blocked target is not currently actionable, but it is
    still a real course the student has not completed -- represented as
    node_type="course" like any other course node. status="OPEN" here means
    only "work remains / not completed", the same meaning OPEN already
    carries for a NOT_TAKEN verified recommendation -- never "immediately
    enrollable now". `PrerequisiteBlockedCourse` has no `student_status`
    field, but that is not a gap: check_eligibility()'s INELIGIBLE branch is
    only reached after the COMPLETED/IN_PROGRESS/PLANNED early-return checks
    already ran and did not match, so the target's own status is
    structurally guaranteed to be NOT_TAKEN or UNKNOWN here -- OPEN either
    way. Blocking itself is represented by this node's outgoing `requires`
    edges, not by a separate node status.
    """
    node_id = course_node_id(blocked.institution, blocked.course_code)
    if node_id is None:
        return None
    return PlanNode(node_id=node_id, node_type="course", source_ref=node_id, status="OPEN")


def _prerequisite_only_node(
    institution: CatalogInstitution, course_code: str, status: NodeStatus
) -> PlanNode | None:
    """A course that exists only as a code inside a PrerequisiteEvaluation --
    never queried from the catalog here (the planner does not re-query
    Course Discovery); source_ref is the node's own id, the same
    self-referential convention `_course_node`/`_blocked_course_node` use,
    since there is no separate catalog record object to point to."""
    node_id = course_node_id(institution, course_code)
    if node_id is None:
        return None
    return PlanNode(node_id=node_id, node_type="course", source_ref=node_id, status=status)


def _prerequisite_dependency_codes(
    evaluation: PrerequisiteEvaluation,
) -> list[tuple[str, NodeStatus]]:
    """Return (course_code, node_status) pairs that represent a currently
    active dependency -- deterministically, from the student's evaluated
    state, never from raw `requirement.course_codes` or free text.

    Only PrerequisiteMode.ALL is handled; ANY/UNRESOLVED/NONE return []
    (see the module docstring's ANY-mode contract-gap note). Only
    missing/in_progress/planned codes are consulted:
      * satisfied_courses -- already resolved, not an active dependency.
      * a code with StudentCourseState.UNKNOWN silently does not appear in
        *any* of PrerequisiteEvaluation's four lists (a pre-existing
        contract gap in evaluate_prerequisites(), not something this
        function can or should paper over) -- it correctly gets no edge
        here, since there is no deterministic evidence to build one from.
    planned_courses maps to OPEN, not a new status: D1 only defines
    OPEN/IN_PROGRESS/SATISFIED, and "planned but not yet completed" is
    honestly still "work remains" under that model -- the same conservative
    reading applied to blocked target nodes above.
    """
    if evaluation.requirement.mode != PrerequisiteMode.ALL:
        return []
    dependencies: dict[str, NodeStatus] = {}
    for code in evaluation.missing_courses:
        dependencies[code] = "OPEN"
    for code in evaluation.in_progress_courses:
        dependencies[code] = "IN_PROGRESS"
    for code in evaluation.planned_courses:
        dependencies.setdefault(code, "OPEN")
    return sorted(dependencies.items())


def detect_cycles(
    nodes: list[PlanNode],
    edges: list[PlanEdge],
    *,
    relations: frozenset[EdgeRelation] = frozenset({"requires"}),
) -> list[list[str]]:
    """Return every directed cycle found among edges whose `relation` is in
    `relations`, as ordered node_id lists.

    Only dependency-bearing relations participate by default. A `satisfies`
    edge means "this action fulfills that need", not "this action depends on
    that need existing first" -- including it here would flag ordinary
    course-to-need fan-in as a false cycle. `blocks` is not emitted by this
    builder yet; when it is, it belongs in a dependency-bearing check too,
    but that decision is deferred to whoever adds it.

    Deterministic depth-first search: adjacency is built from a sorted,
    relation-filtered edge list and nodes are visited in sorted node_id
    order, so the result does not depend on input ordering. `PlanEdge`
    already rejects self-loops at the model level; this catches everything
    longer (A->B->A, A->B->C->A, ...).
    """
    dependency_edges = [edge for edge in edges if edge.relation in relations]
    adjacency: dict[str, list[str]] = {node.node_id: [] for node in nodes}
    for edge in sorted(dependency_edges, key=lambda item: (item.from_node_id, item.to_node_id)):
        adjacency.setdefault(edge.from_node_id, []).append(edge.to_node_id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node_id: WHITE for node_id in adjacency}
    cycles: list[list[str]] = []
    path: list[str] = []

    def dfs(node_id: str) -> bool:
        color[node_id] = GRAY
        path.append(node_id)
        for neighbor in adjacency.get(node_id, []):
            if color.get(neighbor, WHITE) == WHITE:
                if dfs(neighbor):
                    return True
            elif color.get(neighbor) == GRAY:
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])
                return True
        path.pop()
        color[node_id] = BLACK
        return False

    for node_id in sorted(adjacency):
        if color[node_id] == WHITE:
            dfs(node_id)

    return cycles


def build_action_plan(
    *,
    target_role: str,
    skill_needs: list[CareerSkillNeed],
    course_discovery_result: CourseDiscoveryResult | None = None,
) -> UnifiedActionPlan:
    """Assemble a UnifiedActionPlan from already-validated typed inputs only.

    Edge orientation:
      * course --satisfies--> skill_need (a course, if taken, satisfies the
        need). Built from both `verified_recommendations` and
        `prerequisite_blocked` -- a blocked course is still relevant to the
        need it would satisfy; that relevance and its current blockage are
        two separate facts, both preserved.
      * dependent course --requires--> prerequisite course (the dependent
        course cannot be completed until the prerequisite is satisfied).
        Built only from `prerequisite_blocked[].prerequisite_evaluation`,
        ALL-mode requirements only (see module docstring).

    `requires_verification` entries are never turned into course nodes (see
    module docstring). A `satisfies` edge is only created when a course's
    `matched_needs` includes a need whose `need_id` also appears in the
    `skill_needs` this plan was actually asked to cover -- the caller's
    `skill_needs` list is authoritative, not whatever a course result
    happens to carry.
    """
    need_nodes = _skill_need_nodes(skill_needs)
    known_need_ids = {need.need_id for need in skill_needs}

    course_nodes: dict[str, PlanNode] = {}
    satisfies_edges: set[tuple[str, str]] = set()
    requires_edges: set[tuple[str, str]] = set()

    def register_satisfies(course_node: PlanNode, matched_needs: list[CareerSkillNeed]) -> None:
        matched_ids = [need.need_id for need in matched_needs if need.need_id in known_need_ids]
        if not matched_ids:
            # Nothing this plan was asked to cover is satisfied by this
            # course; do not add an orphaned course node for it.
            return
        course_nodes.setdefault(course_node.node_id, course_node)
        for need_id in matched_ids:
            satisfies_edges.add((course_node.node_id, skill_need_node_id(need_id)))

    if course_discovery_result is not None:
        for recommendation in course_discovery_result.verified_recommendations:
            course_node = _course_node(recommendation)
            if course_node is None:
                continue
            register_satisfies(course_node, recommendation.matched_needs)

        for blocked in course_discovery_result.prerequisite_blocked:
            blocked_node = _blocked_course_node(blocked)
            if blocked_node is None:
                continue
            dependencies = _prerequisite_dependency_codes(blocked.prerequisite_evaluation)
            matched_ids = [
                need.need_id for need in blocked.matched_needs if need.need_id in known_need_ids
            ]
            if not matched_ids and not dependencies:
                # Nothing this plan covers and no requires edges to own;
                # same orphan-avoidance rule verified recommendations use.
                continue
            course_nodes.setdefault(blocked_node.node_id, blocked_node)
            for need_id in matched_ids:
                satisfies_edges.add((blocked_node.node_id, skill_need_node_id(need_id)))
            for code, status in dependencies:
                prereq_node = _prerequisite_only_node(blocked.institution, code, status)
                if prereq_node is None:
                    continue
                course_nodes.setdefault(prereq_node.node_id, prereq_node)
                requires_edges.add((blocked_node.node_id, prereq_node.node_id))

    all_nodes = sorted(
        [*need_nodes.values(), *course_nodes.values()], key=lambda item: item.node_id
    )
    all_edges = sorted(
        (
            PlanEdge(from_node_id=from_id, to_node_id=to_id, relation="satisfies")
            for from_id, to_id in satisfies_edges
        ),
        key=lambda item: (item.from_node_id, item.to_node_id),
    ) + sorted(
        (
            PlanEdge(from_node_id=from_id, to_node_id=to_id, relation="requires")
            for from_id, to_id in requires_edges
        ),
        key=lambda item: (item.from_node_id, item.to_node_id),
    )

    cycles = detect_cycles(all_nodes, all_edges)
    if cycles:
        return UnifiedActionPlan(
            target_role=target_role,
            nodes=[],
            edges=[],
            conflicts=[],
            execution_status="ERROR",
            failure=PlanFailure(
                error_class="CycleDetected",
                safe_message="The dependency graph contains a cycle and cannot be planned safely.",
            ),
            summary="Graph assembly aborted: a directed dependency cycle was detected.",
        )

    return UnifiedActionPlan(
        target_role=target_role,
        nodes=all_nodes,
        edges=all_edges,
        conflicts=[],
        execution_status="SUCCESS",
        failure=None,
        summary=(
            f"{len(need_nodes)} skill need(s), {len(course_nodes)} course "
            f"node(s), {len(satisfies_edges)} satisfies relationship(s), "
            f"{len(requires_edges)} requires relationship(s)."
            if need_nodes or course_nodes
            else "No skill needs or verified course recommendations were supplied; nothing to plan."
        ),
    )
