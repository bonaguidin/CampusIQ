"""Small, synthetic C2 evaluation set; execution is fixture-only by default."""

from typing import Literal

from pydantic import Field

from .models import StrictModel


class CourseDiscoveryEvalScenario(StrictModel):
    scenario_id: str = Field(pattern=r"^course_[a-z0-9_]+$")
    purpose: str
    candidate_code: str
    expected_state: Literal["verified", "excluded", "unresolved", "rejected", "empty"]
    live_eligible: Literal[False] = False


C2_SCENARIOS = [
    CourseDiscoveryEvalScenario(scenario_id="course_eligible_match", purpose="Eligible catalog match is verified.", candidate_code="CSCE 110", expected_state="verified"),
    CourseDiscoveryEvalScenario(scenario_id="course_multiple_ranked", purpose="Multiple eligible matches remain bounded and ranked.", candidate_code="CSCE 110", expected_state="verified"),
    CourseDiscoveryEvalScenario(scenario_id="course_completed", purpose="Completed course is excluded.", candidate_code="CSCE 110", expected_state="excluded"),
    CourseDiscoveryEvalScenario(scenario_id="course_planned", purpose="Planned course is excluded.", candidate_code="CSCE 110", expected_state="excluded"),
    CourseDiscoveryEvalScenario(scenario_id="course_missing_prerequisite", purpose="Missing prerequisite is not eligible.", candidate_code="CSCE 221", expected_state="excluded"),
    CourseDiscoveryEvalScenario(scenario_id="course_ambiguous_restriction", purpose="Ambiguous restriction is separated for verification.", candidate_code="CSCE 482", expected_state="unresolved"),
    CourseDiscoveryEvalScenario(scenario_id="course_fabricated", purpose="Fabricated course is rejected.", candidate_code="BUS 301", expected_state="rejected"),
    CourseDiscoveryEvalScenario(scenario_id="course_wrong_institution", purpose="Wrong-institution code is rejected.", candidate_code="CS 1342", expected_state="rejected"),
    CourseDiscoveryEvalScenario(scenario_id="course_honest_empty", purpose="No verified candidate returns an honest empty result.", candidate_code="NONE", expected_state="empty"),
]
