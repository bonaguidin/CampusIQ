"""Typed, deterministic domain contracts for the Phase D unified action plan.

Lives in `action_planning/`, not `planning/` -- `GradusIQ_career/planning/`
already exists and is the unrelated term-organized academic-planning package
(term dates, planned courses, course search). This module has nothing to do
with that one; the name is kept distinct on purpose.

This module defines the plan's shape only. It intentionally contains no graph
construction, no cycle detection, no conflict detection, no sequencing, and no
FIT/GAP/SHIFT/Course Discovery adapters -- those are later, separate units.

Nodes never embed the objects they represent (a `CareerSkillNeed`, a
`VerifiedCourseRecommendation`, ...). They carry a `source_ref` back to
already-validated, already-provenanced data produced elsewhere, so this layer
cannot manufacture evidence -- it can only arrange references to evidence
that already exists.
"""

from typing import Literal

from pydantic import Field, model_validator

from GradusIQ_career.course_discovery.models import StrictModel


NodeType = Literal["skill_need", "course", "project", "experience"]
NodeStatus = Literal["OPEN", "IN_PROGRESS", "SATISFIED"]
EdgeRelation = Literal["requires", "satisfies", "blocks"]
ConflictResolution = Literal["UNRESOLVED", "DEFERRED", "MANUAL_REVIEW_REQUIRED"]
PlanExecutionStatus = Literal["SUCCESS", "PARTIAL", "ERROR"]

# Whether a dependency ordering fully accounts for every requires-relevant
# prerequisite fact the source CourseDiscoveryResult actually knows, or
# whether real prerequisite uncertainty exists that the binary requires graph
# cannot represent (see DependencyOrderLimitation).
DependencyOrderCompleteness = Literal["COMPLETE", "PROVISIONAL"]
DependencyOrderStatus = Literal["ORDERED", "ERROR"]
# Only reasons the existing prerequisite contract can actually prove:
#   ANY_PREREQUISITE       -- PrerequisiteMode.ANY (an alternative set, not a
#                              mandatory edge; see builder.py's ANY-mode note)
#   UNRESOLVED_PREREQUISITE -- PrerequisiteMode.UNRESOLVED (ambiguous catalog
#                              grammar; C1 could not determine the requirement)
#   UNKNOWN_COURSE_STATE    -- a prerequisite code whose student status is
#                              StudentCourseState.UNKNOWN (PrerequisiteEvaluation
#                              .unknown_courses)
DependencyOrderReasonType = Literal[
    "ANY_PREREQUISITE", "UNRESOLVED_PREREQUISITE", "UNKNOWN_COURSE_STATE"
]


class PlanNode(StrictModel):
    node_id: str = Field(min_length=1, max_length=100)
    node_type: NodeType
    # Points back to already-validated, already-provenanced data (e.g. a
    # CareerSkillNeed.need_id, or a course_code/institution pair) -- never a
    # copy of that data.
    source_ref: str = Field(min_length=1, max_length=200)
    status: NodeStatus


class PlanEdge(StrictModel):
    from_node_id: str = Field(min_length=1, max_length=100)
    to_node_id: str = Field(min_length=1, max_length=100)
    relation: EdgeRelation

    @model_validator(mode="after")
    def reject_self_loop(self):
        if self.from_node_id == self.to_node_id:
            raise ValueError("a plan edge cannot connect a node to itself")
        return self


class PlanConflict(StrictModel):
    node_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)
    resolution: ConflictResolution


class PlanFailure(StrictModel):
    """Safe failure envelope; mirrors CourseDiscoveryFailure's shape.

    Reused as-is for DependencyOrderResult's failure state below (its
    category is already generic, not assembly-specific) rather than
    inventing a second failure type for the same "something went wrong,
    here is a safe typed reason" concept.
    """

    category: Literal["PLANNER_FAILURE"] = "PLANNER_FAILURE"
    error_class: str | None = None
    safe_message: str = "Unified action plan could not be assembled safely."


class DependencyOrderLimitation(StrictModel):
    """One reason a dependency ordering is PROVISIONAL rather than COMPLETE,
    tied to the specific node it concerns. Only carries evidence the existing
    PrerequisiteEvaluation contract actually knows -- course_codes is either
    the ANY-mode alternative set or the UNKNOWN-state course codes, verbatim
    from the source evidence, never invented."""

    node_id: str = Field(min_length=1, max_length=100)
    reason_type: DependencyOrderReasonType
    course_codes: list[str] = Field(default_factory=list)


class DependencyOrderResult(StrictModel):
    """A deterministic topological ordering over a UnifiedActionPlan's
    `requires` edges, plus an honest assessment of whether that ordering
    accounts for every prerequisite fact currently known.

    Answers dependency precedence only -- "what must happen before what",
    never calendar/term scheduling. See dependency_order()'s docstring in
    action_planning/query.py for the full contract.
    """

    ordered_node_ids: list[str] = Field(default_factory=list)
    # Action nodes (course/project/experience, never skill_need) that
    # participate in zero `requires` edges -- they have no proven ordering
    # constraint, so they are deliberately kept out of ordered_node_ids
    # rather than assigned an arbitrary position that would imply one.
    unconstrained_node_ids: list[str] = Field(default_factory=list)
    completeness: DependencyOrderCompleteness = "COMPLETE"
    limitations: list[DependencyOrderLimitation] = Field(default_factory=list)
    status: DependencyOrderStatus = "ORDERED"
    failure: PlanFailure | None = None

    @model_validator(mode="after")
    def execution_contract(self):
        if self.status == "ERROR":
            if self.failure is None:
                raise ValueError("an ERROR result requires a PlanFailure")
            if self.ordered_node_ids or self.unconstrained_node_ids or self.limitations:
                raise ValueError("an ERROR result cannot carry partial ordering data")
        else:
            if self.failure is not None:
                raise ValueError("a non-ERROR result must not carry a PlanFailure")
            has_limitations = bool(self.limitations)
            if self.completeness == "COMPLETE" and has_limitations:
                raise ValueError("a COMPLETE result cannot carry any limitations")
            if self.completeness == "PROVISIONAL" and not has_limitations:
                raise ValueError("a PROVISIONAL result requires at least one limitation")
        return self


class UnifiedActionPlan(StrictModel):
    target_role: str = Field(min_length=1, max_length=150)
    nodes: list[PlanNode] = Field(default_factory=list)
    edges: list[PlanEdge] = Field(default_factory=list)
    conflicts: list[PlanConflict] = Field(default_factory=list)
    execution_status: PlanExecutionStatus = "SUCCESS"
    failure: PlanFailure | None = None
    summary: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def unique_node_ids(self):
        seen: set[str] = set()
        for node in self.nodes:
            if node.node_id in seen:
                raise ValueError(f"duplicate node_id: {node.node_id}")
            seen.add(node.node_id)
        return self

    @model_validator(mode="after")
    def references_resolve(self):
        known = {node.node_id for node in self.nodes}
        for edge in self.edges:
            if edge.from_node_id not in known:
                raise ValueError(f"edge references unknown node: {edge.from_node_id}")
            if edge.to_node_id not in known:
                raise ValueError(f"edge references unknown node: {edge.to_node_id}")
        for conflict in self.conflicts:
            for node_id in conflict.node_ids:
                if node_id not in known:
                    raise ValueError(f"conflict references unknown node: {node_id}")
        return self

    @model_validator(mode="after")
    def execution_contract(self):
        if self.execution_status == "ERROR":
            if self.failure is None:
                raise ValueError("an ERROR plan requires a PlanFailure")
            if self.nodes or self.edges or self.conflicts:
                raise ValueError("an ERROR plan cannot carry partial graph data")
        else:
            if self.failure is not None:
                raise ValueError("a non-ERROR plan must not carry a PlanFailure")
            has_unresolved_or_open_conflict = bool(self.conflicts)
            if self.execution_status == "SUCCESS" and has_unresolved_or_open_conflict:
                raise ValueError("a SUCCESS plan cannot carry any residual conflicts")
            if self.execution_status == "PARTIAL" and not has_unresolved_or_open_conflict:
                raise ValueError("a PARTIAL plan requires at least one residual conflict")
        return self
