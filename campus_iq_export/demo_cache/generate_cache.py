"""
Campus IQ — Demo Cache Generator

Regenerates the cached fallback set: every source report in source_md/
-> PDF + DOCX in out/, using the shared export script.

WHY THIS EXISTS
The cached fallback is what the demo shows if live generation fails
(OpenRouter slow/down). These files are pre-generated so the demo never
depends on a live model call at showcase time.

WHAT'S REAL vs REPRESENTATIVE (read this)
The source markdown in source_md/ is REPRESENTATIVE content, not live
model output — because the pipeline that produces real output (data layer
-> agents -> Report Generator) isn't built yet. When it is, replace the
files in source_md/ with real report output and re-run this script. The
output filenames and structure stay identical, so nothing downstream changes.

USAGE
    python generate_cache.py
"""

import sys
from pathlib import Path

# import the shared export script from the parent folder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import export  # noqa: E402

HERE = Path(__file__).resolve().parent
SOURCE_DIR = HERE / "source_md"
OUT_DIR = HERE / "out"

STUDENT_NAME = "Ethan Brooks"

# source filename stem -> feature label used in the output filename
# 'combined' = the full report; the rest are single-feature reports.
FEATURE_MAP = {
    "ethan_brooks_combined": "combined",
    "ethan_brooks_FIT": "FIT",
    "ethan_brooks_GAP": "GAP",
    "ethan_brooks_SHIFT": "SHIFT",
    # Academic per-feature reports slot in here once their runners exist:
    # "ethan_brooks_PROF": "professor_comments",
    # "ethan_brooks_EXAM": "exam_gap",
    # "ethan_brooks_STUDY": "study_guide",
    # "ethan_brooks_COURSE": "course_rec",
}


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    generated = []

    for stem, feature in FEATURE_MAP.items():
        source = SOURCE_DIR / f"{stem}.md"
        if not source.exists():
            print(f"  SKIP  {stem} — no source file")
            continue

        markdown = source.read_text(encoding="utf-8")
        for fmt in ("pdf", "docx"):
            path = export.export_named(
                markdown, STUDENT_NAME, feature, fmt, out_dir=str(OUT_DIR)
            )
            size = Path(path).stat().st_size
            generated.append(Path(path).name)
            print(f"  OK    {Path(path).name}  ({size:,} bytes)")

    print(f"\n  {len(generated)} files written to {OUT_DIR}")
    print("  Commit the out/ folder — those files ARE the fallback cache.")


if __name__ == "__main__":
    main()
