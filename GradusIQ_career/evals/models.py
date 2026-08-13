from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvalFeature(str, Enum):
    FIT = "fit"
    GAP = "gap"
    SHIFT = "shift"
    CHAT = "chat"


class EvalStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIABLE = "UNVERIFIABLE"
    ERROR = "ERROR"


class EvalExpectation(StrictModel):
    check: str
    description: str


class EvalScenario(StrictModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    scenario_version: str = "1.0"
    purpose: str
    features: set[EvalFeature]
    expectations: list[EvalExpectation]
    fixture_results: dict[EvalFeature, dict[str, Any]]
    student_evidence: list[str] = Field(default_factory=list)
    grounding_evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def fixtures_match_features(self):
        if not set(self.fixture_results).issubset(self.features):
            raise ValueError("fixture result feature is not applicable to the scenario")
        return self


class EvalMetric(StrictModel):
    name: str
    status: EvalStatus
    detail: str | None = None


class EvalRunResult(StrictModel):
    scenario_id: str
    scenario_version: str
    feature: EvalFeature
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


def validate_unique_scenarios(scenarios: list[EvalScenario]) -> None:
    ids = [scenario.scenario_id for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("Evaluation scenario IDs must be unique.")
