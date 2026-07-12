"""Build cached career-analysis output for the demo.

This is the demo bridge between the Python AI engine and the React dashboard.
Rather than stand up a live server (Phase 2), we run the orchestrator once per
student and write the result to ``frontend/public/data/analysis_<slug>.json``,
which the frontend can fetch exactly like it already fetches
``student_<slug>.json``. This also de-risks the live demo: nothing calls
OpenRouter during the presentation.

Usage:
    # Real run (needs OPENROUTER_API_KEY and real model ids in model_config.py):
    uv run python -m CampusIQ_career.demo.build_demo_cache

    # Mock run (no API key, structurally-valid placeholder output so the
    # frontend wiring and export/cache layer can be built/tested offline):
    uv run python -m CampusIQ_career.demo.build_demo_cache --mock

    # Limit to specific students by slug:
    uv run python -m CampusIQ_career.demo.build_demo_cache --only priyaNair marcusWebb
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STUDENTS_DIR = _REPO_ROOT / "data" / "students"
_OUTPUT_DIR = _REPO_ROOT / "frontend" / "public" / "data"


def _slug_from_filename(path: Path) -> str:
    """student_priyaNair.json -> priyaNair."""
    name = path.stem
    return name[len("student_"):] if name.startswith("student_") else name


class _MockClient:
    """Stand-in AI client that returns structurally-valid placeholder JSON.

    Inspects the outgoing prompt to decide which feature contract to satisfy,
    so orchestrator/parser/runner logic exercises end-to-end without a network
    call. Import of AIResponse is deferred so --mock works even before the
    real model ids are set.
    """

    def __init__(self) -> None:
        from CampusIQ_career.ai.types import AIResponse  # local import by design

        self._AIResponse = AIResponse

    def complete(self, *, messages: Sequence[Any], role: Any = None, **_: Any):
        blob = " ".join(
            str(m.get("content", "") if isinstance(m, Mapping) else getattr(m, "content", ""))
            for m in messages
        )
        payload = self._payload_for(blob)
        return self._AIResponse(
            text=json.dumps(payload), raw={"choices": []}, model="mock"
        )

    @staticmethod
    def _payload_for(blob: str) -> dict[str, Any]:
        upper = blob.upper()
        if "GAP" in upper:
            return {
                "readiness_score": 62,
                "strengths": ["[MOCK] Strong analytical foundation from coursework"],
                "must_have_gaps": ["[MOCK] Industry-standard tooling / internship experience"],
                "nice_to_have_gaps": ["[MOCK] A relevant certification"],
                "recommended_next_steps": ["[MOCK] Complete one portfolio project this term"],
            }
        if "FIT" in upper:
            return {
                "role_matches": [
                    {"role": "[MOCK] Target Role", "fit_score": 78,
                     "why_it_fits": "[MOCK] Aligns with declared major and interests."}
                ]
            }
        if "SHIFT" in upper:
            return {
                "role_evolution_summary": "[MOCK] Role family is shifting toward AI-augmented workflows.",
                "adjacent_paths": ["[MOCK] Adjacent role"],
                "ai_articulation_coaching": ["[MOCK] Frame AI fluency as a productivity multiplier."],
            }
        return {"note": "[MOCK] unrecognized feature prompt"}


def _make_client(mock: bool):
    if mock:
        return _MockClient()
    from CampusIQ_career.ai import OpenRouterClient  # local import by design
    from CampusIQ_career.ai.openrouter_client import DEEPSEEK_R1_REASONING_TIMEOUT_SECONDS

    # Real calls run the DeepSeek R1 career/academic roles end to end, which
    # routinely take 100-200s+ -- match api.py's build_client() timeout
    # rather than the library's 30s default. Raises AIConfigError if
    # OPENROUTER_API_KEY is unset.
    return OpenRouterClient(timeout=DEEPSEEK_R1_REASONING_TIMEOUT_SECONDS)


def build(only: Sequence[str] | None, mock: bool) -> int:
    from CampusIQ_career.features.orchestrator import run_career_analysis

    if not _STUDENTS_DIR.exists():
        print(f"ERROR: students dir not found: {_STUDENTS_DIR}", file=sys.stderr)
        return 1

    client = _make_client(mock)
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    student_files = sorted(_STUDENTS_DIR.glob("student_*.json"))
    if only:
        wanted = set(only)
        student_files = [p for p in student_files if _slug_from_filename(p) in wanted]

    if not student_files:
        print("ERROR: no matching student files.", file=sys.stderr)
        return 1

    failures = 0
    for path in student_files:
        slug = _slug_from_filename(path)
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
            result = run_career_analysis(profile, client)
        except Exception as exc:  # keep going; one bad student shouldn't kill the cache
            failures += 1
            print(f"  [FAIL] {slug}: {exc}", file=sys.stderr)
            continue

        out_path = _OUTPUT_DIR / f"analysis_{slug}.json"
        out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        status = result.get("status", "?")
        print(f"  [{status:>15}] {slug} -> {out_path.relative_to(_REPO_ROOT)}")

    mode = "MOCK" if mock else "LIVE"
    print(f"\nDone ({mode}). {len(student_files) - failures}/{len(student_files)} students cached.")
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build cached career-analysis JSON for the demo.")
    parser.add_argument("--mock", action="store_true",
                        help="Use placeholder output instead of calling OpenRouter.")
    parser.add_argument("--only", nargs="*", default=None,
                        help="Limit to these student slugs (e.g. priyaNair).")
    args = parser.parse_args(argv)
    return build(only=args.only, mock=args.mock)


if __name__ == "__main__":
    raise SystemExit(main())
