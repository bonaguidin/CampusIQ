"""Shared contracts and helpers for Gradus IQ feature runners."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence

from GradusIQ_career.ai.errors import AIConfigError, AIRequestError, AIResponseParseError
from GradusIQ_career.ai.parser import parse_ai_json_response


FeatureStatus = Literal["success", "skipped", "failed"]

PROMPT_DIR = Path(__file__).resolve().parents[1]


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

        try:
            prompt_template = load_prompt_template(self.prompt_path)
            response = self.client.complete(
                messages=self.build_messages(student_profile, prompt_template),
                role=self.role,
            )
            parsed = parse_ai_json_response(response.text)
        except (OSError, AIConfigError, AIRequestError, AIResponseParseError, ValueError) as exc:
            return FeatureResult(
                feature=self.feature,
                status="failed",
                summary=f"{self.feature} analysis failed.",
                data={},
                errors=[str(exc)],
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
                    "You are Gradus IQ. Return valid JSON only. Do not wrap the response "
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
