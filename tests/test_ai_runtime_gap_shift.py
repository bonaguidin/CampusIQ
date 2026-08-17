import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from GradusIQ_career import api
from GradusIQ_career.ai.contracts import GapOutput, ShiftOutput, feature_output_is_valid
from GradusIQ_career.ai.errors import AIRequestError
from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.ai.types import AIResponse
from GradusIQ_career.features import gap as gap_module
from GradusIQ_career.features import shift as shift_module
from GradusIQ_career.features.gap import GapRunner
from GradusIQ_career.features.shift import ShiftRunner
from GradusIQ_career.student_intelligence_profile import StudentIntelligenceProfile


GAP_DATA = {
    "readiness_score": 6,
    "strengths": [{"strength": "Python", "framing": "Use it in project examples."}],
    "must_have_gaps": [
        {"gap": "SQL", "why_it_matters": "The role requires it.", "how_to_close": "Build a SQL project."}
    ],
    "nice_to_have_gaps": [
        {"gap": "Tableau", "why_it_helps": "It communicates findings.", "how_to_close": "Build a dashboard."}
    ],
    "recommended_next_steps": ["Build a small SQL project."],
}

SHIFT_DATA = {
    "role_evolution_summary": "Routine analysis is increasingly AI-assisted.",
    "task_shifts": [
        {"task": "First-pass analysis", "changing": "AI drafts it.", "meaning": "Review matters more."}
    ],
    "durable_skills": [{"task": "Judgment", "reason": "Context remains human."}],
    "adjacent_paths": [
        {"path": "Operations analytics", "relevance": "Uses current skills.", "driver": "Automation adoption."}
    ],
    "ai_fluency_guidance": ["Explain how you verify AI output."],
}


def canonical_profile():
    # The typed runner retains this canonical object but never serializes it
    # into traces. Profile construction/confirmation filtering is tested in
    # test_student_intelligence_profile.py.
    return StudentIntelligenceProfile.model_construct()


def legacy_profile(role="Business Analyst Intern"):
    return {
        "student": {
            "id": "student-1",
            "major_current": "Business",
            "major_intended": "Business Analytics",
            "classification": "Junior",
            "expected_graduation": "Spring 2028",
        },
        "career": {
            "target_roles": [role],
            "interests": ["analytics"],
            "skills_self_reported": {"technical": ["Python"], "soft": ["communication"]},
            "work_experience": [{"role": "Intern"}],
            "projects": [],
            "certifications": [],
        },
        "courses": [{"course_code": "STAT 211", "source": "transcript_parse"}],
    }


def response(data, summary="done"):
    return json.dumps({"summary": summary, "data": data})


class QueueClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return AIResponse(
            text=outcome,
            raw={"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 10}},
            model="resolved/model",
        )


def runtime_factory(client):
    return AIRuntime(client, sleep=lambda _: None)


@pytest.mark.parametrize(
    ("model", "valid"),
    [(GapOutput, GAP_DATA), (ShiftOutput, SHIFT_DATA)],
)
def test_real_shaped_contracts_are_valid(model, valid):
    assert model.model_validate(valid)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.pop("readiness_score"),
        lambda d: d["must_have_gaps"][0].pop("how_to_close"),
        lambda d: d.update(must_have_gaps={}),
        lambda d: d.update(readiness_score=11),
        lambda d: d.update(readiness_score="6"),
        lambda d: d["nice_to_have_gaps"][0].update(unknown="value"),
    ],
)
def test_gap_contract_rejects_missing_nested_wrong_type_range_and_extra(mutation):
    data = json.loads(json.dumps(GAP_DATA))
    mutation(data)
    with pytest.raises(ValidationError):
        GapOutput.model_validate(data)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.pop("role_evolution_summary"),
        lambda d: d["task_shifts"][0].pop("meaning"),
        lambda d: d.update(durable_skills=["judgment"]),
        lambda d: d.update(adjacent_paths={}),
        lambda d: d["ai_fluency_guidance"].append({"label": "missing text"}),
    ],
)
def test_shift_contract_rejects_missing_nested_and_malformed_structures(mutation):
    data = json.loads(json.dumps(SHIFT_DATA))
    mutation(data)
    with pytest.raises(ValidationError):
        ShiftOutput.model_validate(data)


def test_every_current_demo_gap_and_shift_cache_passes_shared_contract():
    cache_dir = Path(__file__).resolve().parents[1] / "data" / "demo_cache"
    for path in cache_dir.glob("analysis_*.json"):
        results = json.loads(path.read_text(encoding="utf-8"))["results"]
        for feature in ("GAP", "SHIFT"):
            assert feature_output_is_valid(feature, results[feature]["data"]), path
            assert api._valid_cached_feature_result(feature, results[feature]), path


@pytest.mark.parametrize(
    ("runner_class", "data", "prompt_name"),
    [(GapRunner, GAP_DATA, "gap"), (ShiftRunner, SHIFT_DATA, "shift")],
)
def test_authenticated_typed_runner_first_success_has_one_call_and_trace(
    runner_class, data, prompt_name, monkeypatch
):
    if runner_class is ShiftRunner:
        monkeypatch.setattr(shift_module, "get_shift_signals", lambda roles: {"by_role": {}})
        monkeypatch.setattr(shift_module.role_research_agent, "get_role_trends", lambda role: None)
    client = QueueClient([response(data)])
    runner = runner_class(client=client, runtime_factory=runtime_factory)
    result = runner.run_canonical(canonical_profile(), legacy_profile())
    assert result["status"] == "success"
    assert len(client.calls) == 1
    assert runner.last_trace["request_id"]
    assert runner.last_trace["prompt_name"] == prompt_name
    assert runner.last_trace["prompt_version"] == "1.0"
    assert runner.last_trace["resolved_model"] == "resolved/model"
    assert runner.last_trace["attempt_count"] == 1
    assert runner.last_trace["repair_count"] == 0
    assert runner.last_trace["validation_status"] == "success"


@pytest.mark.parametrize(
    ("runner_class", "data"),
    [(GapRunner, GAP_DATA), (ShiftRunner, SHIFT_DATA)],
)
def test_transient_retry_reuses_prebuilt_grounding(runner_class, data, monkeypatch):
    builds = 0
    original = runner_class.build_student_context

    def counted(self, profile):
        nonlocal builds
        builds += 1
        return original(self, profile)

    monkeypatch.setattr(runner_class, "build_student_context", counted)
    if runner_class is ShiftRunner:
        monkeypatch.setattr(shift_module, "get_shift_signals", lambda roles: {"by_role": {}})
        monkeypatch.setattr(shift_module.role_research_agent, "get_role_trends", lambda role: None)
    client = QueueClient([AIRequestError("timeout", transient=True), response(data)])
    runner = runner_class(client=client, runtime_factory=runtime_factory)
    result = runner.run_canonical(canonical_profile(), legacy_profile())
    assert result["status"] == "success"
    assert len(client.calls) == 2
    assert builds == 1


@pytest.mark.parametrize(
    ("runner_class", "data"),
    [(GapRunner, GAP_DATA), (ShiftRunner, SHIFT_DATA)],
)
def test_structured_repair_reuses_prebuilt_grounding(runner_class, data, monkeypatch):
    builds = 0
    original = runner_class.build_student_context

    def counted(self, profile):
        nonlocal builds
        builds += 1
        return original(self, profile)

    monkeypatch.setattr(runner_class, "build_student_context", counted)
    if runner_class is ShiftRunner:
        monkeypatch.setattr(shift_module, "get_shift_signals", lambda roles: {"by_role": {}})
        monkeypatch.setattr(shift_module.role_research_agent, "get_role_trends", lambda role: None)
    client = QueueClient(["{bad-json", response(data, "repaired")])
    runner = runner_class(client=client, runtime_factory=runtime_factory)
    result = runner.run_canonical(canonical_profile(), legacy_profile())
    assert result["status"] == "success"
    assert result["summary"] == "repaired"
    assert len(client.calls) == 2
    assert builds == 1
    assert runner.last_trace["repair_count"] == 1


def test_gap_onet_and_neighbor_paths_do_not_research(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: calls.append(role),
    )
    runner = GapRunner(client=QueueClient([]))
    market = {
        "by_role": {
            "Business Analyst Intern": {"provenance": "onet"},
            "Finance Intern": {"provenance": "onet_neighbor"},
        }
    }
    runner.role_requirements_for(["Business Analyst Intern", "Finance Intern"], market)
    assert calls == []


def test_gap_research_fallback_runs_once_and_trace_records_it(monkeypatch):
    research_calls = []
    monkeypatch.setattr(
        gap_module,
        "get_market_requirements",
        lambda roles: {"by_role": {"Operations Intern": {"provenance": "none"}}},
    )
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: research_calls.append(role) or {
            "must_have_skills": ["Planning"],
            "nice_to_have_skills": [],
            "must_have_certifications": [],
            "nice_to_have_certifications": [],
        },
    )
    client = QueueClient(["bad", response(GAP_DATA)])
    runner = GapRunner(client=client, runtime_factory=runtime_factory)
    result = runner.run_canonical(canonical_profile(), legacy_profile("Operations Intern"))
    assert result["status"] == "success"
    assert research_calls == ["Operations Intern"]
    metadata = runner.last_trace["grounding_metadata"]["attributes"]
    assert metadata["research_used"] is True
    assert metadata["role_resolution_sources"] == {"agent": 1}


def test_shift_failed_research_degrades_and_is_not_repeated_on_repair(monkeypatch):
    trend_calls = []
    monkeypatch.setattr(shift_module, "get_shift_signals", lambda roles: {"by_role": {}})
    monkeypatch.setattr(
        shift_module.role_research_agent,
        "get_role_trends",
        lambda role: trend_calls.append(role) or None,
    )
    client = QueueClient(["bad", response(SHIFT_DATA)])
    runner = ShiftRunner(client=client, runtime_factory=runtime_factory)
    result = runner.run_canonical(canonical_profile(), legacy_profile())
    assert result["status"] == "success"
    assert trend_calls == ["Business Analyst Intern"]
    metadata = runner.last_trace["grounding_metadata"]["attributes"]
    assert metadata == {
        "trend_research_used": False,
        "successful_search_count": 0,
        "unresearched_role_count": 1,
    }


def test_shift_successful_research_trace_is_safe_and_counted(monkeypatch):
    monkeypatch.setattr(shift_module, "get_shift_signals", lambda roles: {"by_role": {}})
    monkeypatch.setattr(
        shift_module.role_research_agent,
        "get_role_trends",
        lambda role: {
            "role_evolution": "external summary must not enter trace",
            "task_shifts": [],
            "emerging_skills": [],
            "sources": ["https://example.invalid/source"],
        },
    )
    runner = ShiftRunner(
        client=QueueClient([response(SHIFT_DATA)]), runtime_factory=runtime_factory
    )
    assert runner.run_canonical(canonical_profile(), legacy_profile())["status"] == "success"
    serialized = json.dumps(runner.last_trace)
    assert runner.last_trace["grounding_metadata"]["attributes"]["trend_research_used"] is True
    assert runner.last_trace["grounding_metadata"]["attributes"]["successful_search_count"] == 1
    assert "external summary" not in serialized
    assert "example.invalid" not in serialized


@pytest.mark.parametrize("runner_class", [GapRunner, ShiftRunner])
def test_non_transient_failure_does_not_retry_and_failed_repair_stops(runner_class, monkeypatch):
    if runner_class is ShiftRunner:
        monkeypatch.setattr(shift_module, "get_shift_signals", lambda roles: {"by_role": {}})
        monkeypatch.setattr(shift_module.role_research_agent, "get_role_trends", lambda role: None)
    client = QueueClient([AIRequestError("bad request")])
    runner = runner_class(client=client, runtime_factory=runtime_factory)
    assert runner.run_canonical(canonical_profile(), legacy_profile())["status"] == "failed"
    assert len(client.calls) == 1

    client = QueueClient(["bad", "still bad"])
    runner = runner_class(client=client, runtime_factory=runtime_factory)
    assert runner.run_canonical(canonical_profile(), legacy_profile())["status"] == "failed"
    assert len(client.calls) == 2


@pytest.mark.parametrize("runner_class", [GapRunner, ShiftRunner])
def test_transient_retry_budget_is_three_total_attempts(runner_class, monkeypatch):
    if runner_class is ShiftRunner:
        monkeypatch.setattr(shift_module, "get_shift_signals", lambda roles: {"by_role": {}})
        monkeypatch.setattr(shift_module.role_research_agent, "get_role_trends", lambda role: None)
    client = QueueClient([AIRequestError("busy", transient=True)] * 3)
    runner = runner_class(client=client, runtime_factory=runtime_factory)
    assert runner.run_canonical(canonical_profile(), legacy_profile())["status"] == "failed"
    assert len(client.calls) == 3
