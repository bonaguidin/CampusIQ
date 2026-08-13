import json

import pytest
from pydantic import ValidationError

from GradusIQ_career.evals.evaluators import aggregate, evaluate_fixture
from GradusIQ_career.evals.models import EvalFeature, EvalRunResult, EvalScenario, EvalStatus, validate_unique_scenarios
from GradusIQ_career.evals.run import main
from GradusIQ_career.evals.runner import compare_runs, run_scenarios
from GradusIQ_career.evals.scenarios import SCENARIOS


def test_scenarios_are_valid_unique_and_synthetic():
    assert 10 <= len(SCENARIOS) <= 15
    validate_unique_scenarios(SCENARIOS)
    rendered = json.dumps([item.model_dump(mode="json") for item in SCENARIOS])
    assert "@" not in rendered
    assert "private-student-id" not in rendered


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match="unique"):
        validate_unique_scenarios([SCENARIOS[0], SCENARIOS[0]])


def test_scenario_rejects_non_applicable_fixture():
    payload = SCENARIOS[0].model_dump()
    payload["fixture_results"][EvalFeature.CHAT] = {"text": "hello"}
    with pytest.raises(ValidationError):
        EvalScenario.model_validate(payload)


def test_fixture_run_filtering_serialization_and_no_network(monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *a, **k: pytest.fail("network forbidden"))
    results = run_scenarios(SCENARIOS, feature=EvalFeature.CHAT, scenario_id="student_prompt_injection")
    assert len(results) == 1
    assert results[0].feature == EvalFeature.CHAT
    EvalRunResult.model_validate_json(results[0].model_dump_json())


def test_deterministic_pass_fail_unverifiable_and_error():
    grounded = SCENARIOS[0]
    passed = evaluate_fixture(grounded, EvalFeature.FIT, grounded.fixture_results[EvalFeature.FIT])
    assert aggregate(passed) == EvalStatus.PASS

    trap = next(item for item in SCENARIOS if item.scenario_id == "shift_market_claim_trap")
    bad = dict(trap.fixture_results[EvalFeature.SHIFT])
    bad["data"] = dict(bad["data"], role_evolution_summary="There are 42 current local jobs.")
    assert aggregate(evaluate_fixture(trap, EvalFeature.SHIFT, bad)) == EvalStatus.FAIL

    unverifiable = run_scenarios([next(item for item in SCENARIOS if item.scenario_id == "fit_market_claim_trap")])[0]
    assert unverifiable.status == EvalStatus.UNVERIFIABLE
    assert aggregate(evaluate_fixture(grounded, EvalFeature.FIT, "bad")) == EvalStatus.ERROR


def test_baseline_comparison_reports_stable_metrics():
    before = run_scenarios(SCENARIOS[:2])
    after = [item.model_copy(update={"latency_ms": 10, "total_tokens": 5, "attempt_count": 1}) for item in before]
    comparison = compare_runs(before, after)
    assert comparison["after"]["latency_ms"] == 20
    assert comparison["after"]["total_tokens"] == 10
    assert comparison["after"]["attempts"] == 2


def test_explicit_baseline_creation_never_overwrites(tmp_path):
    baseline = tmp_path / "reviewed-baseline.json"
    assert main(["--baseline-output", str(baseline)]) == 0
    original = baseline.read_text()
    with pytest.raises(SystemExit):
        main(["--baseline-output", str(baseline)])
    assert baseline.read_text() == original


def test_cli_fixture_mode_and_live_requires_double_opt_in(tmp_path, monkeypatch, capsys):
    output = tmp_path / "eval.json"
    assert main(["--feature", "chat", "--output", str(output)]) == 0
    assert json.loads(output.read_text())["results"]
    monkeypatch.delenv("GRADUSIQ_EVAL_LIVE", raising=False)
    with pytest.raises(SystemExit):
        main(["--live"])
    assert '"run_status": "complete"' in capsys.readouterr().out


def test_live_mode_is_explicit_and_bounded(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setenv("GRADUSIQ_EVAL_LIVE", "1")
    monkeypatch.setattr(
        "GradusIQ_career.evals.live.execute_live",
        lambda scenario, feature: calls.append((scenario.scenario_id, feature)) or scenario.fixture_results[feature],
    )
    monkeypatch.chdir(tmp_path)
    assert main(["--live", "--output", "eval-results/live.json"]) == 0
    assert len(calls) == 12
    assert '"run_status": "complete"' in capsys.readouterr().out

    with pytest.raises(SystemExit):
        main(["--live", "--max-runs", "13", "--output", "eval-results/live.json"])
