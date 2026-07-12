# TAMU Catalog Schema Contract

## Purpose

This document defines the official TAMU catalog JSON contract used by Campus IQ / CareerOS.

The schema supports academic foundation data for future course recommendation, study planning, and student profile reasoning. It is data foundation only. It does not implement AI recommendation logic, FIT/GAP/SHIFT features, career prompts, or student-facing planning behavior.

## Catalog Storage Location

Catalog files live under `data/catalog/`.

Each catalog file is a top-level JSON array of course objects. Files are grouped by existing domain folders, such as:

- `data/catalog/arts_and_sciences/`
- `data/catalog/business/`
- `data/catalog/education_human_development/`
- `data/catalog/engineering/`
- `data/catalog/government_public_service/`

Do not create new top-level catalog folders unless explicitly approved.

## Required Course Fields

| Field | Type | Example | Category | Description |
| --- | --- | --- | --- | --- |
| `code` | string | `"CSCE 120"` | source-provided | Official subject prefix and course number. |
| `title` | string | `"Program Design and Concepts"` | source-provided | Official course title. |
| `credit_hours` | number or string | `3`, `"0-6"` | source-provided | Official credit value. Fixed credits are numbers; variable credits are range strings. Do not rename to `credits`. |
| `description` | string | `"Extension of prior programming knowledge..."` | source-provided | Official course description text, preserving catalog meaning. |
| `prerequisites` | string or null | `"Prerequisite: Grade of C or better in CSCE 110."` | source-provided | Original prerequisite/corequisite/cross-listing text when present; `null` when no text is listed. |
| `department` | string | `"Computer Science and Engineering"` | source-provided/curated | Department or subject label used by the local catalog file. |
| `prefix` | string | `"CSCE"` | derived | Parsed subject prefix from `code`. |
| `number` | string | `"120"` | derived | Parsed course number from `code`. Stored as a string to preserve suffixes if present. |
| `course_level` | number or null | `100` | derived | Derived from the first digit of `number`: `100`, `200`, `300`, `400`, or `null` if not parseable. |
| `credit_min` | number | `3` | normalized | Minimum credit value derived from `credit_hours`. |
| `credit_max` | number | `6` | normalized | Maximum credit value derived from `credit_hours`. |
| `is_variable_credit` | boolean | `true` | normalized | `true` when `credit_hours` is a range string such as `"0-6"`; otherwise `false`. |
| `ucc_attributes` | array of strings | `["Life and Physical Sciences"]` | normalized | Normalized University Core Curriculum attributes. Empty array when none are listed. |
| `tccns` | array of strings | `["GOVT 2305"]` | normalized | Texas Common Course Numbering System identifiers extracted from the beginning of the description when present. |
| `cross_listings` | array of strings | `["ECEN 222"]` | normalized | Course codes extracted from catalog cross-listing text. Empty array when none are listed. |
| `repeatability` | string or null | `"May be repeated for credit."` | normalized | Repeatability sentence extracted from description or prerequisite text, or `null` if none is present. |
| `campuses` | array of strings | `["Galveston", "Qatar"]` | normalized | Campus mentions extracted from description or prerequisite text. Empty array when none are present. |
| `prerequisite_courses` | array of strings | `["CSCE 110", "MATH 151"]` | normalized | Course codes extracted from the original `prerequisites` text. Empty array when none are present. |
| `restrictions` | array of strings | `["junior or senior classification"]` | normalized | Non-course requirements extracted from prerequisites, such as classification, approval, major-only, or grade requirements. |
| `source_url` | string | `"https://catalog.tamu.edu/undergraduate/course-descriptions/csce/"` | traceability metadata | Official TAMU undergraduate course-description subject page for the course prefix. |
| `catalog_year` | string | `"2026-2027"` | traceability metadata | TAMU catalog edition used for the course data. |
| `source_last_checked` | string | `"2026-06-20"` | traceability metadata | Date the source page was last checked, formatted as `YYYY-MM-DD`. |

## Optional / Legacy Fields

`satisfies_ucc` is an optional legacy/source field. It may appear when a course had a source-provided University Core Curriculum attribute before normalization.

Do not delete `satisfies_ucc` if present. The normalized field used going forward is `ucc_attributes`, which is always an array.

## Credit Hour Rules

Fixed-credit courses store `credit_hours` as a number:

```json
{
  "credit_hours": 3,
  "credit_min": 3,
  "credit_max": 3,
  "is_variable_credit": false
}
```

Variable-credit courses store `credit_hours` as a range string:

```json
{
  "credit_hours": "0-6",
  "credit_min": 0,
  "credit_max": 6,
  "is_variable_credit": true
}
```

`credit_min` and `credit_max` must be valid numbers, and `credit_min` must be less than or equal to `credit_max`.

## Prerequisite and Restriction Rules

The original `prerequisites` text is preserved exactly enough to retain source meaning. It may contain prerequisites, corequisites, cross-listings, grade requirements, classification rules, approval requirements, major restrictions, or campus notes.

`prerequisite_courses` extracts course codes only, such as `CSCE 120`, `MATH 151`, or `POLS 206`.

`restrictions` extracts non-course requirements, including:

- classification requirements, such as `junior or senior classification`
- approval requirements, such as `approval of instructor`
- major-only requirements, such as `Computer Science majors only`
- grade requirements, such as `grade of C or better`

If no prerequisite courses or restrictions are present, use empty arrays.

## Source Traceability Rules

Every course must include:

- `source_url`
- `catalog_year`
- `source_last_checked`

Current `catalog_year` is `2026-2027`.

`source_url` must point to the official TAMU undergraduate course-description subject page:

```text
https://catalog.tamu.edu/undergraduate/course-descriptions/<prefix>/
```

`source_last_checked` must use `YYYY-MM-DD`.

## Validation Rules

`data/catalog/validate_catalog.py` checks that:

- required base, normalized, and source fields exist
- `code` is parseable into `prefix` and `number`
- parsed `prefix` and `number` match the stored fields
- `credit_min` and `credit_max` are valid numbers
- `credit_min <= credit_max`
- array fields are arrays
- there are no duplicate course codes within a department file
- `title` and `description` are non-empty
- `source_url` starts with `https://catalog.tamu.edu/undergraduate/course-descriptions/`
- `source_last_checked` is valid `YYYY-MM-DD`

Run validation with:

```bash
python3 data/catalog/validate_catalog.py
```

## Expansion Process

Use this safe process for adding more TAMU subjects:

1. Run `python3 data/catalog/audit_catalog_expansion.py`.
2. Select a small approved batch.
3. Scrape only approved subjects.
4. Normalize course and source fields.
5. Run `python3 data/catalog/validate_catalog.py`.
6. Update `data/reference/catalog_expansion_audit.md`.
7. Commit locally.
8. Do not push unless explicitly asked.

Do not scrape all TAMU departments automatically. Do not add unapproved subjects.

## Current Coverage Snapshot

- Catalog files: 19
- Total courses: 1,374
- Approved expansion batch 1 subjects: `CSCE`, `ECON`, `MEEN`, `ISEN`, `BMEN`
- Validation status: 0 errors
- Current local commits:
  - `46f589c Add TAMU catalog source traceability fields`
  - `0aefb0e Add approved TAMU catalog expansion batch 1`

## Example Course Object

```json
{
  "code": "CSCE 120",
  "title": "Program Design and Concepts",
  "credit_hours": 3,
  "description": "Extension of prior programming knowledge and creation of computer programs that solve problems; application of computational thinking to enhance problem solving.",
  "prerequisites": "Prerequisite: Grade of C or better in CSCE 110, CSCE 111, or CSCE 206.",
  "department": "Computer Science and Engineering",
  "prefix": "CSCE",
  "number": "120",
  "course_level": 100,
  "credit_min": 3,
  "credit_max": 3,
  "is_variable_credit": false,
  "ucc_attributes": [],
  "tccns": [],
  "cross_listings": [],
  "repeatability": null,
  "campuses": [],
  "prerequisite_courses": [
    "CSCE 110",
    "CSCE 111",
    "CSCE 206"
  ],
  "restrictions": [
    "Grade of C or better"
  ],
  "source_url": "https://catalog.tamu.edu/undergraduate/course-descriptions/csce/",
  "catalog_year": "2026-2027",
  "source_last_checked": "2026-06-20"
}
```
