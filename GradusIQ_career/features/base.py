"""Shared contracts and helpers for Gradus IQ feature runners."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence

from GradusIQ_career.ai.errors import AIConfigError, AIRequestError, AIResponseParseError
from GradusIQ_career.ai.parser import parse_ai_json_response


FeatureStatus = Literal["success", "skipped", "failed"]

PROMPT_DIR = Path(__file__).resolve().parents[1]

# Human labels for every path any runner gates on. THE SINGLE SOURCE OF TRUTH:
# GAP, FIT, SHIFT and PROFESSOR_COMMENTS all skip through the one gate in
# CareerFeatureRunner.run, so a label written here cannot drift between
# features the way a per-feature map or a frontend copy would.
#
# These are the words the student reads when an analysis will not run, so they
# name the thing they would go and fill in -- "AI comfort level", not
# "career.ai_anxiety_level", and not the column name either. The dotted path
# still travels alongside the label (see MissingField) for the deep link and
# for logs; it is simply never the thing rendered.
FIELD_LABELS: Mapping[str, str] = {
    "student.expected_graduation": "Expected graduation",
    "student.major_intended": "Intended major",
    "career.target_roles": "Target roles",
    "career.interests": "Career interests",
    "career.ai_anxiety_level": "AI comfort level",
    "career.skills_self_reported": "Skills",
    "career.work_experience": "Work experience",
    "submissions": "Course submissions",
    "submissions[].submission_comments": "Professor feedback on your submissions",
}


def field_label(path: str) -> str:
    """Human label for a gated path, falling back to a readable form of it.

    The fallback exists so that adding a path to some runner's required_paths
    and forgetting this map degrades to "Career goals" rather than to a raw
    dotted path leaking into the UI -- a missing entry should read as slightly
    generic, not as a bug the student is looking at.
    """
    known = FIELD_LABELS.get(path)
    if known:
        return known
    leaf = path.split(".")[-1].replace("[]", "").replace("_", " ").strip()
    return leaf[:1].upper() + leaf[1:] if leaf else path


@dataclass(frozen=True)
class MissingField:
    """One unmet precondition, in both registers.

    `path` is what the code gates on; `label` is what the student reads. They
    are carried together rather than the frontend re-deriving one from the
    other, which would put a second copy of FIELD_LABELS in TypeScript and
    guarantee the two eventually disagree.
    """

    path: str
    label: str


@dataclass(frozen=True)
class FeatureResult:
    feature: str
    status: FeatureStatus
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # Populated only on the skip path. `errors` stays a flat list of strings
    # because it also carries transport failures and contract violations, which
    # have no field to point at -- widening it to a union would make every
    # consumer type-check something that is a string in most cases.
    missing_fields: list[MissingField] = field(default_factory=list)

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
        # required_paths can only express dot-separated dict keys (see
        # get_path), so a runner whose real precondition lives inside a list
        # -- e.g. submissions[].submission_comments[] -- reports it via
        # additional_missing_fields and reuses this same skip path. Only
        # consulted when the declarative gate is already satisfied, so a
        # profile missing the top-level field reports that field alone.
        missing_fields = find_missing_fields(
            student_profile, self.required_paths
        ) or self.additional_missing_fields(student_profile)
        if missing_fields:
            resolved = [MissingField(path=path, label=field_label(path)) for path in missing_fields]
            return FeatureResult(
                feature=self.feature,
                status="skipped",
                summary="Missing required fields for this feature.",
                data={},
                # Labelled here too, not just in missing_fields: these strings
                # reach logs and any caller that predates missing_fields, and a
                # raw dotted path is no more useful in a log line than on screen.
                errors=[f"Missing required field: {item.label}" for item in resolved],
                missing_fields=resolved,
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

        # Valid JSON of the wrong shape is the same failure mode as malformed
        # JSON: the caller cannot render it. Reject rather than repair.
        contract_errors = self.validate_data(data, student_profile)
        if contract_errors:
            return FeatureResult(
                feature=self.feature,
                status="failed",
                summary=f"{self.feature} analysis failed.",
                data={},
                errors=contract_errors,
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

    def additional_missing_fields(self, student_profile: Mapping[str, Any]) -> list[str]:
        """Preconditions required_paths cannot express. Default: none.

        Returning a nonempty list produces the ordinary "skipped" result, so
        overriding this never introduces a new status or message.
        """
        return []

    def validate_data(
        self, data: Mapping[str, Any], student_profile: Mapping[str, Any]
    ) -> list[str]:
        """Contract violations in a parsed model response. Default: none.

        Opt-in per runner: the default keeps the historical "any JSON object
        is a success" behavior for runners that have not been reviewed for
        live-path validation yet.
        """
        return []

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
