import argparse
import json
import os
from pathlib import Path

from .models import EvalFeature, EvalRunResult
from .runner import compare_runs, run_scenarios, select_controlled_live_scenarios
from .scenarios import SCENARIOS


TRANSIENT_OUTPUT_DIR = Path("eval-results")


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError:
        return False
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Gradus IQ evaluations.")
    parser.add_argument("--feature", choices=[item.value for item in EvalFeature] + ["all"], default="all")
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
    parser.add_argument("--max-runs", type=int, default=12)
    args = parser.parse_args(argv)
    if args.baseline_output and _inside(args.baseline_output, TRANSIENT_OUTPUT_DIR):
        parser.error("Reviewed baselines must not be written inside ignored eval-results/.")
    if args.live and args.dry_run:
        parser.error("Choose either --live or --dry-run, not both.")
    if args.live:
        if os.getenv("GRADUSIQ_EVAL_LIVE") != "1":
            parser.error("--live also requires GRADUSIQ_EVAL_LIVE=1")
        if args.max_runs < 1 or args.max_runs > 12:
            parser.error("--max-runs must be between 1 and 12")
        if args.max_runs != 12:
            parser.error("The controlled baseline requires exactly 12 validated evaluations.")
        if args.output is None or not _inside(args.output, TRANSIENT_OUTPUT_DIR):
            parser.error("Live output must be written under the ignored eval-results/ directory.")
    selected_scenarios = SCENARIOS
    if args.live or args.dry_run:
        try:
            selected_scenarios = select_controlled_live_scenarios(SCENARIOS)
        except ValueError as exc:
            parser.error(str(exc))
    if args.dry_run:
        print(json.dumps({
            "provider_calls": 0,
            "research_calls": 0,
            "total": len(selected_scenarios),
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
    results = run_scenarios(
        selected_scenarios, feature=feature, scenario_id=args.scenario, live=args.live,
        live_executor=live_executor, max_runs=args.max_runs if args.live else None,
    )
    payload = [result.model_dump(mode="json") for result in results]
    output = {"results": payload}
    if args.compare:
        prior = [
            EvalRunResult.model_validate(item)
            for item in json.loads(args.compare.read_text())["results"]
        ]
        output["comparison"] = compare_runs(prior, results)
    rendered = json.dumps(output, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.baseline_output:
        if args.baseline_output.exists():
            parser.error("Baseline already exists; refusing to overwrite it.")
        args.baseline_output.parent.mkdir(parents=True, exist_ok=True)
        args.baseline_output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
