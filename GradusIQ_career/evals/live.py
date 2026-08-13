"""Explicitly opted-in adapter from synthetic scenarios to production feature paths."""

from functools import lru_cache

from GradusIQ_career.ai.context import AgentContext, GroundingMetadata
from GradusIQ_career.ai.contracts import ChatOutput
from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.api import ChatRequest, build_canonical_chat_messages, build_client
from GradusIQ_career.features.orchestrator import RUNNERS
from GradusIQ_career.profile_builder import canonical_to_legacy_profile
from GradusIQ_career.student_intelligence_profile import StudentIntelligenceProfile

from .models import EvalFeature, EvalScenario


@lru_cache(maxsize=1)
def synthetic_profile() -> StudentIntelligenceProfile:
    return StudentIntelligenceProfile.model_validate({
        "identity": {"student_id": "eval-student", "name": "Synthetic Student", "classification": "Junior", "expected_graduation": "Spring 2028"},
        "institution": {"name": "Synthetic University"},
        "academics": {
            "summary": {"major_current": "Statistics", "major_intended": "Data Science", "confirmed_course_count": 1},
            "courses": [{"id": "eval-course", "course_code": "STAT 301", "title": "Statistics", "credit_hours": 3, "letter_grade": "A", "credit_type": "resident", "status": "completed", "source": "synthetic_eval"}],
            "gpa": {"official": 4.0, "projected": 4.0, "computable": True},
        },
        "career": {
            "confirmed": True, "target_roles": ["Data Analyst"], "interests": ["analytics"],
            "ai_anxiety_level": "moderate", "skills": {"technical": ["SQL", "Python"], "soft": ["communication"]},
            "work_experience": [{"role": "Synthetic Analytics Intern"}],
        },
        "completeness": {
            "career": {"confirmed_profile": True, "target_role_present": True, "skills_present": True, "certifications_present": False, "work_experience_present": True, "projects_present": False, "ready_for_career_features": True},
            "academics": {"transcript_data_present": True, "terms_present": False, "gpa_computable": True, "ready_for_academic_features": False},
            "overall": "partial",
        },
        "provenance": {},
    })


def execute_live(scenario: EvalScenario, feature: EvalFeature) -> dict:
    """Perform one bounded product-path invocation using synthetic data only."""
    canonical = synthetic_profile()
    if feature == EvalFeature.CHAT:
        body = ChatRequest(message=scenario.purpose, history=[])
        context = AgentContext(
            feature="chat", canonical_profile=canonical, model_role="chat",
            prompt_name="chat", prompt_version="1.0",
            grounding=GroundingMetadata(source_types=("synthetic_eval",), attributes={"history_message_count": 0}),
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
