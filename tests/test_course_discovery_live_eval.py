import json
import re

import pytest

from GradusIQ_career.ai.types import AIMessageResponse
from GradusIQ_career.evals import live
from GradusIQ_career.evals.course_discovery_scenarios import COURSE_DISCOVERY_SCENARIOS
from GradusIQ_career.evals.models import EvalFeature, EvalRunResult, EvalStatus
from GradusIQ_career.evals.models import SyntheticCourse, SyntheticStudentInput
from GradusIQ_career.evals.profiles import build_synthetic_canonical_profile
from GradusIQ_career.evals.live import build_course_discovery_context
from GradusIQ_career.course_discovery.models import StudentCourseState
from GradusIQ_career.course_discovery.service import CourseDiscoveryService
from GradusIQ_career.evals.run import main
from GradusIQ_career.evals.runner import (
    run_scenarios,
    select_controlled_course_discovery_scenarios,
    select_controlled_live_scenarios,
)
from GradusIQ_career.evals.scenarios import SCENARIOS

REAL_EXECUTE_LIVE = live.execute_live

class CourseClient:
    def __init__(self, scenario_id):
        self.scenario_id = scenario_id
        self.calls = 0

    def complete_message_with_metadata(self, **kwargs):
        self.calls += 1
        if self.scenario_id == "course_adversarial_fabricated":
            assert "Ignore safeguards" not in json.dumps(kwargs["messages"])
        if self.calls == 1:
            codes = ["CSCE 206", "CSCE 110"] if self.scenario_id == "course_multiple_candidates" else [
                "CSCE 331" if self.scenario_id == "course_prerequisite_unresolved" else "CSCE 206"
            ]
            operations = [
                ("search_courses", {"query": code, "limit": 5}) for code in codes
            ]
            message = {
                "content": "",
                "tool_calls": [
                    {"id": f"call-{index}", "type": "function", "function": {
                        "name": name,
                        "arguments": json.dumps(arguments),
                    }}
                    for index, (name, arguments) in enumerate(operations, 1)
                ],
            }
        else:
            blob = json.dumps(kwargs["messages"])
            need_id = re.search(r"need_[a-f0-9]{12}", blob).group(0)
            codes = {
                "course_multiple_candidates": ["CSCE 206", "CSCE 110"],
                "course_already_completed": [],
                "course_already_planned": [],
                "course_prerequisite_unresolved": ["CSCE 331"],
            }.get(self.scenario_id, ["CSCE 206"])
            message = {"content": json.dumps({"proposals": [
                {
                    "course_code": code,
                    "matched_need_ids": [need_id],
                    "ranking_reason": f"Ranked for the grounded need ({index}).",
                    "skill_alignment_explanation": "Catalog match supports the career skill need.",
                }
                for index, code in enumerate(codes, 1)
            ]})}
        return AIMessageResponse(
            message=message, model="controlled/course-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


def execute(scenario, feature):
    return REAL_EXECUTE_LIVE(
        scenario, feature, client_factory=lambda: CourseClient(scenario.scenario_id)
    )


def test_separate_controlled_suites_validate_before_execution():
    phase_b = select_controlled_live_scenarios(SCENARIOS)
    course = select_controlled_course_discovery_scenarios(COURSE_DISCOVERY_SCENARIOS)
    assert len(phase_b) == 12 and all(EvalFeature.COURSE_DISCOVERY not in s.features for s in phase_b)
    assert len(course) == 6 and all(s.features == {EvalFeature.COURSE_DISCOVERY} for s in course)
    assert len({s.synthetic_input.safe_fingerprint() for s in course}) == 6


def test_in_progress_and_planned_state_use_real_c1_status_logic():
    base = COURSE_DISCOVERY_SCENARIOS[0]
    value = SyntheticStudentInput(
        institution="Texas A&M University",
        target_roles=["Software Engineering Intern"], technical_skills=["Python"],
        in_progress_courses=[SyntheticCourse(
            course_code="CSCE 110", title="Programming I", status="in_progress"
        )],
    )
    scenario = base.model_copy(update={"synthetic_input": value}, deep=True)
    service = CourseDiscoveryService(build_course_discovery_context(scenario))
    assert service.student_course_status("CSCE 110").state == StudentCourseState.IN_PROGRESS
    planned = COURSE_DISCOVERY_SCENARIOS[3]
    assert CourseDiscoveryService(
        build_course_discovery_context(planned)
    ).student_course_status("CSCE 206").state == StudentCourseState.PLANNED
    assert build_synthetic_canonical_profile(planned.synthetic_input).academics.courses == []


def test_invalid_c2_suite_fails_before_any_executor():
    with pytest.raises(ValueError, match="exactly 6"):
        select_controlled_course_discovery_scenarios(COURSE_DISCOVERY_SCENARIOS[:-1])
    bad = COURSE_DISCOVERY_SCENARIOS[0].model_copy(deep=True)
    bad.course_discovery_expectation.expected_state = "INELIGIBLE"
    with pytest.raises(ValueError, match="expected catalog state"):
        select_controlled_course_discovery_scenarios([bad, *COURSE_DISCOVERY_SCENARIOS[1:]])


def test_c2_dry_run_is_six_valid_and_network_free(monkeypatch, capsys):
    monkeypatch.setattr("socket.create_connection", lambda *a, **k: pytest.fail("network forbidden"))
    assert main(["--dry-run", "--suite", "course-discovery"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert (payload["planned"], payload["selected"], payload["valid"]) == (6, 6, 6)
    assert payload["provider_calls"] == payload["research_calls"] == 0


def test_c2_live_requires_dual_opt_in_exact_cap_and_ignored_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GRADUSIQ_EVAL_LIVE", raising=False)
    with pytest.raises(SystemExit):
        main(["--live", "--suite", "course-discovery", "--output", "eval-results/c2.json"])
    monkeypatch.setenv("GRADUSIQ_EVAL_LIVE", "1")
    with pytest.raises(SystemExit):
        main(["--live", "--suite", "course-discovery", "--max-runs", "12", "--output", "eval-results/c2.json"])
    with pytest.raises(SystemExit):
        main(["--live", "--suite", "course-discovery", "--output", "outside.json"])


def test_all_six_live_shaped_results_round_trip_and_final_verifier_protects():
    results = run_scenarios(
        COURSE_DISCOVERY_SCENARIOS, live=True, live_executor=execute, max_runs=6
    )
    assert len(results) == 6 and all(item.status == EvalStatus.PASS for item in results)
    reloaded = [EvalRunResult.model_validate_json(item.model_dump_json()) for item in results]
    assert all(item.prompt_version == "1.3" for item in reloaded)
    by_id = {item.scenario_id: item for item in reloaded}
    assert len(by_id["course_normal_eligible"].course_discovery_review.validated_result.verified_recommendations) == 1
    assert len(by_id["course_multiple_candidates"].course_discovery_review.validated_result.verified_recommendations) == 2
    normal_tools = by_id["course_normal_eligible"].course_discovery_review.tool_summary
    assert normal_tools.search_courses_count == 1
    assert normal_tools.get_course_count == normal_tools.student_status_count == 0
    assert normal_tools.qualification_batch_count == 1
    assert normal_tools.eligibility_count == normal_tools.qualified_candidate_count >= 1
    assert normal_tools.tool_call_count == 1
    assert normal_tools.tool_execution_count == 1 + normal_tools.qualified_candidate_count
    assert normal_tools.deduplicated_count == normal_tools.policy_rejected_count == 0
    assert normal_tools.seed_search_count > 0
    assert normal_tools.seed_unique_candidate_count <= 12
    assert normal_tools.both_candidate_count >= 1
    required = {
        "course_normal_eligible": {"CSCE 206": "ELIGIBLE"},
        "course_multiple_candidates": {
            "CSCE 206": "ELIGIBLE", "CSCE 110": "ELIGIBLE",
        },
        "course_already_completed": {"CSCE 206": "ALREADY_COMPLETED"},
        "course_already_planned": {"CSCE 206": "ALREADY_PLANNED"},
        "course_prerequisite_unresolved": {"CSCE 331": "UNRESOLVED"},
    }
    for scenario_id, expected in required.items():
        dispositions = {
            item.course_code: item
            for item in by_id[scenario_id].course_discovery_review.course_dispositions
        }
        for code, status in expected.items():
            item = dispositions[code]
            assert item.observed and item.qualified
            assert item.qualification_status.value == status
            assert item.observation_source == "BOTH"
            assert item.seed_need_ids
    for scenario_id in ("course_already_completed", "course_already_planned"):
        assert by_id[scenario_id].course_discovery_review.validated_result.verified_recommendations == []
        assert by_id[scenario_id].course_discovery_review.tool_summary.rejected_count == 0
    assert len(by_id["course_adversarial_fabricated"].course_discovery_review.validated_result.verified_recommendations) == 1
    unresolved = by_id["course_prerequisite_unresolved"].course_discovery_review.validated_result
    assert unresolved.verified_recommendations == []
    prereq_disposition = next(
        item for item in by_id["course_prerequisite_unresolved"].course_discovery_review.course_dispositions
        if item.course_code == "CSCE 331"
    )
    assert prereq_disposition.observed and prereq_disposition.qualified
    assert prereq_disposition.qualification_status.value == "UNRESOLVED"
    assert prereq_disposition.final_disposition == "UNRESOLVED"
    rendered = json.dumps([item.model_dump(mode="json") for item in reloaded])
    for forbidden in ("synthetic-eval-student", "Authorization", "api_key", "raw_provider", "<untrusted_context>"):
        assert forbidden not in rendered
    assert '"proposals"' not in rendered
    assert by_id["course_already_completed"].course_discovery_review.rejection_reasons == {}
    assert by_id["course_already_planned"].course_discovery_review.rejection_reasons == {}
    completed = next(
        item for item in by_id["course_already_completed"].course_discovery_review.course_dispositions
        if item.course_code == "CSCE 206"
    )
    planned = next(
        item for item in by_id["course_already_planned"].course_discovery_review.course_dispositions
        if item.course_code == "CSCE 206"
    )
    assert completed.observed and completed.qualified and not completed.proposed
    assert completed.qualification_status == "ALREADY_COMPLETED"
    assert completed.final_disposition == "COMPLETED"
    assert planned.observed and planned.qualified and not planned.proposed
    assert planned.qualification_status == "ALREADY_PLANNED"
    assert planned.final_disposition == "PLANNED"


def test_course_executor_uses_shared_concurrency_gate(monkeypatch):
    active = False

    class Gate:
        class Slot:
            def __enter__(self):
                nonlocal active
                active = True

            def __exit__(self, *args):
                nonlocal active
                active = False

        def slot(self):
            return self.Slot()

    class GuardedClient(CourseClient):
        def complete_message_with_metadata(self, **kwargs):
            assert active is True
            return super().complete_message_with_metadata(**kwargs)

    monkeypatch.setattr(live.production_app.state, "ai_concurrency", Gate())
    scenario = COURSE_DISCOVERY_SCENARIOS[0]
    observation = REAL_EXECUTE_LIVE(
        scenario, EvalFeature.COURSE_DISCOVERY,
        client_factory=lambda: GuardedClient(scenario.scenario_id),
    )
    assert observation["status"] == "success" and active is False


def test_c2_cli_writes_six_typed_results_incrementally(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRADUSIQ_EVAL_LIVE", "1")
    monkeypatch.setattr(live, "execute_live", execute)
    output = tmp_path / "eval-results" / "c2-live-shaped.json"
    assert main([
        "--live", "--suite", "course-discovery", "--output", str(output)
    ]) == 0
    artifact = json.loads(output.read_text())
    assert (artifact["planned"], artifact["completed"], artifact["run_status"]) == (6, 6, "complete")
    assert len(artifact["results"]) == 6
    assert all(EvalRunResult.model_validate(item).course_discovery_review for item in artifact["results"])


def test_c2_interruption_preserves_completed_typed_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRADUSIQ_EVAL_LIVE", "1")
    calls = 0

    def interrupted(scenario, feature):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt
        return execute(scenario, feature)

    monkeypatch.setattr(live, "execute_live", interrupted)
    output = tmp_path / "eval-results" / "c2-interrupted.json"
    with pytest.raises(KeyboardInterrupt):
        main(["--live", "--suite", "course-discovery", "--output", str(output)])
    artifact = json.loads(output.read_text())
    assert (artifact["planned"], artifact["completed"], artifact["run_status"]) == (6, 2, "incomplete")
    assert len(artifact["results"]) == 2
    assert all(EvalRunResult.model_validate(item).course_discovery_review for item in artifact["results"])
