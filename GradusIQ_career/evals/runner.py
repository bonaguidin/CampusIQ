from collections import Counter
from typing import Callable, Iterable

from .evaluators import aggregate, evaluate_fixture
from .models import EvalFeature, EvalRunResult, EvalScenario, EvalStatus, validate_unique_scenarios


LiveExecutor = Callable[[EvalScenario, EvalFeature], dict]


def select_controlled_live_scenarios(
    scenarios: Iterable[EvalScenario], *, per_feature: int = 3
) -> list[EvalScenario]:
    """Validate the complete controlled set before any executor can run."""
    available = list(scenarios)
    validate_unique_scenarios(available)
    selected: list[EvalScenario] = []
    for feature in EvalFeature:
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


def run_scenarios(
    scenarios: Iterable[EvalScenario], *, feature: EvalFeature | None = None,
    scenario_id: str | None = None, live: bool = False, live_executor: LiveExecutor | None = None,
    max_runs: int | None = None,
) -> list[EvalRunResult]:
    selected = list(scenarios)
    validate_unique_scenarios(selected)
    if live and live_executor is None:
        raise ValueError("Live evaluation requires an explicit live executor.")
    results = []
    for scenario in selected:
        if scenario_id and scenario.scenario_id != scenario_id:
            continue
        for applicable in sorted(scenario.features, key=lambda item: item.value):
            if live and not scenario.live_eligible:
                continue
            if feature and applicable != feature:
                continue
            if max_runs is not None and len(results) >= max_runs:
                return results
            observation = live_executor(scenario, applicable) if live else scenario.fixture_results.get(applicable)
            if observation is None:
                metrics = []
                status = EvalStatus.ERROR
            else:
                metrics = evaluate_fixture(scenario, applicable, observation)
                status = aggregate(metrics)
            results.append(EvalRunResult(
                scenario_id=scenario.scenario_id, scenario_version=scenario.scenario_version,
                feature=applicable, prompt_name=applicable.value, prompt_version="1.0",
                model=observation.get("model") if isinstance(observation, dict) else None,
                status=status, metrics=metrics,
                latency_ms=observation.get("latency_ms", 0) if isinstance(observation, dict) else 0,
                attempt_count=observation.get("attempt_count", 0) if isinstance(observation, dict) else 0,
                repair_count=observation.get("repair_count", 0) if isinstance(observation, dict) else 0,
                input_tokens=observation.get("input_tokens") if isinstance(observation, dict) else None,
                output_tokens=observation.get("output_tokens") if isinstance(observation, dict) else None,
                total_tokens=observation.get("total_tokens") if isinstance(observation, dict) else None,
                grounding_status=next((m.status for m in metrics if m.name == "forbidden_unsupported_claims"), EvalStatus.UNVERIFIABLE),
            ))
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
