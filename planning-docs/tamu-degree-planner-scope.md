# TAMU Degree Planner — Scoping Document

**Status:** SCOPING PASS — not a build spec. No code, no schema, no build prompt written yet. Do not commit without Deepak's review.
**Purpose:** Establish what TAMU's catalog platform actually is and what data it exposes, as a handoff point for a future TAMU scraper build prompt. This is the TAMU-side counterpart to [degree-planner-spec.md](degree-planner-spec.md)'s SMU work — see that doc's §5 for why TAMU was deferred as a parallel track.

---

## 1. Platform

TAMU's catalog (`catalog.tamu.edu`) runs on **CourseLeaf**, not Coursedog (SMU's platform). Confirmed via the version tag "23.2.3" and CourseLeaf branding visible on the course-search page.

No usable AJAX/JSON API was confirmed or investigated further — deprioritized, since static HTML scraping is confirmed viable (§2) and simpler than reverse-engineering an undocumented endpoint.

---

## 2. Data confirmed available

Verified visually against live pages, 2026-08-23:

- Every undergraduate program has its own catalog page with a "Program Requirements" section (anchor: `#programrequirementstext`)
- Requirement tables are structured HTML: Year (First Year, etc.) → Semester (Fall/Spring) → rows of Course Code / Title / Credit Hours, with semester subtotals and a running Total Semester Credit Hours
- Choice groups appear as "Select one of the following:" rows with a credit-hour range shown (e.g. "3-4") — maps directly onto the existing three-state satisfaction model (SATISFIED/IN_PROGRESS/NOT_STARTED) already built for SMU (see [degree-planner-spec.md](degree-planner-spec.md) §9)
- Numbered footnotes carry real constraint semantics beyond decoration: grade-C-or-better requirements, math-placement-exam contingencies affecting starting course, and University Core Curriculum distribution rules (e.g. "3 hours must be from creative arts"). A scraper must capture and structure these, not just the course list — this is real scope, not a nice-to-have.
- Format assumed consistent across all TAMU undergraduate programs, given CourseLeaf's templated structure — verified directly on Computer Engineering - BS's freshman year only; not independently re-verified program-by-program, but a reasonable assumption for a templated catalog platform.

---

## 3. Resolved: Computer Engineering - BS's two URLs

Computer Engineering - BS is listed under two departments (Computer Science and Engineering, and Electrical and Computer Engineering), each with its own URL. Verified directly (screenshots, freshman year, both URLs): course-for-course, credit-hour-for-credit-hour identical, same footnote markers.

This is one degree with two navigation paths, not two different curricula — no reconciliation needed. Pick one canonical URL for scraping (recommend the Electrical and Computer Engineering path, matching how the department is referenced elsewhere, but either works).

---

## 4. Comparison to SMU's build

| | SMU (built) | TAMU (scoped) |
|---|---|---|
| Platform | Coursedog | CourseLeaf |
| Access | Unauthenticated JSON API | Static HTML, structured tables |
| Requirement structure | JSON, hand-modeled | HTML tables, needs parsing + footnote extraction |
| Real-time offerings | Mocked (no live API) | Behind Howdy (authenticated) — same limitation, still mocked/absent for v1 |
| Choice/elective groups | Present, modeled | Present, same shape ("Select one of the following" + credit range) |

---

## 5. Still open before a build prompt

- Confirm sophomore/junior/senior years follow the same table structure (not yet directly verified — reasonable to assume, low risk, but worth a spot-check before writing the parser)
- Footnote-to-constraint mapping needs a defined schema — propose extending the existing requirement model with a `constraints: list[str]` or similar field rather than inventing new machinery
- No decision yet on refresh cadence (SMU's build was effectively a one-time load — propose matching that for v1, since catalogs update yearly)

---

## 6. Recommended first degree

**Computer Engineering - BS** — matches the screenshot that motivated this scoping pass, and its complexity (choice groups, footnoted constraints, freshman year shared across most engineering majors) looks comparable to SMU CS-BS's scope, making it a fair first target.

---

## 7. Suggested next step (not started)

A Claude Code build prompt for a TAMU scraper: static HTML fetch (this would run in Claude Code's own environment if `catalog.tamu.edu` becomes network-reachable there, otherwise needs to run from an unrestricted environment) + table parser + footnote-constraint extractor, targeting the same JSON shape `requirement_satisfaction.py` already consumes for SMU.

Not scoped in detail here — this doc is the handoff point.
