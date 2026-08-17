import argparse
import json
import os
import tempfile
from pathlib import Path

from .models import EvalFeature, EvalRunResult
from .runner import (
    compare_runs,
    run_scenarios,
    select_controlled_course_discovery_scenarios,
    select_controlled_live_scenarios,
)
from .scenarios import SCENARIOS
from .course_discovery_scenarios import COURSE_DISCOVERY_SCENARIOS


TRANSIENT_OUTPUT_DIR = Path("eval-results")


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError:
        return False
    return True


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Gradus IQ evaluations.")
    parser.add_argument("--feature", choices=[item.value for item in EvalFeature] + ["all"], default="all")
    parser.add_argument("--suite", choices=["phase-b", "course-discovery"], default="phase-b")
    parser.add_argument("--all", action="store_true", help="Run every applicable feature.")
    parser.add_argument("--scenario")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--baseline-output",
        type=Path,
        help="Explicitly create a reviewed baseline file; never overwrites an existing baseline.",
    )
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the 12 live selections without provider calls.")
    parser.add_argument("--max-runs", type=int)
    args = parser.parse_args(argv)
    if args.baseline_output and _inside(args.baseline_output, TRANSIENT_OUTPUT_DIR):
        parser.error("Reviewed baselines must not be written inside ignored eval-results/.")
    if args.live and args.dry_run:
        parser.error("Choose either --live or --dry-run, not both.")
    if args.live:
        if os.getenv("GRADUSIQ_EVAL_LIVE") != "1":
            parser.error("--live also requires GRADUSIQ_EVAL_LIVE=1")
        required_runs = 6 if args.suite == "course-discovery" else 12
        if args.max_runs is not None and args.max_runs != required_runs:
            parser.error(f"The controlled {args.suite} suite requires exactly {required_runs} evaluations.")
        if args.output is None or not _inside(args.output, TRANSIENT_OUTPUT_DIR):
            parser.error("Live output must be written under the ignored eval-results/ directory.")
    selected_scenarios = (
        COURSE_DISCOVERY_SCENARIOS if args.suite == "course-discovery" else SCENARIOS
    )
    if args.live or args.dry_run:
        try:
            selected_scenarios = (
                select_controlled_course_discovery_scenarios(COURSE_DISCOVERY_SCENARIOS)
                if args.suite == "course-discovery"
                else select_controlled_live_scenarios(SCENARIOS)
            )
        except ValueError as exc:
            parser.error(str(exc))
    if args.dry_run:
        print(json.dumps({
            "provider_calls": 0,
            "research_calls": 0,
            "total": len(selected_scenarios),
            "planned": len(selected_scenarios),
            "selected": len(selected_scenarios),
            "valid": len(selected_scenarios),
            "selections": [
                {
                    "scenario_id": scenario.scenario_id,
                    "feature": next(iter(scenario.features)).value,
                    "purpose": scenario.purpose,
                    "input_fingerprint": scenario.synthetic_input.safe_fingerprint(),
                }
                for scenario in selected_scenarios
            ],
        }, indent=2, sort_keys=True))
        return 0
    feature = None if args.all or args.feature == "all" else EvalFeature(args.feature)
    live_executor = None
    if args.live:
        from .live import execute_live
        live_executor = execute_live
    artifact = {
        "artifact_version": "2.0",
        "run_status": "incomplete",
        "planned": len(selected_scenarios) if not feature and not args.scenario else None,
        "completed": 0,
        "results": [],
    }
    if args.output:
        _atomic_write(args.output, artifact)

    def record_result(result, completed, planned):
        artifact["planned"] = planned
        artifact["completed"] = completed
        artifact["results"].append(result.model_dump(mode="json"))
        if args.output:
            _atomic_write(args.output, artifact)

    def progress(event, scenario, applicable, index, planned, result):
        if not args.live:
            return
        if event == "started":
            label = (
                applicable.value if applicable == EvalFeature.COURSE_DISCOVERY
                else applicable.value.upper()
            )
            print(f"[{index}/{planned}] {label} {scenario.scenario_id} started", flush=True)
        else:
            review = result.course_discovery_review
            counts = (
                f" verified={review.tool_summary.verified_count}"
                f" unresolved={review.tool_summary.unresolved_count}"
                if review else ""
            )
            print(
                f"[{index}/{planned}] completed status={result.status.value}{counts}",
                flush=True,
            )

    results = run_scenarios(
        selected_scenarios,
        feature=feature,
        scenario_id=args.scenario,
        live=args.live,
        live_executor=live_executor,
        max_runs=(6 if args.suite == "course-discovery" else 12) if args.live else None,
        on_result=record_result,
        on_progress=progress,
    )
    artifact["run_status"] = "complete"
    artifact["planned"] = len(results)
    artifact["completed"] = len(results)
    if args.output:
        _atomic_write(args.output, artifact)
    payload = [result.model_dump(mode="json") for result in results]
    output = {**artifact, "results": payload}
    if args.compare:
        prior = [
            EvalRunResult.model_validate(item)
            for item in json.loads(args.compare.read_text())["results"]
        ]
        output["comparison"] = compare_runs(prior, results)
    rendered = json.dumps(output, indent=2, sort_keys=True)
    if args.baseline_output:
        if args.baseline_output.exists():
            parser.error("Baseline already exists; refusing to overwrite it.")
        _atomic_write(args.baseline_output, output)
    if args.live or args.output:
        print(json.dumps({
            "run_status": output["run_status"],
            "planned": output["planned"],
            "completed": output["completed"],
        }, sort_keys=True))
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
