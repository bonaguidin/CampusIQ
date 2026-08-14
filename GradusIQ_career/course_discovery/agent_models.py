"""Strict model-owned proposal and deterministic final-result contracts."""

from typing import Literal

from pydantic import Field, model_validator

from .models import (
    CareerSkillNeed,
    CatalogInstitution,
    CatalogProvenance,
    CourseEligibilityResult,
    CourseEligibilityStatus,
    CourseSearchResult,
    MatchKind,
    PrerequisiteStatus,
    StrictModel,
    StudentCourseState,
    canonical_course_code,
)


MAX_PROPOSALS = 10
MAX_VERIFIED_RECOMMENDATIONS = 5


class QualifiedCourseCandidate(StrictModel):
    """One observed catalog result qualified by the trusted C1 service."""

    search_result: CourseSearchResult
    eligibility: CourseEligibilityResult


class ProposedCourse(StrictModel):
    course_code: str = Field(min_length=1, max_length=32)
    matched_need_ids: list[str] = Field(min_length=1, max_length=8)
    ranking_reason: str = Field(min_length=1, max_length=500)
    skill_alignment_explanation: str = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def exact_code_and_unique_needs(self):
        normalized = canonical_course_code(self.course_code)
        if normalized is None or normalized != self.course_code:
            raise ValueError("course_code must be an exact normalized institutional code")
        if len(self.matched_need_ids) != len(set(self.matched_need_ids)):
            raise ValueError("matched_need_ids must be unique")
        return self


class CourseDiscoveryProposal(StrictModel):
    proposals: list[ProposedCourse] = Field(default_factory=list, max_length=MAX_PROPOSALS)

    @model_validator(mode="after")
    def unique_courses(self):
        codes = [item.course_code for item in self.proposals]
        if len(codes) != len(set(codes)):
            raise ValueError("course proposals must be unique")
        return self


class VerifiedCourseRecommendation(StrictModel):
    institution: CatalogInstitution
    course_code: str
    title: str
    description: str
    credit_min: float
    credit_max: float
    matched_needs: list[CareerSkillNeed]
    match_kinds: list[MatchKind]
    matched_terms: list[str]
    student_status: StudentCourseState
    prerequisite_status: PrerequisiteStatus
    eligibility_status: Literal[CourseEligibilityStatus.ELIGIBLE]
    provenance: CatalogProvenance
    ranking_reason: str
    skill_alignment_explanation: str
    degree_applicability: Literal["UNKNOWN"] = "UNKNOWN"
    offering_status: Literal["UNKNOWN"] = "UNKNOWN"


class UnresolvedCourseCandidate(StrictModel):
    institution: CatalogInstitution
    course_code: str
    title: str
    matched_needs: list[CareerSkillNeed]
    match_kinds: list[MatchKind]
    eligibility_status: Literal[CourseEligibilityStatus.UNRESOLVED]
    reasons: list[str]
    provenance: CatalogProvenance


class CourseDiscoveryResult(StrictModel):
    target_role: str
    current_major: str | None = None
    intended_major: str | None = None
    career_needs: list[CareerSkillNeed]
    verified_recommendations: list[VerifiedCourseRecommendation] = Field(
        default_factory=list, max_length=MAX_VERIFIED_RECOMMENDATIONS
    )
    requires_verification: list[UnresolvedCourseCandidate] = Field(default_factory=list, max_length=5)
    summary: str
    degree_applicability: Literal["UNKNOWN"] = "UNKNOWN"
    offering_status: Literal["UNKNOWN"] = "UNKNOWN"


class SafeToolTrace(StrictModel):
    tool_name: str
    duration_ms: int = Field(ge=0)
    status: str
    result_count: int = Field(ge=0)


class CourseDiscoveryTrace(StrictModel):
    request_id: str
    feature: Literal["COURSE_DISCOVERY"] = "COURSE_DISCOVERY"
    prompt_name: Literal["course_discovery"] = "course_discovery"
    prompt_version: Literal["1.0", "1.1", "1.2"] = "1.2"
    model_role: Literal["course_discovery"] = "course_discovery"
    resolved_model: str | None = None
    tool_rounds: int = 0
    tool_call_count: int = 0
    tool_execution_count: int = 0
    search_call_count: int = 0
    lookup_count: int = 0
    status_check_count: int = 0
    eligibility_check_count: int = 0
    deduplicated_call_count: int = 0
    policy_rejected_call_count: int = 0
    candidate_count: int = 0
    qualified_candidate_count: int = 0
    qualification_batch_count: int = 0
    eligible_candidate_count: int = 0
    completed_candidate_count: int = 0
    planned_candidate_count: int = 0
    in_progress_candidate_count: int = 0
    ineligible_candidate_count: int = 0
    unresolved_candidate_count: int = 0
    proposal_count: int = 0
    verified_count: int = 0
    unresolved_count: int = 0
    rejected_count: int = 0
    provider_ms: int = 0
    tool_ms: int = 0
    verification_ms: int = 0
    total_ms: int = 0
    attempt_count: int = 0
    repair_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    final_status: Literal["success", "failed"] = "failed"
    error_class: str | None = None
    tool_trace: list[SafeToolTrace] = Field(default_factory=list)


class CourseDiscoveryAgentResult(StrictModel):
    result: CourseDiscoveryResult | None = None
    trace: CourseDiscoveryTrace
    errors: list[str] = Field(default_factory=list)
