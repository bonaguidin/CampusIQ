#!/usr/bin/env python3
"""
TAMU Course Catalog Scraper — Full catalog, all levels.
Fetches every course listed under each department prefix at catalog.tamu.edu.
Business file merges all 7 Mays Business School department prefixes.
"""

import json
import re
import time
import subprocess
from html import unescape
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = PROJECT_ROOT / "data" / "catalog"
OUTPUT_DIR = CATALOG_DIR

# Each entry in DEPARTMENTS produces one output file.
# "sources" is a list of (prefix, department_label, url) tuples —
# multiple sources are merged into a single file (used for Business).
DEPARTMENTS = [
    {
        "file": "business.json",
        "sources": [
            ("BUSN", "Mays Business School",              "https://catalog.tamu.edu/undergraduate/course-descriptions/busn/"),
            ("ACCT", "Accounting",                        "https://catalog.tamu.edu/undergraduate/course-descriptions/acct/"),
            ("FINC", "Finance",                           "https://catalog.tamu.edu/undergraduate/course-descriptions/finc/"),
            ("MGMT", "Management",                        "https://catalog.tamu.edu/undergraduate/course-descriptions/mgmt/"),
            ("MKTG", "Marketing",                         "https://catalog.tamu.edu/undergraduate/course-descriptions/mktg/"),
            ("ISTM", "Information & Operations Mgmt (ISTM)", "https://catalog.tamu.edu/undergraduate/course-descriptions/istm/"),
            ("SCMT", "Supply Chain Management",           "https://catalog.tamu.edu/undergraduate/course-descriptions/scmt/"),
        ],
    },
    {
        "file": "aerospace_engineering.json",
        "sources": [
            ("AERO", "Aerospace Engineering", "https://catalog.tamu.edu/undergraduate/course-descriptions/aero/"),
        ],
    },
    {
        "file": "computer_engineering.json",
        "sources": [
            ("ECEN", "Electrical & Computer Engineering (ECEN)", "https://catalog.tamu.edu/undergraduate/course-descriptions/ecen/"),
        ],
    },
    {
        "file": "psychology.json",
        "sources": [
            ("PBSI", "Psychology & Brain Sciences", "https://catalog.tamu.edu/undergraduate/course-descriptions/pbsi/"),
        ],
    },
    {
        "file": "biology.json",
        "sources": [
            ("BIOL", "Biology", "https://catalog.tamu.edu/undergraduate/course-descriptions/biol/"),
        ],
    },
]

UCC_URL = "https://catalog.tamu.edu/undergraduate/general-information/university-core-curriculum/"


def fetch(url: str) -> str:
    result = subprocess.run(
        ["curl", "-s", "--max-time", "30", "-A",
         "Mozilla/5.0 (compatible; TAMU-catalog-scraper/1.0; academic-research)",
         url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed for {url}: {result.stderr}")
    return result.stdout


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_department_courses(html: str, department: str) -> list:
    """
    Parse all course blocks from a department catalog page, all levels.
    Returns list of course dicts.
    """
    courses = []
    blocks = re.split(r'<div class="courseblock">', html)
    blocks = blocks[1:]

    for block in blocks:
        title_match = re.search(
            r'<h2[^>]*class="courseblocktitle"[^>]*>(.*?)</h2>',
            block, re.DOTALL
        )
        if not title_match:
            continue

        raw_title = strip_tags(title_match.group(1))
        code_match = re.match(r'^([A-Z]+\s+\d+)\s+(.+)$', raw_title)
        if not code_match:
            continue

        code = code_match.group(1).strip()
        title = code_match.group(2).strip()

        desc_match = re.search(
            r'<p[^>]*class="courseblockdesc"[^>]*>(.*?)</p>',
            block, re.DOTALL
        )
        raw_desc_html = desc_match.group(1) if desc_match else ""

        # Credit hours
        credits = None
        hours_match = re.search(
            r'<span[^>]*class="hours"[^>]*>.*?<strong>(.*?)</strong>',
            raw_desc_html, re.DOTALL
        )
        if hours_match:
            hours_text = strip_tags(hours_match.group(1))
            range_match = re.search(r'Credits?\s+(\d+)\s+to\s+(\d+)', hours_text, re.IGNORECASE)
            if range_match:
                lo, hi = int(range_match.group(1)), int(range_match.group(2))
                credits = f"{lo}-{hi}"
            else:
                credit_match = re.search(r'Credits?\s+([\d.]+)', hours_text, re.IGNORECASE)
                if credit_match:
                    try:
                        credits = float(credit_match.group(1))
                        if credits == int(credits):
                            credits = int(credits)
                    except ValueError:
                        pass

        desc_no_hours = re.sub(
            r'<span[^>]*class="hours"[^>]*>.*?</span>', '', raw_desc_html, flags=re.DOTALL
        )

        prereq_raw = ""
        prereq_match = re.search(
            r'<strong>\s*Prerequisites?:?\s*</strong>(.*?)(?:<br|$)',
            desc_no_hours, re.DOTALL | re.IGNORECASE
        )
        if prereq_match:
            prereq_raw = strip_tags(prereq_match.group(1))

        desc_text = re.sub(
            r'<strong>\s*Prerequisites?:?\s*</strong>.*',
            '', desc_no_hours, flags=re.DOTALL | re.IGNORECASE
        )
        description = strip_tags(desc_text).strip(". ").strip()

        courses.append({
            "code": code,
            "title": title,
            "credit_hours": credits,
            "description": description,
            "prerequisites": prereq_raw if prereq_raw else None,
            "department": department,
        })

    return courses


def parse_ucc(html: str) -> dict:
    content_start = html.find('<a id="communication"')
    if content_start == -1:
        content_start = html.find('sc_courselist')
    content = html[content_start:]

    areas_in_order = []
    for m in re.finditer(r'<a id="([a-z][^"]*)"[^>]*></a>([^<\n]+)', content):
        area_id = m.group(1)
        area_name_raw = strip_tags(m.group(2)).strip()
        area_name = re.sub(r'\s*[-–—]+\s*\d+\s*SCH.*$', '', area_name_raw, flags=re.IGNORECASE).strip()
        if area_name:
            areas_in_order.append((m.start(), area_id, area_name))

    result = {}
    for i, (pos, area_id, area_name) in enumerate(areas_in_order):
        end = areas_in_order[i + 1][0] if i + 1 < len(areas_in_order) else len(content)
        section_html = content[pos:end]

        courses = []
        row_pattern = re.compile(
            r'<tr[^>]*class="[^"]*(?:even|odd)[^"]*"[^>]*>(.*?)</tr>', re.DOTALL
        )
        for row_m in row_pattern.finditer(section_html):
            row_html = row_m.group(1)
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
            if len(cells) < 2:
                continue
            code = strip_tags(cells[0]).strip()
            title = strip_tags(cells[1]).strip()
            hours = strip_tags(cells[2]).strip() if len(cells) > 2 else None
            if not code or not re.match(r'^[A-Z]', code):
                continue
            try:
                credit_hours = float(hours) if hours else None
                if credit_hours and credit_hours == int(credit_hours):
                    credit_hours = int(credit_hours)
            except (ValueError, TypeError):
                credit_hours = None
            courses.append({
                "code": code,
                "title": title,
                "credit_hours": credit_hours,
                "description": None,
                "prerequisites": None,
                "department": f"UCC - {area_name}",
            })

        if courses:
            result[area_name] = courses

    return result


def level_breakdown(courses: list) -> dict:
    buckets = {"100s": 0, "200s": 0, "300s": 0, "400s": 0, "500s+": 0}
    for c in courses:
        m = re.search(r'\d+', c.get("code", ""))
        if not m:
            continue
        n = int(m.group())
        if n < 200:
            buckets["100s"] += 1
        elif n < 300:
            buckets["200s"] += 1
        elif n < 400:
            buckets["300s"] += 1
        elif n < 500:
            buckets["400s"] += 1
        else:
            buckets["500s+"] += 1
    return {k: v for k, v in buckets.items() if v > 0}


def main():
    import os
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for dept in DEPARTMENTS:
        all_courses = []
        for prefix, dept_label, url in dept["sources"]:
            print(f"  Fetching {prefix} ({dept_label}) ...", flush=True)
            html = fetch(url)
            courses = parse_department_courses(html, dept_label)
            print(f"    -> {len(courses)} courses", flush=True)
            all_courses.extend(courses)
            time.sleep(2)

        out_path = f"{OUTPUT_DIR}/{dept['file']}"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_courses, f, indent=2, ensure_ascii=False)

        breakdown = level_breakdown(all_courses)
        print(f"  Saved {len(all_courses)} total to {dept['file']} — {breakdown}\n", flush=True)

    # UCC (unchanged)
    print("Fetching University Core Curriculum ...", flush=True)
    html = fetch(UCC_URL)
    ucc_data = parse_ucc(html)
    all_ucc = []
    for courses in ucc_data.values():
        all_ucc.extend(courses)

    ucc_output = {
        "metadata": {
            "source": UCC_URL,
            "total_courses": len(all_ucc),
            "areas": list(ucc_data.keys()),
        },
        "by_area": ucc_data,
        "courses": all_ucc,
    }
    out_path = f"{OUTPUT_DIR}/ucc.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ucc_output, f, indent=2, ensure_ascii=False)
    print(f"  -> {len(all_ucc)} UCC courses across {len(ucc_data)} areas saved to ucc.json")

    print("\nDone.")


if __name__ == "__main__":
    main()
