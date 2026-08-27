"""Domain contracts for the Syllabus What-If Calculator (Phase 1).

Phase 1 defines only the structured shapes: the parsed-document output a
future PDF/Markdown parser will produce, and the versioned grading model a
future LLM-extraction step will populate and a future what-if calculator
will consume. No parsing, LLM calls, persistence, or forecasting logic
lives here -- see planning-docs for the intended pipeline:

    syllabus.pdf -> ParsedSyllabusDocument -> markdown sections ->
    LLM extraction -> GradeModel -> deterministic validation ->
    Validated GradeModel -> What-If Calculator

The calculator must eventually depend only on a validated GradeModel, never
directly on PDF text or raw LLM output -- these models are the seam.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Parsed syllabus document
#
# Future contract: parse_syllabus_pdf(...) -> ParsedSyllabusDocument.
# Deliberately not coupled to any specific parser library (PyMuPDF, Docling,
# Marker, ...) -- that adapter is Phase 2's concern.
# ---------------------------------------------------------------------------

PARSED_SYLLABUS_DOCUMENT_SCHEMA_VERSION = "1"


class ParsedPage(StrictModel):
    page_number: int = Field(ge=1)
    markdown: str


class ParsedSection(StrictModel):
    """One logical section of the syllabus, possibly spanning multiple pages."""

    heading: str
    page_numbers: list[int] = Field(min_length=1)
    markdown: str

    @model_validator(mode="after")
    def page_numbers_are_positive(self):
        if any(page < 1 for page in self.page_numbers):
            raise ValueError("page_numbers must all be >= 1")
        return self


class ParsedDocumentMetadata(StrictModel):
    """Deliberately minimal and extensible -- Phase 2's parser adapter will
    add fields here (e.g. source_filename, parser_name) without requiring a
    schema_version bump as long as the shape stays additive.
    """

    source_filename: str | None = None
    page_count: int | None = Field(default=None, ge=0)
    extra: dict[str, str] = Field(default_factory=dict)


class ParsedSyllabusDocument(StrictModel):
    schema_version: str = PARSED_SYLLABUS_DOCUMENT_SCHEMA_VERSION
    pages: list[ParsedPage] = Field(default_factory=list)
    sections: list[ParsedSection] = Field(default_factory=list)
    markdown: str
    metadata: ParsedDocumentMetadata = Field(default_factory=ParsedDocumentMetadata)


# ---------------------------------------------------------------------------
# Source provenance
#
# Every meaningful extracted grading claim can point back at where it came
# from. Provenance is optional throughout -- manually entered data has none.
# ---------------------------------------------------------------------------


class SourceEvidence(StrictModel):
    page: int | None = Field(default=None, ge=1)
    text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


# ---------------------------------------------------------------------------
# Grade model
# ---------------------------------------------------------------------------

GRADE_MODEL_SCHEMA_VERSION = "1"


class GradingMethod(str, Enum):
    WEIGHTED = "weighted"
    POINTS = "points"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class CourseMetadata(StrictModel):
    course_code: str | None = None
    course_title: str | None = None
    section: str | None = None
    term: str | None = None
    instructor: str | None = None


class GradeCategory(StrictModel):
    """A named bucket of assessments, e.g. 'Lecture Quizzes: 5%'.

    weight and count are independently optional: a syllabus naming a
    category with a percentage but never enumerating how many assessments
    fall under it is common, and count must never be guessed in that case.
    """

    name: str = Field(min_length=1)
    weight: float | None = Field(default=None, ge=0)
    count: int | None = Field(default=None, ge=0)
    evidence: SourceEvidence | None = None


class Assessment(StrictModel):
    """One individual graded item. A syllabus is not required to enumerate
    these -- GradeModel.assessments may be empty even when categories are
    fully populated.
    """

    name: str = Field(min_length=1)
    category: str | None = None
    date: str | None = None
    weight: float | None = Field(default=None, ge=0)
    points: float | None = Field(default=None, ge=0)
    evidence: SourceEvidence | None = None


class GradeThreshold(StrictModel):
    """One letter-grade cutoff. Institutions vary in how they express scales
    (min only, max only, both, non-A-F letters), so at least one bound must
    be present but neither is individually required.
    """

    letter: str = Field(min_length=1)
    minimum: float | None = None
    maximum: float | None = None
    evidence: SourceEvidence | None = None

    @model_validator(mode="after")
    def has_at_least_one_bound(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("grade threshold must specify a minimum, a maximum, or both")
        return self

    @model_validator(mode="after")
    def minimum_not_above_maximum(self):
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        return self


class GradingRuleType(str, Enum):
    REPLACEMENT = "replacement"
    DROP = "drop"
    CURVE = "curve"
    EXTRA_CREDIT = "extra_credit"
    LATE_WORK = "late_work"
    MAKEUP = "makeup"
    OTHER = "other"


class GradingRule(StrictModel):
    """Structured-where-possible extraction of a grading policy sentence.

    Phase 1 only preserves extracted meaning; it is not an executable rules
    engine. `source`/`target` name the categories or assessments a
    replacement/drop rule acts on (e.g. source="Final Exam",
    target="Mid-term Exam"); `condition` is a human/machine-readable
    predicate string (e.g. "final_score > midterm_score") rather than a
    parsed expression tree.
    """

    rule_type: GradingRuleType
    description: str = Field(min_length=1)
    source: str | None = None
    target: str | None = None
    condition: str | None = None
    evidence: SourceEvidence | None = None


class ExtractionWarningType(str, Enum):
    UNKNOWN_ASSESSMENT_COUNT = "unknown_assessment_count"
    UNKNOWN_WEIGHT = "unknown_weight"
    AMBIGUOUS_RULE = "ambiguous_rule"
    POSSIBLE_CURVE = "possible_curve"
    MISSING_GRADE_SCALE = "missing_grade_scale"
    OTHER = "other"


class ExtractionWarning(StrictModel):
    type: ExtractionWarningType
    description: str = Field(min_length=1)
    related_field: str | None = None


class GradeModel(StrictModel):
    schema_version: str = GRADE_MODEL_SCHEMA_VERSION
    course: CourseMetadata = Field(default_factory=CourseMetadata)
    grading_method: GradingMethod = GradingMethod.UNKNOWN
    categories: list[GradeCategory] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)
    grade_thresholds: list[GradeThreshold] = Field(default_factory=list)
    rules: list[GradingRule] = Field(default_factory=list)
    warnings: list[ExtractionWarning] = Field(default_factory=list)
