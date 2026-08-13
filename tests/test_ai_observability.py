import json

import pytest

from GradusIQ_career.ai.context import AgentContext, GroundingMetadata
from GradusIQ_career.ai.contracts import ChatOutput, FitOutput, GapOutput, ShiftOutput
from GradusIQ_career.ai.errors import AIRequestError
from GradusIQ_career.ai.observability import InMemoryTraceSink, normalize_usage
from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.ai.types import AIResponse
from tests.test_ai_runtime_chat import canonical_profile


FIT = '{"data":{"role_matches":[{"role":"Analyst","fit_level":"high","rationale":"SQL","supporting_signals":["SQL"],"missing_signals":[]}],"overall_fit_summary":"Strong"}}'
GAP = '{"data":{"readiness_score":6,"strengths":["SQL"],"must_have_gaps":[],"nice_to_have_gaps":[],"recommended_next_steps":[]}}'
SHIFT = '{"data":{"role_evolution_summary":"Changing","task_shifts":[],"durable_skills":[],"adjacent_paths":[],"ai_fluency_guidance":[]}}'


class Queue:
    def __init__(self, values):
        self.values = list(values)

    def complete(self, **kwargs):
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def response(text, prompt=2, completion=3):
    return AIResponse(
        text=text, model="controlled/model",
        raw={"usage": {"prompt_tokens": prompt, "completion_tokens": completion}},
    )


def context(feature="FIT"):
    return AgentContext(
        feature=feature, canonical_profile=canonical_profile(), model_role="career" if feature != "chat" else "chat",
        prompt_name=feature.lower(), prompt_version="1.0", request_id="stable-request-id",
        grounding=GroundingMetadata(source_types=("student_confirmed",), attributes={"safe_count": 1}),
    )


def test_one_trace_on_success_with_versioned_normalized_usage():
    sink = InMemoryTraceSink()
    result = AIRuntime(Queue([response(FIT)]), trace_sink=sink).invoke(
        context=context(), messages=[], output_model=FitOutput
    )
    assert result.output is not None
    assert len(sink.traces) == 1
    trace = sink.traces[0]
    assert trace.trace_version == "1.0"
    assert trace.request_id == "stable-request-id"
    assert trace.started_at
    assert trace.usage.input_tokens == 2
    assert trace.usage.output_tokens == 3
    assert trace.usage.total_tokens == 5
    assert trace.usage.provider_usage_available is True
    assert trace.usage.estimated_cost is None


@pytest.mark.parametrize(
    "feature, payload, output_model",
    [("FIT", FIT, FitOutput), ("GAP", GAP, GapOutput), ("SHIFT", SHIFT, ShiftOutput)],
)
def test_structured_features_share_observability_contract(feature, payload, output_model):
    sink = InMemoryTraceSink()
    result = AIRuntime(Queue([response(payload)]), trace_sink=sink).invoke(
        context=context(feature), messages=[], output_model=output_model
    )
    assert result.output is not None
    assert len(sink.traces) == 1
    assert sink.traces[0].feature == feature


def test_chat_shares_observability_contract():
    sink = InMemoryTraceSink()
    result = AIRuntime(Queue([response("Advice")]), trace_sink=sink).invoke_text(
        context=context("chat"), messages=[], output_model=ChatOutput
    )
    assert result.output.content == "Advice"
    assert len(sink.traces) == 1
    assert sink.traces[0].feature == "chat"


def test_retry_and_repair_emit_once_and_aggregate_usage():
    sink = InMemoryTraceSink()
    queue = Queue([
        AIRequestError("timeout", transient=True),
        response("not json", 2, 1),
        response(FIT, 4, 3),
    ])
    result = AIRuntime(queue, sleep=lambda _: None, trace_sink=sink).invoke(
        context=context(), messages=[], output_model=FitOutput
    )
    assert result.output is not None
    assert len(sink.traces) == 1
    trace = sink.traces[0]
    assert trace.attempt_count == 3
    assert trace.repair_count == 1
    assert (trace.usage.input_tokens, trace.usage.output_tokens, trace.usage.total_tokens) == (6, 4, 10)


@pytest.mark.parametrize(
    "values, output_model, method",
    [
        ([AIRequestError("bad", transient=False)], FitOutput, "invoke"),
        ([response("   ")], ChatOutput, "invoke_text"),
        ([response("{}"), response("{}")], FitOutput, "invoke"),
    ],
)
def test_failure_and_validation_paths_emit_exactly_once(values, output_model, method):
    sink = InMemoryTraceSink()
    runtime = AIRuntime(Queue(values), sleep=lambda _: None, trace_sink=sink)
    result = getattr(runtime, method)(context=context("chat" if method == "invoke_text" else "FIT"), messages=[], output_model=output_model)
    assert result.output is None
    assert len(sink.traces) == 1
    assert sink.traces[0].request_id == "stable-request-id"


def test_absent_or_variant_usage_is_safe():
    assert normalize_usage(None).provider_usage_available is False
    usage = normalize_usage({"input_tokens": 7, "output_tokens": 2})
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (7, 2, 9)


def test_trace_serialization_structurally_excludes_sensitive_payloads():
    sink = InMemoryTraceSink()
    AIRuntime(Queue([response("answer")]), trace_sink=sink).invoke_text(
        context=context("chat"), messages=[{"role": "user", "content": "SECRET HISTORY"}], output_model=ChatOutput
    )
    rendered = json.dumps(sink.traces[0].to_dict())
    for forbidden in ("SECRET HISTORY", "private-student-id", "STUDENT_PROFILE_DATA", "Authorization", "api_key"):
        assert forbidden not in rendered


def test_sink_failure_never_changes_product_result():
    class BrokenSink:
        def record(self, trace):
            raise RuntimeError("sink down")

    result = AIRuntime(Queue([response("answer")]), trace_sink=BrokenSink()).invoke_text(
        context=context("chat"), messages=[], output_model=ChatOutput
    )
    assert result.output.content == "answer"
