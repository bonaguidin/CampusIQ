import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from GradusIQ_career.course_discovery.agent_models import (
    CourseDiscoveryResult,
    CourseDiscoveryTrace,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvalFeature(str, Enum):
    FIT = "fit"
    GAP = "gap"
    SHIFT = "shift"
    CHAT = "chat"
    COURSE_DISCOVERY = "course_discovery"


class EvalStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIABLE = "UNVERIFIABLE"
    ERROR = "ERROR"


class EvalExpectation(StrictModel):
    check: str
    description: str


class CourseDiscoveryExpectation(StrictModel):
    candidate_code: str
    expected_state: str


class SyntheticExperience(StrictModel):
    role: str
    employer: str | None = None


class SyntheticProject(StrictModel):
    name: str
    description: str | None = None


class SyntheticCourse(StrictModel):
    course_code: str
    title: str
    credit_hours: float = Field(default=3.0, gt=0, le=12)
    letter_grade: str | None = None
    status: str = "completed"


class SyntheticChatTurn(StrictModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=2000)


class SyntheticStudentInput(StrictModel):
    institution: str = "Synthetic University"
    current_major: str | None = None
    intended_major: str | None = None
    classification: str | None = "Junior"
    expected_graduation: str | None = "Spring 2028"
    target_roles: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    technical_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    experience: list[SyntheticExperience] = Field(default_factory=list)
    projects: list[SyntheticProject] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    completed_courses: list[SyntheticCourse] = Field(default_factory=list)
    in_progress_courses: list[SyntheticCourse] = Field(default_factory=list)
    planned_courses: list[SyntheticCourse] = Field(default_factory=list)
    career_goals: str | None = None
    chat_question: str | None = None
    chat_history: list[SyntheticChatTurn] = Field(default_factory=list, max_length=12)
    adversarial_instruction: str | None = Field(default=None, max_length=500)

    def safe_fingerprint(self) -> str:
        normalized = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class EvalScenario(StrictModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    scenario_version: str = "1.0"
    purpose: str
    live_eligible: bool = False
    synthetic_input: SyntheticStudentInput
    features: set[EvalFeature]
    expectations: list[EvalExpectation]
    fixture_results: dict[EvalFeature, dict[str, Any]]
    student_evidence: list[str] = Field(default_factory=list)
    grounding_evidence: list[str] = Field(default_factory=list)
    course_discovery_expectation: CourseDiscoveryExpectation | None = None

    @model_validator(mode="after")
    def fixtures_match_features(self):
        if not set(self.fixture_results).issubset(self.features):
            raise ValueError("fixture result feature is not applicable to the scenario")
        if self.live_eligible and (not self.purpose.strip() or not self.expectations):
            raise ValueError("live scenarios require a purpose and expected invariants")
        if self.live_eligible and len(self.features) != 1:
            raise ValueError("live scenarios must target exactly one feature")
        return self


class EvalMetric(StrictModel):
    name: str
    status: EvalStatus
    detail: str | None = None


class SafeGroundingSummary(StrictModel):
    source_categories: list[str] = Field(default_factory=list)
    grounded_target_roles: list[str] = Field(default_factory=list)
    onet_evidence_present: bool = False
    employer_posting_evidence_supplied: bool = False
    role_resolution_sources: dict[str, int] = Field(default_factory=dict)
    supplied_course_count: int = 0
    supplied_certification_count: int = 0
    canonical_profile_used: bool = False
    history_count: int = 0
    tools_available: bool = False
    persistent_memory_available: bool = False
    source_status: str = "SOURCE_NOT_PRESENT"


class ResearchSummary(StrictModel):
    research_used: bool = False
    cache_hit: bool = False
    cache_miss: bool = False
    research_model_turn_count: int = 0
    tool_call_count: int = 0
    successful_search_count: int = 0
    source_count: int = 0
    # Also appears in StageTiming as the unified end-to-end stage view; here it
    # travels with the counters/status that explain the research operation.
    research_ms: int = Field(default=0, ge=0)
    research_status: str = "not_used"


class StageTiming(StrictModel):
    context_ms: int = 0
    grounding_ms: int = 0
    research_ms: int = 0
    provider_ms: int = 0
    parse_ms: int = 0
    validation_ms: int = 0
    total_ms: int = 0


class TraceSummary(StrictModel):
    request_id: str | None = None
    attempt_count: int = 0
    repair_count: int = 0
    provider_attempt_ms: list[int] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    final_status: str = "failed"
    error_class: str | None = None


class ReviewConvenience(StrictModel):
    course_recommendations: list[str] = Field(default_factory=list)
    certification_recommendations: list[str] = Field(default_factory=list)


class CourseDiscoveryToolSummary(StrictModel):
    tool_rounds: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    search_courses_count: int = Field(default=0, ge=0)
    get_course_count: int = Field(default=0, ge=0)
    student_status_count: int = Field(default=0, ge=0)
    eligibility_count: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    proposal_count: int = Field(default=0, ge=0)
    verified_count: int = Field(default=0, ge=0)
    unresolved_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)


class CourseDiscoveryReview(StrictModel):
    institution: str
    validated_result: CourseDiscoveryResult
    safe_trace: CourseDiscoveryTrace
    tool_summary: CourseDiscoveryToolSummary
    rejection_reasons: dict[str, int] = Field(default_factory=dict)


class EvalRunResult(StrictModel):
    scenario_id: str
    scenario_version: str
    feature: EvalFeature
    purpose: str = ""
    input_fingerprint: str = ""
    prompt_name: str
    prompt_version: str
    model: str | None = None
    status: EvalStatus
    metrics: list[EvalMetric]
    latency_ms: int = 0
    attempt_count: int = 0
    repair_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    grounding_status: EvalStatus = EvalStatus.UNVERIFIABLE
    reviewable_output: dict[str, Any] | str | None = None
    safe_grounding_summary: SafeGroundingSummary = Field(default_factory=SafeGroundingSummary)
    research_summary: ResearchSummary = Field(default_factory=ResearchSummary)
    stage_timing: StageTiming = Field(default_factory=StageTiming)
    trace_summary: TraceSummary = Field(default_factory=TraceSummary)
    review_convenience: ReviewConvenience = Field(default_factory=ReviewConvenience)
    course_discovery_review: CourseDiscoveryReview | None = None


def validate_unique_scenarios(scenarios: list[EvalScenario]) -> None:
    ids = [scenario.scenario_id for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("Evaluation scenario IDs must be unique.")
