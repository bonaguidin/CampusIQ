import json

import pytest

from GradusIQ_career.ai.context import AgentContext, GroundingMetadata
from GradusIQ_career.ai.contracts import ChatOutput, FitOutput
from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.ai.types import AIResponse
from GradusIQ_career.evals.live import _review_convenience
from GradusIQ_career.evals.models import EvalFeature
from GradusIQ_career.evals.run import main
from GradusIQ_career.evals.runner import run_scenarios
from GradusIQ_career.evals.scenarios import SCENARIOS
from GradusIQ_career.features import role_research_agent as research
from tests.test_ai_runtime_chat import canonical_profile


REAL_GET_ROLE_REQUIREMENTS = research.get_role_requirements
REAL_GET_ROLE_TRENDS = research.get_role_trends


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        self.value += 0.001
        return self.value


class Client:
    def __init__(self, text):
        self.text = text

    def complete(self, **kwargs):
        return AIResponse(
            text=self.text,
            model="controlled/model",
            raw={"usage": {"prompt_tokens": 3, "completion_tokens": 2}},
        )


def context(feature="FIT"):
    return AgentContext(
        feature=feature,
        canonical_profile=canonical_profile(),
        model_role="chat" if feature == "chat" else "career",
        prompt_name=feature.lower(),
        prompt_version="1.0",
        grounding=GroundingMetadata(source_types=("synthetic_eval",)),
    )


def test_provider_parse_validation_timings_are_safe_and_coherent():
    clock = Clock()
    payload = '{"data":{"role_matches":[{"role":"Analyst","fit_level":"high","rationale":"SQL","supporting_signals":["SQL"],"missing_signals":[]}],"overall_fit_summary":"Strong"}}'
    result = AIRuntime(Client(payload), monotonic=clock).invoke(
        context=context(), messages=[], output_model=FitOutput
    )
    trace = result.trace.to_dict()
    assert trace["provider_ms_total"] == sum(trace["provider_attempt_ms"])
    assert trace["provider_ms_total"] >= 0
    assert trace["parse_ms"] >= 0 and trace["validation_ms"] >= 0
    assert trace["latency_ms"] >= trace["provider_ms_total"]

    chat = AIRuntime(Client("Advice"), monotonic=Clock()).invoke_text(
        context=context("chat"), messages=[], output_model=ChatOutput
    )
    assert chat.trace.validation_ms >= 0
    assert chat.trace.parse_ms == 0


def test_fixture_review_records_retain_validated_outputs_without_provider_envelope():
    records = run_scenarios(SCENARIOS)
    by_feature = {record.feature: record for record in records}
    assert isinstance(by_feature[EvalFeature.FIT].reviewable_output, dict)
    assert isinstance(by_feature[EvalFeature.GAP].reviewable_output, dict)
    assert isinstance(by_feature[EvalFeature.SHIFT].reviewable_output, dict)
    assert isinstance(by_feature[EvalFeature.CHAT].reviewable_output, str)
    rendered = json.dumps([record.model_dump(mode="json") for record in records])
    for forbidden in (
        "raw_provider_response", "choices", "Authorization", "api_key",
        "synthetic-eval-student", "chat_history", "prompt_text",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize("feature", [
    EvalFeature.FIT, EvalFeature.GAP, EvalFeature.SHIFT, EvalFeature.CHAT
])
def test_every_feature_review_record_has_stage_timing_and_safe_summaries(feature):
    scenario = next(item for item in SCENARIOS if feature in item.features)
    observation = dict(scenario.fixture_results[feature])
    observation.update({
        "stage_timing": {
            "context_ms": 1, "grounding_ms": 2, "research_ms": 3,
            "provider_ms": 4, "parse_ms": 5, "validation_ms": 6, "total_ms": 21,
        },
        "safe_grounding_summary": {
            "source_categories": ["synthetic_eval"], "canonical_profile_used": True,
        },
        "research_summary": {"research_used": feature in {EvalFeature.GAP, EvalFeature.SHIFT}},
    })
    record = run_scenarios(
        [scenario], live=True, live_executor=lambda *_: observation
    )[0]
    assert record.stage_timing.total_ms == 21
    assert record.stage_timing.provider_ms == 4
    assert record.safe_grounding_summary.canonical_profile_used is True
    assert record.research_summary.research_used is (feature in {EvalFeature.GAP, EvalFeature.SHIFT})


def test_gap_review_convenience_extracts_courses_and_certifications():
    output = {
        "recommended_next_steps": [
            "Take CS 301 next term.",
            "Consider the AWS Cloud Practitioner certification.",
        ]
    }
    review = _review_convenience(EvalFeature.GAP, output)
    assert review["course_recommendations"] == ["Take CS 301 next term."]
    assert review["certification_recommendations"] == [
        "Consider the AWS Cloud Practitioner certification."
    ]


def test_research_accounting_cache_hit(monkeypatch):
    cached = {
        "soc_code": "15-1252.00", "soc_title": "Software Developers",
        "must_have_skills": [], "nice_to_have_skills": [],
        "must_have_certifications": [], "nice_to_have_certifications": [],
    }
    monkeypatch.setattr(research, "_read_cache", lambda *args: cached)
    with research.capture_research_accounting() as accounting:
        assert REAL_GET_ROLE_REQUIREMENTS("Synthetic Role") is not None
    assert accounting.research_used is True
    assert accounting.cache_hit is True
    assert accounting.cache_miss is False
    assert accounting.research_status == "cache_hit"


def test_research_accounting_miss_turns_tools_searches_and_sources(monkeypatch):
    monkeypatch.setattr(research, "_read_cache", lambda *args: None)
    monkeypatch.setattr(research, "_write_cache", lambda *args: None)
    monkeypatch.setattr(research, "_execute_tool_call", lambda *args: '{"results":[{"title":"source"}]}')

    class ResearchClient:
        def __init__(self):
            self.calls = 0

        def complete_message(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"content": "", "tool_calls": [{"id": "1", "function": {"name": "web_search", "arguments": "{}"}}]}
            return {"content": json.dumps({
                "role_evolution": "Changing", "task_shifts": [],
                "emerging_skills": [], "sources": ["review-source"],
            })}

    monkeypatch.setattr(research, "_has_search_capability", lambda: True)
    with research.capture_research_accounting() as accounting:
        assert REAL_GET_ROLE_TRENDS("Synthetic Role", client=ResearchClient()) is not None
    assert accounting.research_used is True and accounting.cache_miss is True
    assert accounting.research_model_turn_count == 2
    assert accounting.tool_call_count == 1
    assert accounting.successful_search_count == 1
    assert accounting.source_count == 1
    assert accounting.research_status == "success"


def test_incremental_atomic_artifact_preserves_two_results_on_interruption(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRADUSIQ_EVAL_LIVE", "1")
    calls = 0

    def execute(scenario, feature):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt
        return scenario.fixture_results[feature]

    monkeypatch.setattr("GradusIQ_career.evals.live.execute_live", execute)
    output = tmp_path / "eval-results" / "interrupted.json"
    with pytest.raises(KeyboardInterrupt):
        main(["--live", "--output", str(output)])
    artifact = json.loads(output.read_text())
    assert artifact["run_status"] == "incomplete"
    assert artifact["planned"] == 12
    assert artifact["completed"] == 2
    assert len(artifact["results"]) == 2
    assert not list(output.parent.glob(f".{output.name}.*"))
