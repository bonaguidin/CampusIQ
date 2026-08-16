"""Strict contracts for deterministic course discovery."""

from enum import Enum
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from GradusIQ_career.student_intelligence_profile import StudentIntelligenceProfile
from GradusIQ_career.transcript.catalog import normalize_code


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogInstitution(str, Enum):
    TAMU = "tamu"
    SMU = "smu"


INSTITUTION_NAMES = {
    CatalogInstitution.TAMU: "Texas A&M University",
    CatalogInstitution.SMU: "Southern Methodist University",
}


def resolve_institution(value: str | CatalogInstitution | None) -> CatalogInstitution | None:
    if isinstance(value, CatalogInstitution):
        return value
    normalized = " ".join(str(value or "").lower().split())
    aliases = {
        "tamu": CatalogInstitution.TAMU,
        "texas a&m": CatalogInstitution.TAMU,
        "texas a&m university": CatalogInstitution.TAMU,
        "smu": CatalogInstitution.SMU,
        "southern methodist university": CatalogInstitution.SMU,
    }
    return aliases.get(normalized)


class CatalogProvenance(StrictModel):
    institution: CatalogInstitution
    course_code: str
    catalog_year: str
    source_url: str
    source_last_checked: str


class CourseCatalogRecord(StrictModel):
    institution: CatalogInstitution
    course_code: str
    title: str
    description: str
    department: str
    credit_min: float
    credit_max: float
    course_level: int | None = None
    prerequisite_text: str | None = None
    prerequisite_courses: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)
    cross_listings: list[str] = Field(default_factory=list)
    catalog_year: str
    source_url: str
    source_last_checked: str

    @property
    def provenance(self) -> CatalogProvenance:
        return CatalogProvenance(
            institution=self.institution,
            course_code=self.course_code,
            catalog_year=self.catalog_year,
            source_url=self.source_url,
            source_last_checked=self.source_last_checked,
        )


class CourseSearchQuery(StrictModel):
    institution: CatalogInstitution
    query: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=50)
    subject: str | None = Field(default=None, max_length=8)
    level: int | None = Field(default=None, ge=100, le=900)


class MatchKind(str, Enum):
    COURSE_CODE = "MATCHED_COURSE_CODE"
    TITLE = "MATCHED_TITLE"
    DESCRIPTION = "MATCHED_DESCRIPTION"


class CourseSearchResult(StrictModel):
    course: CourseCatalogRecord
    score: int = Field(ge=0)
    match_kinds: list[MatchKind]
    matched_terms: list[str]


class PrerequisiteCoverage(StrictModel):
    institution: CatalogInstitution
    total_courses: int = Field(ge=0)
    prerequisite_text_courses: int = Field(ge=0)
    parsed_course_code_courses: int = Field(ge=0)
    parsed_restriction_courses: int = Field(ge=0)


class CourseExistenceStatus(str, Enum):
    EXISTS = "EXISTS"
    NOT_FOUND = "NOT_FOUND"


class CourseExistenceResult(StrictModel):
    institution: CatalogInstitution
    requested_code: str
    normalized_code: str | None
    status: CourseExistenceStatus
    course: CourseCatalogRecord | None = None
    provenance: CatalogProvenance | None = None


class PlannedCourseEvidence(StrictModel):
    id: str
    institution: CatalogInstitution
    course_code: str
    term_id: str | None = None
    catalog_course_id: str | None = None


class CourseDiscoveryContext(StrictModel):
    """Trusted scope. Tool arguments never carry a student identifier."""

    profile: StudentIntelligenceProfile
    institution: CatalogInstitution
    planned_courses: list[PlannedCourseEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def home_institution_matches(self):
        resolved = resolve_institution(self.profile.institution.name)
        if resolved is not None and resolved != self.institution:
            raise ValueError("course discovery institution must match the canonical home institution")
        return self

    @property
    def student_id(self) -> str:
        return self.profile.identity.student_id


class StudentCourseState(str, Enum):
    COMPLETED = "COMPLETED"
    IN_PROGRESS = "IN_PROGRESS"
    PLANNED = "PLANNED"
    NOT_TAKEN = "NOT_TAKEN"
    UNKNOWN = "UNKNOWN"


class StudentCourseStatus(StrictModel):
    institution: CatalogInstitution
    course_code: str
    state: StudentCourseState
    matching_record_ids: list[str] = Field(default_factory=list)
    repeat_excluded_record_ids: list[str] = Field(default_factory=list)
    reason: str


class PrerequisiteMode(str, Enum):
    NONE = "NONE"
    ALL = "ALL"
    ANY = "ANY"
    UNRESOLVED = "UNRESOLVED"


class PrerequisiteRequirement(StrictModel):
    mode: PrerequisiteMode
    course_codes: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)
    raw_text: str | None = None
    unresolved_reasons: list[str] = Field(default_factory=list)


class PrerequisiteStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNRESOLVED = "UNRESOLVED"


class PrerequisiteEvaluation(StrictModel):
    status: PrerequisiteStatus
    requirement: PrerequisiteRequirement
    satisfied_courses: list[str] = Field(default_factory=list)
    missing_courses: list[str] = Field(default_factory=list)
    in_progress_courses: list[str] = Field(default_factory=list)
    planned_courses: list[str] = Field(default_factory=list)
    # A prerequisite course code whose student_course_status() came back
    # StudentCourseState.UNKNOWN (unparseable code, or absent from the
    # institution-scoped catalog) previously vanished silently -- it is not
    # satisfied, missing, in-progress, or planned; it is simply unresolvable
    # from current evidence. Already folded into `status` (see
    # evaluate_prerequisites()'s `elif in_progress or unknown: UNRESOLVED`
    # branch); this field only stops discarding *which* codes caused that.
    unknown_courses: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class CourseEligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    ALREADY_PLANNED = "ALREADY_PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COURSE_NOT_FOUND = "COURSE_NOT_FOUND"
    WRONG_INSTITUTION = "WRONG_INSTITUTION"
    UNRESOLVED = "UNRESOLVED"


class CourseEligibilityResult(StrictModel):
    institution: CatalogInstitution
    course_code: str
    status: CourseEligibilityStatus
    exists: bool
    student_status: StudentCourseStatus
    prerequisite_evaluation: PrerequisiteEvaluation | None = None
    reasons: list[str]
    provenance: CatalogProvenance | None = None
    degree_applicability: Literal["UNKNOWN"] = "UNKNOWN"
    offering_status: Literal["UNKNOWN"] = "UNKNOWN"


class EvidenceState(str, Enum):
    VERIFIED_LOCAL = "VERIFIED_LOCAL"
    EXTERNAL_EVIDENCE_PRESENT = "EXTERNAL_EVIDENCE_PRESENT"
    NO_EVIDENCE = "NO_EVIDENCE"
    UNVERIFIED = "UNVERIFIED"


class CareerSkillNeed(StrictModel):
    need_id: str = ""
    skill: str = Field(min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    target_role: str = Field(min_length=1, max_length=150)
    importance: Literal["required", "preferred", "exploratory"]
    evidence_state: EvidenceState
    evidence_source: str = Field(min_length=1, max_length=200)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def assign_stable_id(self):
        if not self.need_id:
            digest = hashlib.sha256(
                f"{self.target_role}|{self.category}|{self.skill}|{self.evidence_source}".lower().encode()
            ).hexdigest()[:12]
            object.__setattr__(self, "need_id", f"need_{digest}")
        return self


class CourseCandidate(StrictModel):
    need: CareerSkillNeed
    search_result: CourseSearchResult
    student_status: StudentCourseStatus
    eligibility: CourseEligibilityResult


class VerificationDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    FLAG = "FLAG"


class FinalCourseVerification(StrictModel):
    disposition: VerificationDisposition
    eligibility: CourseEligibilityResult
    reasons: list[str]


class ToolOperationMetadata(StrictModel):
    tool_name: str
    duration_ms: int = Field(ge=0)
    result_count: int = Field(ge=0)
    status: Literal["success", "not_found", "rejected"]


class SearchCoursesInput(StrictModel):
    query: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=50)


class CourseCodeInput(StrictModel):
    course_code: str = Field(min_length=1, max_length=32)


class ToolResult(StrictModel):
    metadata: ToolOperationMetadata
    results: list[CourseSearchResult] = Field(default_factory=list)
    course: CourseCatalogRecord | None = None
    student_status: StudentCourseStatus | None = None
    eligibility: CourseEligibilityResult | None = None


def canonical_course_code(value: str) -> str | None:
    return normalize_code(value)
