"""
Campus IQ — Report Export (Layer 5)

Content-agnostic: converts ANY report's markdown → PDF or DOCX.
The script never inspects which feature produced the content. GAP, SHIFT,
professor comments, or the full combined report all arrive as markdown and
convert identically. Only the FORMAT (pdf/docx) and the FILENAME vary, and
both are passed in — never detected.

Input contract:  markdown (the shape the Report Generator / Rep emits)
Output:          .pdf or .docx, named firstname_lastname_FEATURE_YYYY-MM.ext

Steps 1-3 (this file): working conversion against the filled sample.
Branding (reference.docx / report.css) is deferred — runs clean without it.
"""

import re
import unicodedata
from datetime import date
from pathlib import Path

import pypandoc


# ─────────────────────────────────────────────────────────────
# Spec-appendix strip — safety guard
# ─────────────────────────────────────────────────────────────
# The filled TEMPLATE.md carries a "Template Spec" section below a double
# horizontal rule. That's scaffolding for the build team and must NEVER
# appear in a student-facing export.
#
#   - In testing: we feed TEMPLATE.md, which HAS the spec -> this strips it.
#   - In production: Rep won't emit a spec at all -> this is a no-op guard.
#
# We cut from the "## Template Spec" heading to end of document.
def strip_spec_appendix(markdown_text: str) -> str:
    marker = re.search(r"\n#{1,6}\s+Template Spec\b", markdown_text)
    if not marker:
        return markdown_text.rstrip() + "\n"
    cut = markdown_text[: marker.start()]
    # also drop a trailing separator rule (--- / ----) left dangling above it
    cut = re.sub(r"\n-{3,}\s*$", "", cut.rstrip())
    return cut.rstrip() + "\n"


# ─────────────────────────────────────────────────────────────
# Filename slug — real names -> safe filenames
# ─────────────────────────────────────────────────────────────
# "Ethan Brooks"       -> "ethan_brooks"
# "Mary-Jane O'Brien"  -> "mary_jane_obrien"
# "José García-López"  -> "jose_garcia_lopez"
def slugify_name(name: str) -> str:
    # strip accents -> ascii
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower()
    name = name.replace("'", "").replace("\u2019", "")      # drop apostrophes
    name = re.sub(r"[^a-z0-9]+", "_", name)                 # everything else -> _
    return re.sub(r"_+", "_", name).strip("_")


def build_filename(student_name: str, feature: str, fmt: str,
                   period: str | None = None) -> str:
    """firstname_lastname_FEATURE_YYYY-MM.ext
       feature='combined' for the full report."""
    period = period or date.today().strftime("%Y-%m")
    return f"{slugify_name(student_name)}_{feature}_{period}.{fmt}"


# ─────────────────────────────────────────────────────────────
# Core export — the whole point: branches on FORMAT, not content
# ─────────────────────────────────────────────────────────────
def export_report(markdown_text: str, fmt: str, out_path: str,
                  reference_docx: str | None = None,
                  css_path: str | None = None) -> str:
    fmt = fmt.lower()
    clean_md = strip_spec_appendix(markdown_text)

    if fmt == "docx":
        extra = []
        if reference_docx:                     # branding, deferred
            extra.append(f"--reference-doc={reference_docx}")
        pypandoc.convert_text(
            clean_md, "docx", format="md",
            outputfile=out_path, extra_args=extra,
        )

    elif fmt == "pdf":
        extra = ["--pdf-engine=weasyprint"]
        if css_path:                           # branding, deferred
            extra.append(f"--css={css_path}")
        pypandoc.convert_text(
            clean_md, "pdf", format="md",
            outputfile=out_path, extra_args=extra,
        )

    else:
        raise ValueError(f"Unsupported format {fmt!r}; use 'pdf' or 'docx'.")

    return out_path


# convenience wrapper: content + who/what -> correctly named file on disk
def export_named(markdown_text: str, student_name: str, feature: str,
                 fmt: str, out_dir: str = ".", **kw) -> str:
    fname = build_filename(student_name, feature, fmt)
    out_path = str(Path(out_dir) / fname)
    return export_report(markdown_text, fmt, out_path, **kw)


# ─────────────────────────────────────────────────────────────
# Smoke test — prove steps 1-3 against the filled sample
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    here = Path(__file__).parent
    sample = (here / "campus_iq_combined_report_TEMPLATE.md").read_text()
    out_dir = here / "out"
    out_dir.mkdir(exist_ok=True)

    # The sample is the COMBINED report for Ethan Brooks.
    # Same script, same call — a single-feature md would work identically.
    for fmt in ("docx", "pdf"):
        path = export_named(sample, "Ethan Brooks", "combined", fmt,
                            out_dir=str(out_dir))
        size = Path(path).stat().st_size
        print(f"  {fmt.upper():4} -> {Path(path).name}  ({size:,} bytes)")

    # Prove the spec appendix was stripped (must not appear in output).
    stripped = strip_spec_appendix(sample)
    assert "Template Spec" not in stripped, "SPEC LEAKED"
    assert "Through-Line" in stripped, "content lost"
    print("  spec stripped, report body intact")
