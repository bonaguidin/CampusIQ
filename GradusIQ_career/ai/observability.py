"""Versioned, structurally safe AI invocation observability contracts."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Protocol


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    provider_usage_available: bool = False
    estimated_cost: float | None = None


@dataclass
class AIExecutionTrace:
    request_id: str
    feature: str
    prompt_name: str
    prompt_version: str
    model_role: str
    started_at: str
    trace_version: Literal["1.0"] = "1.0"
    resolved_model: str | None = None
    attempt_count: int = 0
    repair_count: int = 0
    latency_ms: int = 0
    usage: AIUsage = field(default_factory=AIUsage)
    parse_status: str = "not_started"
    validation_status: str = "not_started"
    final_status: str = "failed"
    error_class: str | None = None
    grounding_metadata: Mapping[str, Any] | None = None

    @property
    def provider_usage(self) -> Mapping[str, Any] | None:
        """Compatibility view retained for Phase A callers."""
        if not self.usage.provider_usage_available:
            return None
        return {
            key: value
            for key, value in {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "total_tokens": self.usage.total_tokens,
            }.items()
            if value is not None
        }

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["provider_usage"] = self.provider_usage
        return value


class TraceSink(Protocol):
    def record(self, trace: AIExecutionTrace) -> None: ...


class NoopTraceSink:
    def record(self, trace: AIExecutionTrace) -> None:
        return None


class InMemoryTraceSink:
    def __init__(self) -> None:
        self.traces: list[AIExecutionTrace] = []

    def record(self, trace: AIExecutionTrace) -> None:
        self.traces.append(trace)


def normalize_usage(raw: Mapping[str, Any] | None) -> AIUsage:
    if not isinstance(raw, Mapping):
        return AIUsage()

    def token(*names: str) -> int | None:
        for name in names:
            value = raw.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        return None

    input_tokens = token("prompt_tokens", "input_tokens")
    output_tokens = token("completion_tokens", "output_tokens")
    total_tokens = token("total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    available = any(value is not None for value in (input_tokens, output_tokens, total_tokens))
    return AIUsage(input_tokens, output_tokens, total_tokens, available, None)


def add_usage(left: AIUsage, right: AIUsage) -> AIUsage:
    def add(a: int | None, b: int | None) -> int | None:
        values = [value for value in (a, b) if value is not None]
        return sum(values) if values else None

    return AIUsage(
        input_tokens=add(left.input_tokens, right.input_tokens),
        output_tokens=add(left.output_tokens, right.output_tokens),
        total_tokens=add(left.total_tokens, right.total_tokens),
        provider_usage_available=left.provider_usage_available or right.provider_usage_available,
        estimated_cost=None,
    )
