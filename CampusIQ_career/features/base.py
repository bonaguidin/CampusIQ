"""Shared contracts and helpers for Campus IQ feature runners."""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence

from CampusIQ_career.ai.errors import AIConfigError, AIRequestError, AIResponseParseError
from CampusIQ_career.ai.parser import parse_ai_json_response


logger = logging.getLogger(__name__)

FeatureStatus = Literal["success", "skipped", "failed"]

PROMPT_DIR = Path(__file__).resolve().parents[1]

# One re-ask on an unparseable response. Two attempts, not more: a second
# failure on the same messages points at a systematic problem (a prompt that
# invites prose, a model that can't hold the format) which retrying will not
# fix, and each attempt is a full paid call.
_PARSE_ATTEMPTS = 2


@dataclass(frozen=True)
class FeatureResult:
    feature: str
    status: FeatureStatus
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FeatureRunner(Protocol):
    feature: str

    def run(self, student_profile: Mapping[str, Any]) -> dict[str, Any]:
        ...


class CareerFeatureRunner:
    feature: str
    prompt_filename: str
    required_paths: Sequence[str]
    output_contract: Mapping[str, Any]
    role: str = "career"

    def __init__(self, client: Any, prompt_path: str | Path | None = None) -> None:
        self.client = client
        self.prompt_path = Path(prompt_path) if prompt_path else PROMPT_DIR / self.prompt_filename

    def run(self, student_profile: Mapping[str, Any]) -> dict[str, Any]:
        missing_fields = find_missing_fields(student_profile, self.required_paths)
        if missing_fields:
            return FeatureResult(
                feature=self.feature,
                status="skipped",
                summary="Missing required fields for this feature.",
                data={},
                errors=[f"Missing required field: {field_name}" for field_name in missing_fields],
            ).to_dict()

        # Built once, outside the retry loop. build_student_context is not free
        # for every runner -- GAP's may call the research agent, SHIFT's does
        # live trend research -- and a retry is for a bad *response*, not a bad
        # request. Re-deriving the context would repeat that work for nothing.
        try:
            prompt_template = load_prompt_template(self.prompt_path)
            messages = self.build_messages(student_profile, prompt_template)
        except (OSError, ValueError) as exc:
            return FeatureResult(
                feature=self.feature,
                status="failed",
                summary=f"{self.feature} analysis failed.",
                data={},
                errors=[str(exc)],
            ).to_dict()

        parsed = None
        last_parse_error: AIResponseParseError | None = None
        for attempt in range(1, _PARSE_ATTEMPTS + 1):
            try:
                response = self.client.complete(messages=messages, role=self.role)
                parsed = parse_ai_json_response(response.text)
                break
            except AIResponseParseError as exc:
                # Retried because this is a sampling accident, not a bad
                # request: an unescaped quote inside a long string, or a
                # structural slip. Observed once in 24 live runs, and it
                # succeeded on re-ask both times. Deliberately NOT retried for
                # config/request errors -- a missing key or a refused request
                # fails identically the second time, and re-sending would just
                # double the cost of an outage.
                last_parse_error = exc
                logger.warning(
                    "%s: unparseable response on attempt %d/%d: %s",
                    self.feature, attempt, _PARSE_ATTEMPTS, exc,
                )
            except (AIConfigError, AIRequestError, ValueError) as exc:
                return FeatureResult(
                    feature=self.feature,
                    status="failed",
                    summary=f"{self.feature} analysis failed.",
                    data={},
                    errors=[str(exc)],
                ).to_dict()

        if parsed is None:
            return FeatureResult(
                feature=self.feature,
                status="failed",
                summary=f"{self.feature} analysis failed.",
                data={},
                errors=[str(last_parse_error)],
            ).to_dict()

        data = parsed.get("data", parsed)
        summary = parsed.get("summary") or self.default_summary(data)
        if not isinstance(data, dict):
            return FeatureResult(
                feature=self.feature,
                status="failed",
                summary=f"{self.feature} analysis failed.",
                data={},
                errors=["AI response data must be a JSON object."],
            ).to_dict()

        # Value-level check, on top of the shape check the parser already did.
        # api.py's _matches_contract only verifies types, so any number passes
        # for a numeric field -- a readiness score of 0.32 or 900 would reach
        # the dashboard and render verbatim. Fail closed instead: a value
        # outside its contract means the model ignored the contract, and that
        # is worth surfacing rather than displaying.
        invalid = self.validate_data(data)
        if invalid:
            return FeatureResult(
                feature=self.feature,
                status="failed",
                summary=f"{self.feature} analysis failed.",
                data={},
                errors=[invalid],
            ).to_dict()

        return FeatureResult(
            feature=self.feature,
            status="success",
            summary=summary,
            data=data,
            errors=[],
        ).to_dict()

    def build_messages(self, student_profile: Mapping[str, Any], prompt_template: str) -> list[dict[str, str]]:
        student_context = self.build_student_context(student_profile)
        return [
            {
                "role": "system",
                "content": (
                    "You are Campus IQ. Return valid JSON only. Do not wrap the response "
                    "in Markdown. Follow the requested output contract exactly."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{prompt_template}\n\n"
                    "Return JSON only using this feature result contract:\n"
                    f"{json.dumps(self.feature_contract(), indent=2)}\n\n"
                    "Relevant student profile context:\n"
                    f"{json.dumps(student_context, indent=2, sort_keys=True)}"
                ),
            },
        ]

    def build_student_context(self, student_profile: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "student": student_profile.get("student", {}),
            "career": student_profile.get("career", {}),
        }

    def feature_contract(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "summary": "string",
            "data": self.output_contract,
        }

    def validate_data(self, data: Mapping[str, Any]) -> str | None:
        """Return an error message if the parsed data is unusable, else None.

        Hook for value-level constraints a JSON-shape check cannot express
        (ranges, enums, cross-field consistency). Default is no-op: most
        contracts are fully described by their shape.
        """
        return None

    def default_summary(self, data: Mapping[str, Any]) -> str:
        return f"{self.feature} analysis completed."


def load_prompt_template(path: Path) -> str:
    try:
        prompt = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Prompt file not found: {path}") from exc
    if not prompt.strip():
        raise ValueError(f"Prompt file is empty: {path}")
    return prompt


def find_missing_fields(data: Mapping[str, Any], paths: Sequence[str]) -> list[str]:
    return [path for path in paths if is_missing(get_path(data, path))]


def get_path(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return len(value) == 0
    if isinstance(value, Mapping):
        return len(value) == 0
    return False
