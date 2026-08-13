"""Explicit, synthetic-only adapter producing reviewable ignored artifacts."""

import re
import time
from typing import Any, Callable, Mapping

from GradusIQ_career.ai.context import AgentContext, GroundingMetadata
from GradusIQ_career.ai.contracts import ChatOutput
from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.api import ChatRequest, build_canonical_chat_messages, build_client
from GradusIQ_career.features import role_research_agent
from GradusIQ_career.features.orchestrator import RUNNERS
from GradusIQ_career.profile_builder import canonical_to_legacy_profile

from .models import EvalFeature, EvalScenario
from .profiles import build_synthetic_canonical_profile


_COURSE_CODE = re.compile(r"\b[A-Z]{2,5}\s?\d{3,4}\b")


def _elapsed_ms(monotonic: Callable[[], float], started: float) -> int:
    return max(0, round((monotonic() - started) * 1000))


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _review_convenience(feature: EvalFeature, output: Any) -> dict[str, list[str]]:
    if feature != EvalFeature.GAP:
        return {"course_recommendations": [], "certification_recommendations": []}
    values = list(_strings(output))
    courses = [value for value in values if "course" in value.lower() or _COURSE_CODE.search(value)]
    certifications = [
        value for value in values if "certification" in value.lower() or "certificate" in value.lower()
    ]
    return {
        "course_recommendations": list(dict.fromkeys(courses)),
        "certification_recommendations": list(dict.fromkeys(certifications)),
    }


def _safe_grounding(
    scenario: EvalScenario, feature: EvalFeature, trace: Mapping[str, Any], research: Mapping[str, Any]
) -> dict[str, Any]:
    grounding = trace.get("grounding_metadata") or {}
    attributes = grounding.get("attributes") or {}
    categories = list(grounding.get("source_types") or [])
    source_count = int(research.get("source_count") or 0)
    return {
        "source_categories": categories,
        "grounded_target_roles": list(scenario.synthetic_input.target_roles),
        "onet_evidence_present": "onet_static" in categories,
        "employer_posting_evidence_supplied": False,
        "role_resolution_sources": dict(attributes.get("role_resolution_sources") or {}),
        "supplied_course_count": len(scenario.synthetic_input.completed_courses),
        "supplied_certification_count": len(scenario.synthetic_input.certifications),
        "canonical_profile_used": True,
        "history_count": len(scenario.synthetic_input.chat_history) if feature == EvalFeature.CHAT else 0,
        "tools_available": False,
        "persistent_memory_available": False,
        "source_status": "SOURCE_PRESENT" if source_count else "SOURCE_NOT_PRESENT",
    }


def _trace_summary(trace: Mapping[str, Any]) -> dict[str, Any]:
    usage = trace.get("usage") or {}
    return {
        "request_id": trace.get("request_id"),
        "attempt_count": trace.get("attempt_count", 0),
        "repair_count": trace.get("repair_count", 0),
        "provider_attempt_ms": list(trace.get("provider_attempt_ms") or []),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "final_status": trace.get("final_status", "failed"),
        "error_class": trace.get("error_class"),
    }


def execute_live(
    scenario: EvalScenario,
    feature: EvalFeature,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    client_factory: Callable[[], Any] = build_client,
) -> dict[str, Any]:
    """Perform one product-path invocation and retain only validated eval evidence."""
    if not scenario.live_eligible or feature not in scenario.features:
        raise ValueError("Scenario is not eligible for this live feature.")
    total_started = monotonic()
    context_started = monotonic()
    canonical = build_synthetic_canonical_profile(scenario.synthetic_input)
    legacy = canonical_to_legacy_profile(canonical)
    context_ms = _elapsed_ms(monotonic, context_started)
    grounding_ms = 0

    if feature == EvalFeature.CHAT:
        body = ChatRequest(
            message=scenario.synthetic_input.chat_question or scenario.purpose,
            history=[turn.model_dump() for turn in scenario.synthetic_input.chat_history],
        )
        context = AgentContext(
            feature="chat",
            canonical_profile=canonical,
            model_role="chat",
            prompt_name="chat",
            prompt_version="1.0",
            grounding=GroundingMetadata(
                source_types=("synthetic_eval",),
                attributes={"history_message_count": len(body.history)},
            ),
        )
        result = AIRuntime(client_factory(), monotonic=monotonic).invoke_text(
            context=context,
            messages=build_canonical_chat_messages(canonical, body),
            output_model=ChatOutput,
        )
        trace = result.trace.to_dict()
        output = result.output.content if result.output else None
        status = "success" if result.output else "failed"
        research = role_research_agent.ResearchAccounting().to_dict()
    else:
        runner = RUNNERS[feature.value.upper()](
            client=client_factory(),
            runtime_factory=lambda client: AIRuntime(client, monotonic=monotonic),
        )
        original_build = runner.build_student_context

        def timed_build(profile):
            nonlocal grounding_ms
            started = monotonic()
            value = original_build(profile)
            grounding_ms += _elapsed_ms(monotonic, started)
            return value

        runner.build_student_context = timed_build
        with role_research_agent.capture_research_accounting() as accounting:
            product = runner.run_canonical(canonical, legacy)
        trace = runner.last_trace or {}
        output = product.get("data") if product.get("status") == "success" else None
        status = product.get("status", "failed")
        research = accounting.to_dict()

    usage = trace.get("usage") or {}
    total_ms = _elapsed_ms(monotonic, total_started)
    return {
        "status": status,
        "data": output if feature != EvalFeature.CHAT else None,
        "text": output if feature == EvalFeature.CHAT else "",
        "reviewable_output": output,
        "model": trace.get("resolved_model"),
        "latency_ms": trace.get("latency_ms", total_ms),
        "attempt_count": trace.get("attempt_count", 0),
        "repair_count": trace.get("repair_count", 0),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "safe_grounding_summary": _safe_grounding(scenario, feature, trace, research),
        "research_summary": research,
        "stage_timing": {
            "context_ms": context_ms,
            "grounding_ms": grounding_ms,
            "research_ms": research.get("research_ms", 0),
            "provider_ms": trace.get("provider_ms_total", 0),
            "parse_ms": trace.get("parse_ms", 0),
            "validation_ms": trace.get("validation_ms", 0),
            "total_ms": total_ms,
        },
        "trace_summary": _trace_summary(trace),
        "review_convenience": _review_convenience(feature, output),
    }
