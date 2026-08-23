"""Build cached Course Discovery output for the demo students.

Sibling to build_demo_cache.py (GAP/FIT/SHIFT), but a separate script: the
pipeline (CourseDiscoveryAgent, not the GAP/FIT/SHIFT orchestrator) and the
mock-client interface are both different enough that folding this into the
existing file would blur both.

One target_role can have many CareerSkillNeed/CourseDiscoveryResult shapes
depending on the student, so caching is keyed on (student slug, target role)
-- every one of a demo student's target_roles gets its own cache file, so the
Course Discovery role-switcher dropdown works fully offline during a live
demo.

Action Plan is deliberately NOT cached here. build_action_plan/dependency_order
(GradusIQ_career/action_planning/) are pure, deterministic, no-I/O functions
of (target_role, skill_needs, course_discovery_result) -- recomputing them at
request time from this cached Course Discovery result always reproduces the
same output, so a second cache file would only be a second thing to keep in
sync.

Usage:
    # Real run (needs OPENROUTER_API_KEY and real model ids in model_config.py):
    uv run python -m GradusIQ_career.demo.build_course_discovery_cache

    # Mock run (no API key, structurally-valid empty-recommendations output,
    # for verifying the wiring end-to-end without spending anything):
    uv run python -m GradusIQ_career.demo.build_course_discovery_cache --mock

    # Limit to specific students by slug:
    uv run python -m GradusIQ_career.demo.build_course_discovery_cache --only priyaNair marcusWebb
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv

from GradusIQ_career.demo.profile_adapter import build_demo_intelligence_profile
from GradusIQ_career.demo.role_slug import role_slug

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STUDENTS_DIR = _REPO_ROOT / "data" / "students"
_OUTPUT_DIR = _REPO_ROOT / "data" / "demo_cache"


def _slug_from_filename(path: Path) -> str:
    name = path.stem
    return name[len("student_"):] if name.startswith("student_") else name


class _MockCourseDiscoveryClient:
    """Stand-in for CourseDiscoveryAgent's client -- a different interface
    than build_demo_cache.py's _MockClient (that one implements .complete(),
    the agent calls .complete_message()).

    A tool_calls-less response makes the agent's loop treat `content` as the
    final proposal immediately (see agent.py's run(), the `if tool_calls:`
    branch) -- an empty proposals list is always valid, producing a
    structurally-real, empty-recommendations CourseDiscoveryResult with zero
    network calls. Enough to verify the whole wiring; not real demo content.
    """

    def complete_message(self, *, messages: Any = None, role: Any = None, **_: Any) -> dict[str, Any]:
        return {"content": json.dumps({"proposals": []}), "tool_calls": None}


def _make_client(mock: bool):
    if mock:
        return _MockCourseDiscoveryClient()
    from GradusIQ_career.ai import OpenRouterClient
    from GradusIQ_career.ai.openrouter_client import DEEPSEEK_R1_REASONING_TIMEOUT_SECONDS

    return OpenRouterClient(timeout=DEEPSEEK_R1_REASONING_TIMEOUT_SECONDS)


def build(only: Sequence[str] | None, mock: bool) -> int:
    from GradusIQ_career.course_discovery.agent import CourseDiscoveryAgent
    from GradusIQ_career.course_discovery.models import CourseDiscoveryContext, resolve_institution
    from GradusIQ_career.course_discovery.needs import derive_career_skill_needs
    from GradusIQ_career.course_discovery.service import CourseDiscoveryService
    from GradusIQ_career.features.market_data import is_role_supported

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
    attempted = 0
    for path in student_files:
        slug = _slug_from_filename(path)
        profile_json = json.loads(path.read_text(encoding="utf-8"))
        canonical = build_demo_intelligence_profile(profile_json)
        institution = resolve_institution(canonical.institution.name)
        if institution is None:
            print(f"  [   SKIPPED] {slug}: unsupported institution '{canonical.institution.name}'", file=sys.stderr)
            continue

        for target_role in canonical.career.target_roles:
            if not is_role_supported(target_role):
                print(f"  [   SKIPPED] {slug} / {target_role!r}: not a curated role", file=sys.stderr)
                continue
            attempted += 1
            out_path = _OUTPUT_DIR / f"course_discovery_{slug}_{role_slug(target_role)}.json"
            try:
                needs = derive_career_skill_needs(canonical, target_role)
                context = CourseDiscoveryContext(profile=canonical, institution=institution, planned_courses=[])
                outcome = CourseDiscoveryAgent(CourseDiscoveryService(context), client).run(
                    target_role=target_role, needs=needs
                )
                if outcome.errors or outcome.result is None:
                    raise RuntimeError(f"agent errors: {outcome.errors}")
                result = {
                    "feature": "COURSE_DISCOVERY",
                    "status": "success",
                    "summary": outcome.result.summary,
                    "data": outcome.result.model_dump(mode="json"),
                    "errors": [],
                }
            except Exception as exc:  # keep going; one bad (student, role) shouldn't kill the batch
                failures += 1
                print(f"  [    FAILED] {slug} / {target_role!r}: {exc}", file=sys.stderr)
                continue
            out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            print(f"  [    cached] {slug} / {target_role!r} -> {out_path.relative_to(_REPO_ROOT)}")

    mode = "MOCK" if mock else "LIVE"
    print(f"\nDone ({mode}). {attempted - failures}/{attempted} (student, role) pairs cached.")
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build cached Course Discovery JSON for the demo.")
    parser.add_argument("--mock", action="store_true",
                        help="Use placeholder output instead of calling OpenRouter.")
    parser.add_argument("--only", nargs="*", default=None,
                        help="Limit to these student slugs (e.g. priyaNair).")
    args = parser.parse_args(argv)
    return build(only=args.only, mock=args.mock)


if __name__ == "__main__":
    raise SystemExit(main())
