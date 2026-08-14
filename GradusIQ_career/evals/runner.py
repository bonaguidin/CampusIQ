from collections import Counter
from typing import Callable, Iterable

from .evaluators import aggregate, evaluate_fixture
from .models import EvalFeature, EvalRunResult, EvalScenario, EvalStatus, validate_unique_scenarios


PHASE_B_FEATURES = (
    EvalFeature.FIT, EvalFeature.GAP, EvalFeature.SHIFT, EvalFeature.CHAT
)


LiveExecutor = Callable[[EvalScenario, EvalFeature], dict]
ResultCallback = Callable[[EvalRunResult, int, int], None]
ProgressCallback = Callable[[str, EvalScenario, EvalFeature, int, int, EvalRunResult | None], None]


def select_controlled_live_scenarios(
    scenarios: Iterable[EvalScenario], *, per_feature: int = 3
) -> list[EvalScenario]:
    """Validate the complete controlled set before any executor can run."""
    available = list(scenarios)
    validate_unique_scenarios(available)
    selected: list[EvalScenario] = []
    for feature in PHASE_B_FEATURES:
        matches = [
            scenario
            for scenario in available
            if scenario.live_eligible
            and feature in scenario.features
            and scenario.purpose.strip()
            and scenario.expectations
        ]
        if len(matches) < per_feature:
            raise ValueError(
                f"Live evaluation requires {per_feature} valid {feature.value} scenarios; "
                f"found {len(matches)}."
            )
        selected.extend(matches[:per_feature])
    if len(selected) > 12:
        raise ValueError("Controlled live selection exceeds the 12-evaluation hard cap.")
    return selected


def select_controlled_course_discovery_scenarios(
    scenarios: Iterable[EvalScenario],
) -> list[EvalScenario]:
    """Validate all six C2 cases, including deterministic fixture state, up front."""
    from GradusIQ_career.course_discovery.service import CourseDiscoveryService
    from .live import build_course_discovery_context

    selected = list(scenarios)
    validate_unique_scenarios(selected)
    if len(selected) != 6:
        raise ValueError(f"Controlled Course Discovery requires exactly 6 scenarios; found {len(selected)}.")
    fingerprints = set()
    for scenario in selected:
        if scenario.features != {EvalFeature.COURSE_DISCOVERY} or not scenario.live_eligible:
            raise ValueError(f"Invalid controlled Course Discovery scenario: {scenario.scenario_id}.")
        if scenario.course_discovery_expectation is None:
            raise ValueError(f"Missing Course Discovery expectation: {scenario.scenario_id}.")
        fingerprints.add(scenario.synthetic_input.safe_fingerprint())
        context = build_course_discovery_context(scenario)
        actual = CourseDiscoveryService(context).check_eligibility(
            scenario.course_discovery_expectation.candidate_code
        ).status.value
        if actual != scenario.course_discovery_expectation.expected_state:
            raise ValueError(
                f"Invalid expected catalog state for {scenario.scenario_id}: "
                f"expected {scenario.course_discovery_expectation.expected_state}, got {actual}."
            )
        for code in scenario.course_discovery_expectation.additional_candidate_codes:
            additional = CourseDiscoveryService(context).check_eligibility(code).status.value
            if additional != "ELIGIBLE":
                raise ValueError(
                    f"Additional candidate {code} for {scenario.scenario_id} is {additional}, not ELIGIBLE."
                )
    if len(fingerprints) != 6:
        raise ValueError("Controlled Course Discovery inputs must have 6 distinct fingerprints.")
    return selected


def run_scenarios(
    scenarios: Iterable[EvalScenario], *, feature: EvalFeature | None = None,
    scenario_id: str | None = None, live: bool = False, live_executor: LiveExecutor | None = None,
    max_runs: int | None = None,
    on_result: ResultCallback | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[EvalRunResult]:
    selected = list(scenarios)
    validate_unique_scenarios(selected)
    if live and live_executor is None:
        raise ValueError("Live evaluation requires an explicit live executor.")
    work = [
        (scenario, applicable)
        for scenario in selected
        if not scenario_id or scenario.scenario_id == scenario_id
        for applicable in sorted(scenario.features, key=lambda item: item.value)
        if (not live or scenario.live_eligible) and (not feature or applicable == feature)
    ]
    if max_runs is not None:
        work = work[:max_runs]
    results = []
    planned = len(work)
    for index, (scenario, applicable) in enumerate(work, 1):
        if on_progress:
            on_progress("started", scenario, applicable, index, planned, None)
        observation = live_executor(scenario, applicable) if live else scenario.fixture_results.get(applicable)
        if observation is None:
            metrics = []
            status = EvalStatus.ERROR
        else:
            metrics = evaluate_fixture(scenario, applicable, observation)
            status = aggregate(metrics)
        observation = observation if isinstance(observation, dict) else {}
        reviewable = observation.get("reviewable_output")
        if reviewable is None:
            reviewable = observation.get("text") if applicable == EvalFeature.CHAT else observation.get("data")
        result = EvalRunResult(
                scenario_id=scenario.scenario_id, scenario_version=scenario.scenario_version,
                feature=applicable, purpose=scenario.purpose,
                input_fingerprint=scenario.synthetic_input.safe_fingerprint(),
                prompt_name=applicable.value, prompt_version="1.0",
                model=observation.get("model"),
                status=status, metrics=metrics,
                latency_ms=observation.get("latency_ms", 0),
                attempt_count=observation.get("attempt_count", 0),
                repair_count=observation.get("repair_count", 0),
                input_tokens=observation.get("input_tokens"),
                output_tokens=observation.get("output_tokens"),
                total_tokens=observation.get("total_tokens"),
                grounding_status=next((m.status for m in metrics if m.name == "forbidden_unsupported_claims"), EvalStatus.UNVERIFIABLE),
                reviewable_output=reviewable,
                safe_grounding_summary=observation.get("safe_grounding_summary", {}),
                research_summary=observation.get("research_summary", {}),
                stage_timing=observation.get("stage_timing", {}),
                trace_summary=observation.get("trace_summary", {}),
                review_convenience=observation.get("review_convenience", {}),
                course_discovery_review=observation.get("course_discovery_review"),
            )
        results.append(result)
        if on_result:
            on_result(result, len(results), planned)
        if on_progress:
            on_progress("completed", scenario, applicable, index, planned, result)
    return results


def compare_runs(before: list[EvalRunResult], after: list[EvalRunResult]) -> dict:
    def totals(values):
        statuses = Counter(item.status.value for item in values)
        return {
            "count": len(values), "statuses": dict(statuses),
            "latency_ms": sum(item.latency_ms for item in values),
            "total_tokens": sum(item.total_tokens or 0 for item in values),
            "attempts": sum(item.attempt_count for item in values),
            "repairs": sum(item.repair_count for item in values),
            "models": sorted({item.model for item in values if item.model}),
            "prompts": sorted({f"{item.prompt_name}:{item.prompt_version}" for item in values}),
        }
    return {"before": totals(before), "after": totals(after)}
