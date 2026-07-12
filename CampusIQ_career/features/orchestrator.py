"""Career feature orchestration for Campus IQ."""

from typing import Any, Mapping, Sequence

from .academic import AcademicRunner
from .base import FeatureResult
from .fit import FitRunner
from .gap import GapRunner
from .shift import ShiftRunner


DEFAULT_CAREER_FEATURES = ("FIT", "GAP", "SHIFT")

RUNNERS = {
    "FIT": FitRunner,
    "GAP": GapRunner,
    "SHIFT": ShiftRunner,
    "PROFESSOR_COMMENTS": AcademicRunner,
}


def normalize_feature_name(feature_name: str) -> str:
    normalized = feature_name.strip().upper()
    if normalized not in RUNNERS:
        supported = ", ".join(sorted(RUNNERS))
        raise ValueError(f"Unsupported career feature '{feature_name}'. Expected one of: {supported}.")
    return normalized


def run_feature(feature_name: str, student_profile: Mapping[str, Any], client: Any) -> dict[str, Any]:
    normalized = normalize_feature_name(feature_name)
    try:
        return RUNNERS[normalized](client=client).run(student_profile)
    except Exception as exc:
        return FeatureResult(
            feature=normalized,
            status="failed",
            summary=f"{normalized} analysis failed.",
            data={},
            errors=[str(exc)],
        ).to_dict()


def run_career_analysis(
    student_profile: Mapping[str, Any],
    client: Any,
    features: Sequence[str] | None = None,
) -> dict[str, Any]:
    requested = [normalize_feature_name(feature) for feature in (features or DEFAULT_CAREER_FEATURES)]
    results = {
        feature: run_feature(feature, student_profile, client)
        for feature in requested
    }
    status = summarize_status([result["status"] for result in results.values()])
    errors = collect_errors(results)

    return {
        "analysis_type": "career",
        "status": status,
        "student_id": get_student_id(student_profile),
        "features_requested": requested,
        "results": results,
        "summary": build_summary(status, results),
        "errors": errors,
    }


def summarize_status(statuses: Sequence[str]) -> str:
    if statuses and all(status == "success" for status in statuses):
        return "success"
    if statuses and all(status == "skipped" for status in statuses):
        return "skipped"
    if statuses and all(status == "failed" for status in statuses):
        return "failed"
    if any(status == "success" for status in statuses):
        return "partial_success"
    return "failed"


def collect_errors(results: Mapping[str, Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    for feature, result in results.items():
        for error in result.get("errors", []):
            errors.append(f"{feature}: {error}")
    return errors


def build_summary(status: str, results: Mapping[str, Mapping[str, Any]]) -> str:
    total = len(results)
    succeeded = sum(1 for result in results.values() if result.get("status") == "success")
    skipped = sum(1 for result in results.values() if result.get("status") == "skipped")
    failed = sum(1 for result in results.values() if result.get("status") == "failed")

    if status == "success":
        return f"Career analysis completed successfully for {total} feature(s)."
    if status == "skipped":
        return f"Career analysis skipped for all {total} requested feature(s)."
    if status == "failed":
        return f"Career analysis failed for all {total} requested feature(s)."
    return (
        "Career analysis partially completed: "
        f"{succeeded} succeeded, {skipped} skipped, {failed} failed."
    )


def get_student_id(student_profile: Mapping[str, Any]) -> str | None:
    student = student_profile.get("student")
    if not isinstance(student, Mapping):
        return None
    student_id = student.get("id")
    if student_id is None:
        return None
    return str(student_id)
