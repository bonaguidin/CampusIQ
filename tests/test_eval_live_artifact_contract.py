import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from GradusIQ_career.ai.contracts import ChatOutput
from GradusIQ_career.evals import live
from GradusIQ_career.evals.models import EvalFeature, EvalRunResult, ResearchSummary
from GradusIQ_career.evals.run import _atomic_write, main
from GradusIQ_career.evals.runner import run_scenarios
from GradusIQ_career.evals.scenarios import SCENARIOS
from GradusIQ_career.features import role_research_agent


B2R_IDS = (
    "fit_skill_mismatch",
    "fit_market_claim_trap",
    "gap_skill_experience_mismatch",
    "gap_research_fallback",
    "shift_trend_grounding",
    "shift_market_claim_trap",
    "chat_normal_profile",
    "chat_adversarial_history",
)


def by_id(scenario_id):
    return next(item for item in SCENARIOS if item.scenario_id == scenario_id)


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        self.value += 0.001
        return self.value


def trace(feature):
    return {
        "request_id": f"synthetic-{feature.value}",
        "resolved_model": "controlled/model",
        "attempt_count": 1,
        "repair_count": 0,
        "provider_attempt_ms": [7],
        "provider_ms_total": 7,
        "parse_ms": 1 if feature != EvalFeature.CHAT else 0,
        "validation_ms": 1,
        "latency_ms": 9,
        "final_status": "success",
        "error_class": None,
        "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        "grounding_metadata": {
            "source_types": ["synthetic_eval", "onet_static"],
            "attributes": {"role_resolution_sources": {"onet": 1}},
        },
    }


def adapter_executor(monkeypatch, *, research=False, cache_hit=False):
    class FakeRunner:
        def __init__(self, feature, **kwargs):
            self.feature = feature
            self.last_trace = trace(feature)

        def build_student_context(self, profile):
            return {"safe": True}

        def run_canonical(self, canonical, legacy):
            self.build_student_context(legacy)
            if research:
                role_research_agent._account(
                    research_used=True,
                    cache_hit=cache_hit,
                    cache_miss=not cache_hit,
                    research_model_turn_count=0 if cache_hit else 2,
                    tool_call_count=0 if cache_hit else 1,
                    successful_search_count=0 if cache_hit else 1,
                    source_count=1,
                    research_ms=13,
                    research_status="cache_hit" if cache_hit else "success",
                )
            scenario = current_scenario[0]
            return {"status": "success", "data": scenario.fixture_results[self.feature]["data"]}

    class FakeChatRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def invoke_text(self, **kwargs):
            scenario = current_scenario[0]
            return SimpleNamespace(
                output=ChatOutput(content=scenario.fixture_results[EvalFeature.CHAT]["text"]),
                trace=SimpleNamespace(to_dict=lambda: trace(EvalFeature.CHAT)),
            )

    current_scenario = [None]
    for feature in (EvalFeature.FIT, EvalFeature.GAP, EvalFeature.SHIFT):
        monkeypatch.setitem(
            live.RUNNERS,
            feature.value.upper(),
            lambda feature=feature, **kwargs: FakeRunner(feature, **kwargs),
        )
    monkeypatch.setattr(live, "AIRuntime", FakeChatRuntime)

    def execute(scenario, feature):
        current_scenario[0] = scenario
        return live.execute_live(
            scenario, feature, monotonic=Clock(), client_factory=lambda: object()
        )

    return execute


@pytest.mark.parametrize(
    ("scenario_id", "research", "cache_hit"),
    (
        ("fit_skill_mismatch", False, False),
        ("gap_skill_experience_mismatch", False, False),
        ("gap_research_fallback", True, False),
        ("gap_research_fallback", True, True),
        ("shift_trend_grounding", True, False),
        ("chat_adversarial_history", False, False),
    ),
)
def test_live_adapter_result_round_trips_through_strict_contract(
    monkeypatch, scenario_id, research, cache_hit
):
    scenario = by_id(scenario_id)
    executor = adapter_executor(monkeypatch, research=research, cache_hit=cache_hit)
    result = run_scenarios([scenario], live=True, live_executor=executor)[0]
    reloaded = EvalRunResult.model_validate_json(result.model_dump_json())

    assert reloaded.reviewable_output is not None
    assert reloaded.research_summary.research_ms == (13 if research else 0)
    assert reloaded.stage_timing.research_ms == (13 if research else 0)
    assert reloaded.trace_summary.provider_attempt_ms == [7]
    if scenario.features == {EvalFeature.CHAT}:
        assert isinstance(reloaded.reviewable_output, str)
        assert reloaded.safe_grounding_summary.history_count == len(
            scenario.synthetic_input.chat_history
        )
    else:
        assert isinstance(reloaded.reviewable_output, dict)


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"research_used": False, "research_ms": 0},
        {
            "research_used": True,
            "cache_hit": True,
            "research_model_turn_count": 0,
            "tool_call_count": 0,
            "successful_search_count": 0,
            "source_count": 1,
            "research_ms": 4,
        },
        {
            "research_used": True,
            "cache_miss": True,
            "research_model_turn_count": 2,
            "tool_call_count": 1,
            "successful_search_count": 1,
            "source_count": 1,
            "research_ms": 13,
        },
    ),
)
def test_research_summary_accepts_supported_counter_and_timing_shapes(payload):
    assert ResearchSummary.model_validate(payload).research_ms >= 0


def test_research_summary_rejects_negative_timing_and_unknown_fields():
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        ResearchSummary.model_validate({"research_ms": -1})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResearchSummary.model_validate({"research_ms": 0, "raw_snippets": []})


def test_exact_eight_b2r_scenarios_complete_incremental_mock_artifact(tmp_path, monkeypatch):
    scenarios = [by_id(scenario_id) for scenario_id in B2R_IDS]
    executor = adapter_executor(monkeypatch, research=True)
    output = tmp_path / "b2r-dry.json"
    artifact = {
        "artifact_version": "2.0",
        "run_status": "incomplete",
        "planned": 8,
        "completed": 0,
        "results": [],
    }
    _atomic_write(output, artifact)

    def retain(result, completed, planned):
        artifact["planned"] = planned
        artifact["completed"] = completed
        artifact["results"].append(result.model_dump(mode="json"))
        _atomic_write(output, artifact)

    results = run_scenarios(
        scenarios, live=True, live_executor=executor, on_result=retain
    )
    artifact["run_status"] = "complete"
    _atomic_write(output, artifact)
    reloaded = json.loads(output.read_text())

    assert reloaded["planned"] == reloaded["completed"] == len(results) == 8
    assert reloaded["run_status"] == "complete"
    assert {item["feature"] for item in reloaded["results"]} == {
        "fit", "gap", "shift", "chat"
    }
    assert all(EvalRunResult.model_validate(item) for item in reloaded["results"])
    rendered = output.read_text()
    for forbidden in (
        "Authorization", "raw_provider_response", '"canonical_profile":',
        "chat_history", "environment", "tavily_snippet", "synthetic-eval-student",
    ):
        assert forbidden not in rendered


def test_live_shaped_interruption_retains_two_typed_results(tmp_path, monkeypatch):
    scenarios = [by_id(scenario_id) for scenario_id in B2R_IDS]
    adapter = adapter_executor(monkeypatch, research=True)
    calls = 0
    output = tmp_path / "b2r-interrupted.json"
    artifact = {
        "artifact_version": "2.0", "run_status": "incomplete",
        "planned": 8, "completed": 0, "results": [],
    }
    _atomic_write(output, artifact)

    def interrupting_executor(scenario, feature):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt
        return adapter(scenario, feature)

    def retain(result, completed, planned):
        artifact["planned"] = planned
        artifact["completed"] = completed
        artifact["results"].append(result.model_dump(mode="json"))
        _atomic_write(output, artifact)

    with pytest.raises(KeyboardInterrupt):
        run_scenarios(
            scenarios, live=True, live_executor=interrupting_executor,
            on_result=retain,
        )
    reloaded = json.loads(output.read_text())
    assert reloaded["run_status"] == "incomplete"
    assert reloaded["planned"] == 8 and reloaded["completed"] == 2
    assert len(reloaded["results"]) == 2
    assert all(EvalRunResult.model_validate(item) for item in reloaded["results"])
    assert not list(output.parent.glob(f".{output.name}.*"))


def test_live_progress_remains_safe_metadata_only(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRADUSIQ_EVAL_LIVE", "1")
    scenario = by_id("fit_skill_mismatch")
    observation = dict(scenario.fixture_results[EvalFeature.FIT])
    observation["research_summary"] = {"research_ms": 0}
    monkeypatch.setattr(live, "execute_live", lambda *_: observation)
    assert main([
        "--live", "--scenario", scenario.scenario_id,
        "--output", "eval-results/progress.json",
    ]) == 0
    stdout = capsys.readouterr().out
    assert "[1/1] FIT fit_skill_mismatch started" in stdout
    assert "completed status=" in stdout
    assert "synthetic-eval-student" not in stdout
    assert "reviewable_output" not in stdout
