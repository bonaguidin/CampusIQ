"""Bounded structured AI invocation built on the existing OpenRouter client."""

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Generic, Mapping, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

from .context import AgentContext
from .errors import AIConfigError, AIRequestError, AIResponseParseError
from .observability import AIExecutionTrace, NoopTraceSink, TraceSink, add_usage, normalize_usage
from .parser import parse_ai_json_response


OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass
class AIRuntimeResult(Generic[OutputT]):
    output: OutputT | None
    summary: str | None
    trace: AIExecutionTrace
    errors: list[str]


class AIRuntime:
    """Invoke, parse and validate one structured call with bounded recovery."""

    def __init__(
        self,
        client: Any,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        backoff_seconds: Sequence[float] = (0.25, 0.75),
        trace_sink: TraceSink | None = None,
    ) -> None:
        self.client = client
        self.sleep = sleep
        self.monotonic = monotonic
        self.backoff_seconds = tuple(backoff_seconds)
        self.trace_sink = trace_sink or NoopTraceSink()

    def _new_trace(self, context: AgentContext) -> AIExecutionTrace:
        return AIExecutionTrace(
            request_id=context.request_id,
            feature=context.feature,
            prompt_name=context.prompt_name,
            prompt_version=context.prompt_version,
            model_role=context.model_role,
            started_at=context.created_at.isoformat(),
            grounding_metadata={
                "source_types": list(context.grounding.source_types),
                "trust_level": context.grounding.trust_level,
                "attributes": dict(context.grounding.attributes),
            },
        )

    def _capture_usage(self, trace: AIExecutionTrace, response: Any) -> None:
        raw = response.raw.get("usage") if isinstance(response.raw, Mapping) else None
        trace.usage = add_usage(trace.usage, normalize_usage(raw))

    def _emit(self, trace: AIExecutionTrace) -> None:
        try:
            self.trace_sink.record(trace)
        except Exception:
            pass

    @staticmethod
    def _validation_problems(exc: ValidationError) -> list[dict[str, Any]]:
        return [
            {"path": ".".join(str(part) for part in item["loc"]), "type": item["type"], "message": item["msg"]}
            for item in exc.errors(include_url=False, include_context=False, include_input=False)
        ]

    def _complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        context: AgentContext,
        trace: AIExecutionTrace,
        retry_state: list[int],
    ):
        while True:
            trace.attempt_count += 1
            try:
                return self.client.complete(messages=messages, role=context.model_role)
            except AIRequestError as exc:
                if not getattr(exc, "transient", False) or retry_state[0] >= len(self.backoff_seconds):
                    raise
                self.sleep(self.backoff_seconds[retry_state[0]])
                retry_state[0] += 1

    def invoke(
        self,
        *,
        context: AgentContext,
        messages: Sequence[Mapping[str, Any]],
        output_model: type[OutputT],
    ) -> AIRuntimeResult[OutputT]:
        trace = self._new_trace(context)
        started = self.monotonic()
        current_messages = list(messages)
        retry_state = [0]
        last_error = "Structured AI response failed."

        try:
            for repair_index in range(2):
                response = self._complete(current_messages, context, trace, retry_state)
                trace.resolved_model = response.model
                self._capture_usage(trace, response)
                try:
                    parsed = parse_ai_json_response(response.text)
                    trace.parse_status = "success"
                    data = parsed.get("data", parsed)
                    validated = output_model.model_validate(data)
                    trace.validation_status = "success"
                    trace.final_status = "success"
                    summary = parsed.get("summary")
                    result = AIRuntimeResult(
                        output=validated,
                        summary=summary if isinstance(summary, str) else None,
                        trace=trace,
                        errors=[],
                    )
                    trace.latency_ms = max(0, round((self.monotonic() - started) * 1000))
                    self._emit(trace)
                    return result
                except AIResponseParseError as exc:
                    trace.parse_status = "failed"
                    trace.validation_status = "not_started"
                    problems: Any = [{"type": "json_parse", "message": str(exc)}]
                    last_error = "AI response was not valid JSON."
                    trace.error_class = "parse_error"
                except ValidationError as exc:
                    trace.validation_status = "failed"
                    problems = self._validation_problems(exc)
                    last_error = f"AI response did not match the {context.feature} output contract."
                    trace.error_class = "validation_error"

                if repair_index == 1:
                    break
                trace.repair_count = 1
                current_messages = [
                    *messages,
                    {"role": "assistant", "content": response.text},
                    {
                        "role": "user",
                        "content": (
                            "Return only corrected JSON matching the original contract. "
                            "Do not add commentary. Validation problems: "
                            + json.dumps(problems, separators=(",", ":"))
                        ),
                    },
                ]
        except AIConfigError:
            trace.error_class = "configuration_error"
            last_error = "AI service configuration is unavailable."
        except AIRequestError as exc:
            trace.error_class = "transient_provider_error" if getattr(exc, "transient", False) else "provider_error"
            last_error = "AI provider request failed."
        except AIResponseParseError:
            trace.parse_status = "failed"
            trace.validation_status = "not_started"
            trace.error_class = "parse_error"
            last_error = "AI provider response did not contain valid content."
        finally:
            trace.latency_ms = max(0, round((self.monotonic() - started) * 1000))

        result = AIRuntimeResult(output=None, summary=None, trace=trace, errors=[last_error])
        self._emit(trace)
        return result

    def invoke_text(
        self,
        *,
        context: AgentContext,
        messages: Sequence[Mapping[str, Any]],
        output_model: type[OutputT],
    ) -> AIRuntimeResult[OutputT]:
        """Invoke and validate natural-language output without JSON repair."""
        trace = self._new_trace(context)
        started = self.monotonic()
        retry_state = [0]
        last_error = "AI response did not contain valid text."

        try:
            response = self._complete(messages, context, trace, retry_state)
            trace.resolved_model = response.model
            self._capture_usage(trace, response)
            validated = output_model.model_validate({"content": response.text})
            if not validated.content.strip():
                raise ValueError("Chat response must not be blank.")
            trace.parse_status = "not_applicable"
            trace.validation_status = "success"
            trace.final_status = "success"
            result = AIRuntimeResult(output=validated, summary=None, trace=trace, errors=[])
            trace.latency_ms = max(0, round((self.monotonic() - started) * 1000))
            self._emit(trace)
            return result
        except ValidationError:
            trace.parse_status = "not_applicable"
            trace.validation_status = "failed"
            trace.error_class = "validation_error"
        except ValueError:
            trace.parse_status = "not_applicable"
            trace.validation_status = "failed"
            trace.error_class = "validation_error"
        except AIResponseParseError:
            trace.parse_status = "failed"
            trace.validation_status = "not_started"
            trace.error_class = "parse_error"
        except AIConfigError:
            trace.error_class = "configuration_error"
            last_error = "AI service configuration is unavailable."
        except AIRequestError as exc:
            trace.error_class = "transient_provider_error" if getattr(exc, "transient", False) else "provider_error"
            last_error = "AI provider request failed."
        finally:
            trace.latency_ms = max(0, round((self.monotonic() - started) * 1000))

        result = AIRuntimeResult(output=None, summary=None, trace=trace, errors=[last_error])
        self._emit(trace)
        return result
