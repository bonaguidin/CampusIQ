"""Explicitly opted-in adapter from synthetic scenarios to production feature paths."""

from GradusIQ_career.ai.context import AgentContext, GroundingMetadata
from GradusIQ_career.ai.contracts import ChatOutput
from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.api import ChatRequest, build_canonical_chat_messages, build_client
from GradusIQ_career.features.orchestrator import RUNNERS
from GradusIQ_career.profile_builder import canonical_to_legacy_profile
from .models import EvalFeature, EvalScenario
from .profiles import build_synthetic_canonical_profile


def execute_live(scenario: EvalScenario, feature: EvalFeature) -> dict:
    """Perform one bounded product-path invocation using synthetic data only."""
    if not scenario.live_eligible or feature not in scenario.features:
        raise ValueError("Scenario is not eligible for this live feature.")
    canonical = build_synthetic_canonical_profile(scenario.synthetic_input)
    if feature == EvalFeature.CHAT:
        body = ChatRequest(
            message=scenario.synthetic_input.chat_question or scenario.purpose,
            history=[turn.model_dump() for turn in scenario.synthetic_input.chat_history],
        )
        context = AgentContext(
            feature="chat", canonical_profile=canonical, model_role="chat",
            prompt_name="chat", prompt_version="1.0",
            grounding=GroundingMetadata(
                source_types=("synthetic_eval",),
                attributes={"history_message_count": len(body.history)},
            ),
        )
        result = AIRuntime(build_client()).invoke_text(
            context=context, messages=build_canonical_chat_messages(canonical, body), output_model=ChatOutput
        )
        trace = result.trace
        return {
            "status": "success" if result.output else "failed",
            "text": result.output.content if result.output else "",
            "model": trace.resolved_model, "latency_ms": trace.latency_ms,
            "attempt_count": trace.attempt_count, "repair_count": trace.repair_count,
            "input_tokens": trace.usage.input_tokens, "output_tokens": trace.usage.output_tokens,
            "total_tokens": trace.usage.total_tokens,
        }
    runner = RUNNERS[feature.value.upper()](client=build_client())
    product = runner.run_canonical(canonical, canonical_to_legacy_profile(canonical))
    trace = runner.last_trace or {}
    usage = trace.get("usage") or {}
    return {
        "status": product.get("status"), "data": product.get("data"),
        "model": trace.get("resolved_model"), "latency_ms": trace.get("latency_ms", 0),
        "attempt_count": trace.get("attempt_count", 0), "repair_count": trace.get("repair_count", 0),
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }
