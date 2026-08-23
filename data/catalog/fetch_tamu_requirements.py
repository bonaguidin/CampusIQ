#!/usr/bin/env python3
"""Fetch TAMU's degree-requirement plan grid for one CourseLeaf program page
and normalize it into a shape parallel to fetch_smu_requirements.py's output.

STAGE 1 SCRIPT -- not wired into any import path yet. See
planning-docs/tamu-degree-planner-scope.md for platform background and
planning-docs/degree-planner-spec.md (SMU) for the target shape this
mirrors. Two real shape gaps vs. SMU are called out below and are NOT
silently papered over.

SOURCE. catalog.tamu.edu runs CourseLeaf (confirmed via the "23.2.3"
version tag and branding), not Coursedog -- there is no JSON API. Each
program page has a tabbed "Program Requirements" section
(container id="programrequirementstextcontainer", the actual DOM id behind
the "#programrequirementstext" URL-hash anchor used in the tab-switcher
script) containing one or more <table class="sc_plangrid"> grids and one
<dl class="sc_footnotes"> block per table.

CONFIRMED LIVE STRUCTURE (Computer Engineering - BS, 2026-08-23):
container children in document order are: an intro <p>, then
(table, dl.sc_footnotes) pairs repeated (2 pairs on this page -- First Year
in one table, Second/Third/Fourth Year in the other), then a closing
<h2>Total Program Hours N</h2>. Each table's rows carry a `class` that
identifies their role:
  plangridyear   -- a year header row (e.g. "First Year"), one <td>
  plangridterm   -- a semester header row (e.g. "Fall"), or the semester's
                    own "Semester Credit Hours" label row
  even / odd     -- a normal data row: course code cell, title cell
                    (title text + a <sup> of comma-separated footnote
                    numbers, if any), credit-hours cell
  plangridsum    -- combined with even/odd: a semester subtotal row
  plangridtotal  -- combined with lastrow/odd: the table's own running
                    total row

A "Select one of the following:" row is itself a normal data row (no code
cell, the credit range lives in the hours cell) followed by 2+ data rows
with blank hours cells -- the alternatives. Rows with no course-code cell
and no "Select one of" phrasing at all (e.g. "Area elective", "Senior
design", "Engineering elective") are TAMU's freeform-elective equivalent
of SMU's freeformText condition -- footnoted, adviser-defined, no fixed
course. Inline "X or Y" phrasing inside a single code cell (e.g.
"MATH 251 or MATH 253") is a genuine two-course alternative, distinct
from "/"-joined cross-listings of the SAME course under two department
codes (e.g. "CSCE 222/ECEN 222") -- both are handled, see split_codes().

SHAPE GAPS VS. fetch_smu_requirements.py -- RESOLVED THIS PASS, DECISIONS
BELOW (see planning-docs session notes; not re-litigated here):

1. No Coursedog IDs exist for TAMU -- course_catalog.coursedog_group_id is
   null on every TAMU row (planning-docs/degree-planner-spec.md §8.4).
   SMU's options[].coursedog_group_ids has no TAMU equivalent, so this
   script emits options[].course_codes (plain code strings, e.g.
   "CHEM 107") instead -- a deliberately different field name so nothing
   downstream mistakes it for a Coursedog id. DECIDED: keep as-is.
   A future import_tamu_requirements.py must resolve these by joining
   requirement_group_option_courses against course_catalog.code, NOT
   course_catalog.coursedog_group_id -- the join key SMU's
   import_requirement_groups.py uses is structurally unavailable here.
2. No per-course footnote system exists in SMU's shape -- notes_html there
   is Coursedog's own per-RULE prose. TAMU's superscript footnotes are
   per-COURSE. This script emits options[].footnote_refs (list[int]) plus
   a top-level footnotes: {number: text} map. DECIDED: keep as-is.
   FOOTNOTES ARE DISPLAY-ONLY IN THIS PASS -- footnotes_enforced: false is
   stamped at the top level of the output on purpose. Footnote text is
   captured and associated with the rows/options that reference it, but
   is NOT parsed into machine-checkable satisfaction constraints (grade
   minimums, math-placement contingencies, Core Curriculum distribution
   rules). Confirmed live: footnotes 3 and 4 on this program's page are
   shared CourseLeaf boilerplate that names OTHER majors by code
   (BS-AREN, BS-BMEN, BS-CHEN, BS-MSEN, BS-PETE) alongside this one --
   mechanically applying footnote text as a constraint without a human
   verifying which clause actually governs THIS program would risk
   silently importing a different major's rule. Do not flip
   footnotes_enforced to true without that verification pass.
3. No source rule id exists for TAMU at all (no Coursedog, no equivalent
   backing system) -- see assign_rule_ids()'s synthesized tamu-rule-NNN
   identifiers, deliberately named `rule_id`/`parent_rule_id` rather than
   `coursedog_rule_id`/`parent_coursedog_rule_id` so nothing reads them as
   sourced from Coursedog. DECIDED: keep as-is, no change.
4. "source": "tamu_courseleaf" is stamped at the top level of the output
   (see main()) so a consumer handling both schools' JSON files can branch
   on provenance without inspecting field shapes. SMU's
   fetch_smu_requirements.py output has NO equivalent discriminator field
   today -- flagged as a separate, small follow-up ("source":
   "smu_coursedog") for that script, proposed but deliberately NOT applied
   in this pass without separate sign-off (SMU's live data file is out of
   scope for a TAMU-only change).

Dry-run is the default, matching fetch_smu_requirements.py. Use --write to
save JSON -- but see --out below: this script's OUTPUT_ROOT default
(data/catalog/tamu/) intentionally mirrors data/catalog/smu/'s convention
for a *future* run; the Stage-1 review pass this script was written for
must be run with an explicit --out pointing outside the repo's data
directory, since nothing here has been reviewed or approved yet.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag

CATALOG_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = CATALOG_ROOT / "tamu"

REQUEST_HEADERS = {
    "User-Agent": "GradusIQ-catalog-fetch/1.0 (academic-research)",
}

CATALOG_SITE = "https://catalog.tamu.edu"
CONTAINER_ID = "programrequirementstextcontainer"

# Splits "MATH 251 or MATH 253" -> ["MATH 251", "MATH 253"] (genuine
# alternatives). Cross-listings use "/" instead (e.g. "CSCE 222/ECEN 222")
# and are NOT split by this -- same course, kept as one code string.
INLINE_OR_RE = re.compile(r"\s+or\s+", re.IGNORECASE)

CREDIT_RANGE_RE = re.compile(r"^\s*([0-9.]+)(?:\s*-\s*([0-9.]+))?\s*$")


def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def cell_text(tag: Tag, exclude_sup: bool = False) -> str:
    """get_text(" ") so a <br/>-separated "or ENGL 104" continuation line
    doesn't run into the preceding text with no space (confirmed live: TAMU
    renders inline "or" alternatives as a second <div class="blockindent">
    line, not literal " or " text in the same text node). exclude_sup drops
    the footnote-marker <sup> from the text entirely, so a footnote number
    like "University Core Curriculum[3]" doesn't get read back as part of
    the label -- get_text() alone can't tell a footnote marker from real
    label text.
    """
    if exclude_sup:
        tag = BeautifulSoup(str(tag), "html.parser")
        for sup in tag.find_all("sup"):
            sup.decompose()
    return clean_text(tag.get_text(" ", strip=True))


def split_codes(code_cell_text: str) -> tuple[list[str], str]:
    """("MATH 251 or MATH 253", ...) -> (["MATH 251", "MATH 253"], "or")
    ("CSCE 222/ECEN 222", ...) -> (["CSCE 222/ECEN 222"], "and") -- a
    cross-listing is kept as one identity, not split, matching
    degree-planner-spec.md §10.1's slash-joined-identity handling for SMU.
    """
    text = clean_text(code_cell_text)
    if INLINE_OR_RE.search(text):
        return [clean_text(part) for part in INLINE_OR_RE.split(text)], "or"
    return [text], "and"


def parse_footnote_refs(sup: Tag | None) -> list[int]:
    if sup is None:
        return []
    text = clean_text(sup.get_text())
    refs: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if part.isdigit():
            refs.append(int(part))
    return refs


def parse_credit_cell(text: str) -> tuple[float | None, float | None, str]:
    """Returns (low, high, raw_text). Blank cell (choice-group alternative
    rows) -> (None, None, "").
    """
    text = clean_text(text)
    if not text:
        return None, None, text
    match = CREDIT_RANGE_RE.match(text)
    if not match:
        return None, None, text
    low = float(match.group(1))
    high = float(match.group(2)) if match.group(2) else low
    return low, high, text


def parse_footnotes(dl: Tag) -> dict[int, str]:
    footnotes: dict[int, str] = {}
    dts = dl.find_all("dt")
    dds = dl.find_all("dd")
    for dt, dd in zip(dts, dds):
        num_text = clean_text(dt.get_text())
        if num_text.isdigit():
            footnotes[int(num_text)] = clean_text(dd.get_text(" ", strip=True))
    return footnotes


def parse_row(tr: Tag) -> dict[str, Any] | None:
    """Normalize one <tr> from a plangrid table into a role-tagged dict, or
    None for a row this parser doesn't recognize (reported as a warning by
    the caller, not silently dropped).
    """
    classes = tr.get("class") or []
    header_cells = tr.find_all("th")
    cells = tr.find_all("td")

    if "plangridyear" in classes:
        return {"role": "year", "label": clean_text(header_cells[0].get_text())}

    if "plangridterm" in classes:
        # Header row, e.g. "Fall | Semester Credit Hours" -- th cells only.
        # First th is the semester label; a second th ("Semester Credit
        # Hours") is a column header, not data.
        return {"role": "semester", "label": clean_text(header_cells[0].get_text())}

    if "plangridtotal" in classes:
        label = clean_text(cells[-2].get_text()) if len(cells) >= 2 else ""
        low, high, raw = parse_credit_cell(cells[-1].get_text())
        return {"role": "total", "label": label, "low": low, "high": high, "raw": raw}

    if "plangridsum" in classes:
        label = clean_text(cells[-2].get_text()) if len(cells) >= 2 else ""
        low, high, raw = parse_credit_cell(cells[-1].get_text())
        return {"role": "subtotal", "label": label, "low": low, "high": high, "raw": raw}

    if len(cells) == 3:
        code_cell, title_cell, hours_cell = cells
        code_text = cell_text(code_cell)
        sup = title_cell.find("sup")
        title_text = cell_text(title_cell, exclude_sup=True)
        low, high, raw = parse_credit_cell(hours_cell.get_text())
        codes, logic = split_codes(code_text)
        return {
            "role": "course",
            "codes": codes,
            "logic": logic,
            "title": title_text,
            "footnote_refs": parse_footnote_refs(sup),
            "low": low,
            "high": high,
            "raw_hours": raw,
        }

    if len(cells) == 2:
        # "Select one of the following:" header row, or a choice-group
        # alternative row with a blank hours cell (2-cell rows without a
        # separate code cell aren't expected elsewhere; caller decides).
        label_cell, hours_cell = cells
        label_text = cell_text(label_cell, exclude_sup=True)
        sup = label_cell.find("sup")
        low, high, raw = parse_credit_cell(hours_cell.get_text())
        if label_text.lower().startswith("select one of the following"):
            return {
                "role": "choice_header",
                "footnote_refs": parse_footnote_refs(sup),
                "low": low,
                "high": high,
                "raw_hours": raw,
            }
        return {
            "role": "freeform",
            "label": label_text,
            "footnote_refs": parse_footnote_refs(sup),
            "low": low,
            "high": high,
            "raw_hours": raw,
        }

    return None


def build_semester_group(
    year_label: str, semester_label: str, rows: list[dict[str, Any]], warnings: list[str]
) -> dict[str, Any]:
    """rows are every "role" in (course, choice_header, freeform) belonging
    to one semester, in document order. Choice-group alternative rows
    (blank hours, immediately following a choice_header) are consumed as
    that header's own options, not emitted as standalone courses.
    """
    name_prefix = f"{year_label} — {semester_label}"
    required_options: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []

    i = 0
    option_index = 0
    while i < len(rows):
        row = rows[i]
        if row["role"] == "course":
            required_options.append(
                {
                    "option_index": option_index,
                    "logic": row["logic"],
                    "course_codes": row["codes"],
                    "footnote_refs": row["footnote_refs"],
                }
            )
            option_index += 1
            i += 1
            continue

        if row["role"] == "freeform":
            # SPECIAL CASE -- "High Impact Experience": confirmed live
            # (Fourth Year Fall), this 0-credit freeform placeholder row is
            # immediately followed by a blank-hours course row
            # ("CSCE 399 or ECEN 399") that is clearly meant to resolve it,
            # not an unrelated required course. Nested here as that group's
            # own option rather than left to fall through to the general
            # "course" branch below (which would otherwise misfile it into
            # this semester's separate "Required Courses" group, as it did
            # in the first pass of this script). This is a best-effort
            # structural inference, NOT a confirmed advisor-verified
            # relationship -- CourseLeaf's markup gives no explicit link
            # between the two rows beyond adjacency, so
            # modeling_confidence: "inferred" is stamped on the group for
            # human review, and this special-case is intentionally scoped
            # to this one label rather than generalized to every freeform
            # row, since adjacency alone is too weak a signal elsewhere
            # (e.g. "Senior design" / "Area elective" / "Engineering
            # elective" rows have no such following option row at all).
            is_high_impact = row["label"].strip().lower() == "high impact experience"
            resolving_option: dict[str, Any] | None = None
            if is_high_impact and i + 1 < len(rows) and rows[i + 1]["role"] == "course" and rows[i + 1]["low"] is None:
                next_row = rows[i + 1]
                resolving_option = {
                    "option_index": 0,
                    "logic": next_row["logic"],
                    "course_codes": next_row["codes"],
                    "footnote_refs": next_row["footnote_refs"],
                }

            group: dict[str, Any] = {
                "coursedog_rule_id": None,
                "parent_coursedog_rule_id": None,
                "name": f"{name_prefix} — {row['label']}",
                "group_type": "freeform",
                "n_required": None,
                "credit_hours_required": row["high"],
                "notes_html": None,
                "requires_manual_definition": True,
                "options": [],
                "footnote_refs": row["footnote_refs"],
            }
            if resolving_option is not None:
                group["group_type"] = "enumerated_at_least_n"
                group["n_required"] = 1
                group["requires_manual_definition"] = False
                group["options"] = [resolving_option]
                group["modeling_confidence"] = "inferred"
                children.append(group)
                i += 2
                continue

            children.append(group)
            i += 1
            continue

        if row["role"] == "choice_header":
            # An alternative within a choice block can itself be a freeform
            # (no-course-code) row -- confirmed live: First Year Spring's
            # choice is "CHEM 120" (a real course) OR "University Core
            # Curriculum" (adviser-defined, footnoted, no fixed course).
            # Both row roles are valid alternatives here, distinguished
            # from a *new* top-level freeform elective only by having a
            # blank hours cell (rows["low"] is None) right after the header.
            alt_rows = []
            j = i + 1
            while j < len(rows) and rows[j]["role"] in ("course", "freeform") and rows[j]["low"] is None:
                alt_rows.append(rows[j])
                j += 1
            if not alt_rows:
                warnings.append(
                    f"{name_prefix}: choice_header row with no following alternative rows -- skipped"
                )
                i += 1
                continue
            choice_options = []
            for idx, alt in enumerate(alt_rows):
                if alt["role"] == "course":
                    choice_options.append(
                        {
                            "option_index": idx,
                            "logic": alt["logic"],
                            "course_codes": alt["codes"],
                            "footnote_refs": alt["footnote_refs"],
                        }
                    )
                else:  # freeform alternative -- no fixed course, see comment above
                    choice_options.append(
                        {
                            "option_index": idx,
                            "logic": "manual",
                            "course_codes": [],
                            "freeform_label": alt["label"],
                            "footnote_refs": alt["footnote_refs"],
                        }
                    )
            children.append(
                {
                    "coursedog_rule_id": None,
                    "parent_coursedog_rule_id": None,
                    "name": f"{name_prefix} — Select one of the following",
                    "group_type": "enumerated_at_least_n",
                    "n_required": 1,
                    "credit_hours_required": row["high"],
                    "notes_html": None,
                    "requires_manual_definition": False,
                    "options": choice_options,
                    "footnote_refs": row["footnote_refs"],
                }
            )
            i = j
            continue

        warnings.append(f"{name_prefix}: unrecognized row role {row['role']!r} -- skipped")
        i += 1

    if required_options:
        children.insert(
            0,
            {
                "coursedog_rule_id": None,
                "parent_coursedog_rule_id": None,
                "name": f"{name_prefix} — Required Courses",
                "group_type": "enumerated_all",
                "n_required": None,
                "credit_hours_required": None,
                "notes_html": None,
                "requires_manual_definition": False,
                "options": required_options,
                "footnote_refs": [],
            },
        )

    return {
        "coursedog_rule_id": None,
        "parent_coursedog_rule_id": None,
        "name": name_prefix,
        "group_type": "compound_all",
        "n_required": None,
        "credit_hours_required": None,
        "notes_html": None,
        "requires_manual_definition": False,
        "options": [],
        "footnote_refs": [],
        "_children": children,
    }


def parse_plangrid_table(table: Tag, warnings: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Returns (list of year-level group dicts with nested "_children", a
    dict of {semester_label: {low, high}} subtotal figures for validation).
    """
    rows = [parse_row(tr) for tr in table.find_all("tr")]
    unrecognized = sum(1 for r in rows if r is None)
    if unrecognized:
        warnings.append(f"{unrecognized} unrecognized row(s) in table -- see role=None entries")

    years: list[dict[str, Any]] = []
    subtotals: dict[str, Any] = {}
    current_year: str | None = None
    current_semester: str | None = None
    current_rows: list[dict[str, Any]] = []
    semester_order: list[tuple[str, str]] = []
    semesters_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def flush_semester() -> None:
        if current_year is not None and current_semester is not None:
            key = (current_year, current_semester)
            semesters_by_key[key] = list(current_rows)
            semester_order.append(key)

    for row in rows:
        if row is None:
            continue
        if row["role"] == "year":
            flush_semester()
            current_year = row["label"]
            current_semester = None
            current_rows = []
        elif row["role"] == "semester":
            flush_semester()
            current_semester = row["label"]
            current_rows = []
        elif row["role"] == "subtotal":
            subtotals[f"{current_year} — {current_semester}"] = {"low": row["low"], "high": row["high"]}
        elif row["role"] == "total":
            subtotals["__table_total__"] = {"low": row["low"], "high": row["high"]}
        else:
            current_rows.append(row)
    flush_semester()

    years_seen: dict[str, dict[str, Any]] = {}
    for (year_label, semester_label) in semester_order:
        semester_rows = semesters_by_key[(year_label, semester_label)]
        semester_group = build_semester_group(year_label, semester_label, semester_rows, warnings)
        year_group = years_seen.get(year_label)
        if year_group is None:
            year_group = {
                "coursedog_rule_id": None,
                "parent_coursedog_rule_id": None,
                "name": year_label,
                "group_type": "compound_all",
                "n_required": None,
                "credit_hours_required": None,
                "notes_html": None,
                "requires_manual_definition": False,
                "options": [],
                "footnote_refs": [],
                "_children": [],
            }
            years_seen[year_label] = year_group
            years.append(year_group)
        year_group["_children"].append(semester_group)

    return years, subtotals


def assign_rule_ids(years: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten the year -> semester -> (required/choice/freeform) tree into
    the flat groups[] list fetch_smu_requirements.py's shape expects,
    synthesizing a stable-within-this-file coursedog_rule_id equivalent
    (there is no source rule id -- TAMU has no Coursedog backing at all).
    Named `rule_id`, not `coursedog_rule_id`, to avoid implying a Coursedog
    origin that doesn't exist for this school.
    """
    flat: list[dict[str, Any]] = []
    counter = [0]

    def next_id() -> str:
        counter[0] += 1
        return f"tamu-rule-{counter[0]:03d}"

    def walk(node: dict[str, Any], parent_id: str | None) -> None:
        node_id = next_id()
        children = node.pop("_children", [])
        node["rule_id"] = node_id
        node["parent_rule_id"] = parent_id
        flat.append(node)
        for child in children:
            walk(child, node_id)

    for year in years:
        walk(year, None)

    return flat


def fetch_page(url: str, cache_path: Path | None) -> str:
    if cache_path and cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
    response.raise_for_status()
    html = response.text
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(html, encoding="utf-8")
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=f"{CATALOG_SITE}/undergraduate/engineering/electrical-computer/computer-engineering-bs/",
        help="canonical CourseLeaf program page to fetch",
    )
    parser.add_argument("--program-code", default="ECEN-CPEN-BS")
    parser.add_argument("--program-name", default="Computer Engineering")
    parser.add_argument("--catalog-year", default="2026-2027")
    parser.add_argument("--raw-cache", type=Path, default=None, help="local HTML cache path")
    parser.add_argument("--write", action="store_true", help=f"save normalized JSON under {OUTPUT_ROOT}")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="explicit output path for --write; required until this script's shape is reviewed "
        "(the OUTPUT_ROOT default is for a later, approved run)",
    )
    args = parser.parse_args()

    print(f"Mode: {'write' if args.write else 'dry-run (nothing saved)'}")
    print(f"Source: {args.url}")
    print()

    html = fetch_page(args.url, args.raw_cache)
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id=CONTAINER_ID)
    if container is None:
        print(f"ERROR: no element with id={CONTAINER_ID!r} found on the page", file=sys.stderr)
        return 1

    tables = container.find_all("table", class_="sc_plangrid")
    footnote_dls = container.find_all("dl", class_="sc_footnotes")
    print(f"plangrid tables found: {len(tables)}")
    print(f"footnote blocks found: {len(footnote_dls)}")

    warnings: list[str] = []
    all_years: list[dict[str, Any]] = []
    validation_subtotals: dict[str, Any] = {}
    for table_index, table in enumerate(tables):
        years, subtotals = parse_plangrid_table(table, warnings)
        all_years.extend(years)
        for key, value in subtotals.items():
            out_key = f"table{table_index}: {key}" if key == "__table_total__" else key
            validation_subtotals[out_key] = value

    footnotes: dict[int, str] = {}
    for dl in footnote_dls:
        footnotes.update(parse_footnotes(dl))

    groups = assign_rule_ids(all_years)

    print(f"\nYear-level groups: {len(all_years)}")
    print(f"Total flattened groups: {len(groups)}")
    print(f"Footnotes captured: {sorted(footnotes)}")
    print(f"\nWarnings: {len(warnings)}")
    for warning in warnings:
        print(f"  {warning}")

    print("\nSemester subtotals parsed:")
    for label, value in validation_subtotals.items():
        print(f"  {label}: {value}")

    output = {
        # Discriminator so a consumer handling both schools' JSON files can
        # branch on provenance without inspecting field shapes -- see
        # module docstring point 4. SMU's own output has no equivalent
        # field yet; that's a proposed follow-up, not applied here.
        "source": "tamu_courseleaf",
        "program": {
            "code": args.program_code,
            "name": args.program_name,
            "degree_designation": "BS - Bachelor of Science",
            "source_url": args.url,
        },
        "catalog_year": args.catalog_year,
        # Display-only in this pass -- see module docstring point 2 for why
        # (footnotes 3/4 are confirmed shared boilerplate naming other
        # majors). Never consumed as a satisfaction constraint while false.
        "footnotes_enforced": False,
        "footnotes": {str(k): v for k, v in sorted(footnotes.items())},
        "groups": groups,
    }

    if not args.write:
        print("\nDRY RUN — nothing written. Re-run with --write --out <path> to save.")
        return 0

    if not args.out:
        print(
            "\nERROR: --write requires an explicit --out path for this Stage-1, "
            "not-yet-reviewed script (refusing to default into data/catalog/tamu/).",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
