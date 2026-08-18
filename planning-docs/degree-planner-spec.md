# Degree Planner — Pre-Build Specification

**Status:** DRAFT — awaiting Deepak's review before any build prompt is written.
**Feature working name:** Degree Planner (sits directly under Course Discovery)

---

## 1. What this feature actually is

Course Discovery today answers "what courses build the skills my target role needs" — role-driven, GAP-sourced, no awareness of degree requirements or scheduling constraints.

This feature adds a second, orthogonal layer underneath it:

- **Requirement skeleton** (new): what does this student's major actually require to graduate, and what's already satisfied by their transcript
- **Prerequisite-aware scheduling** (new): given what's left to satisfy, in what order *can* it be taken, and where does it fit against a per-term credit-hour load
- **Role-driven electives** (existing, reused): wherever the skeleton has open elective room, prefer GAP-recommended courses that also build target-role skills

The three layers are meant to cooperate, not run as separate systems. Course Discovery doesn't change — this feature wraps around it.

---

## 2. Confirmed scope decisions (from planning conversation — do not re-litigate)

| Decision | Answer |
|---|---|
| Planner type | Requirement-driven (real degree-completion plan), not role-driven-only |
| First school to build against | **SMU Computer Science, B.S.** — confirmed structured requirements data exists, matches existing Coursedog integration |
| TAMU | Parallel track, not a blocker — see §5 |
| Course-load constraint | Must respect prereqs AND a per-term credit-hour cap when placing recommended courses |
| Scheduling logic | Deterministic (topological sort + bin-packing), **not LLM-driven** — same rationale as the FIT/SHIFT grounding fix: a hallucinated prereq ordering is a worse failure mode than a hallucinated skill match |

---

## 3. Data sources — confirmed status

### 3.1 SMU degree requirements (confirmed live, this session)
- Source: `catalog.smu.edu/programs/CS-BS/requirements-*` — Coursedog-backed, same vendor as existing SMU course-catalog integration
- Shape: named requirement buckets (Lyle EDGE Curriculum, Mathematics and Science, Computer Science Core — 33 Credit Hours, Technical Electives — 9 Credit Hours, Engineering Leadership — 6 Credit Hours, Advanced Major Electives — 3-5 Credit Hours), each listing required or "choose N of" course groups
- **Resolved:** requirement groups reference courses via `courseGroupId` (e.g. `0045691`), which is present in every record the existing `courses/search` Coursedog endpoint already returns — it's just absent from `fetch_smu_catalog.py`'s `COLUMNS` list today and discarded, not missing from the source. Confirmed exact match against the requirements endpoint's course-reference IDs on 69 of 73 live CS-BS requirement references (94.5%); the remaining 4 are likely inactive/renumbered course records outside the script's current active-status filter — a minor residual gap, not a scheme mismatch. No new endpoint or auth needed — same `programs/search/$filters` and `courses/search/$filters` Coursedog "cm" surfaces, same unauthenticated Referer/Origin headers already in use.

### 3.2 TAMU degree requirements (confirmed live, this session)
- Source: `catalog.tamu.edu/undergraduate/.../bs/` — CourseLeaf platform (not Coursedog, not Acalog/DIGARC as initially assumed)
- Shape: server-rendered `<table class="sc_plangrid">` — semester-by-semester course codes, titles, credit hours, no separate API
- **Not yet built:** no ingestion exists for this today. Predictable URL pattern per program (`/undergraduate/<college>/<dept>/<program-slug>/`), plain scrape, no auth needed.

### 3.3 Prerequisite data (confirmed live, this session — this was the main open question)
- **Already exists, already populated, already stored, currently unused by any feature:**
  `course_catalog.prerequisites` (text, nullable), populated for both TAMU and SMU courses today.
- **TAMU origin:** CourseLeaf scrape (`data/catalog/scrape_approved_subjects.py` + `normalize_catalog.py`) — pulled from course description text, not the robots.txt-disallowed `/search/` path. Confirmed via live query against 5 CSCE courses (221, 312, 313, 314, 315) — all populated with real prerequisite chains.
- **SMU origin:** Coursedog's own structured `requisites` field is confirmed **empty on every sampled record** — a dead end. SMU's prereq text is instead parsed out of the course description blob via sentence-splitting (`split_description()`), matching sentences like "Prerequisite:", "Corequisite:", "Restricted to...".
- **Format (both schools):** free-text prose, human-readable course codes (e.g. "CSCE 221", "CEE 2321"), corequisite phrasing mixed into the same field rather than a separate column. Example:
  > `CSCE 221`: "Prerequisites: Grade C or better in CSCE 120 or CSCE 121; grade of C or better in CSCE 222/ECEN 222 or ECEN 222/CSCE 222, or concurrent enrollment."

  This single example contains a nested OR inside an AND, plus a concurrent-enrollment (corequisite) exception — representative of the real complexity, not a worst case.

### 3.4 Coverage breadth — checked, mixed result

Full-catalog audit (not just the 5 CSCE courses):

| Scope | Total | Populated | % Populated |
|---|---|---|---|
| SMU full catalog | 3,249 | 1,598 | 49.2% |
| TAMU CSCE only | 71 | 66 | 93.0% |
| TAMU full catalog | 2,565 | 2,312 | 90.1% |

**TAMU is solid.** 90% populated overall, 95%+ at the 300/400 level — the intro-course-gaps-are-expected pattern holds throughout.

**SMU's upper-level null rate is mostly genuine, confirmed via live spot-check.** Cross-referenced 10 null-prerequisite upper-level courses directly against SMU's live Coursedog feed (the same endpoint `fetch_smu_catalog.py` already calls) — stored `description` text matched the live source verbatim in every case, and `requisites` is empty at the source itself, not just downstream. Full breakdown across all 989 null upper-level rows:

| Bucket | Rate | What it means |
|---|---|---|
| Scraper gap | 0% | None found — fetch script isn't dropping anything the source has |
| Parser gap | ~4.9% (48 rows) | `split_description()`'s regex misses permission/approval phrasing not anchored to its trigger words ("prerequisite/corequisite/restricted to..."). Concentrated almost entirely in independent-study/special-topics course templates (CS 41xx-49xx, ARHS 4302, ENGR 3390/4390-family) — a small, repeated pattern, not scattered noise. |
| Genuine gap | ~95.1% (941 rows) | Upper-level humanities/social-science electives (Art History, World Languages, Political Science, History, Anthropology, Music) that legitimately carry no prerequisite in SMU's own catalog. STEM departments have very few nulls outside the one parser-gap template above. |

This removes the main risk to SMU-first sequencing (§5) — the null rate isn't hiding missing scraper data.

- **SMU internal-ID → course-code mapping** for the degree-requirements endpoint (§3.1 open gap above) — still unconfirmed.
- **Term-offering pattern** (fall-only / spring-only / alternating-year courses) — not investigated at all this round. A required course scheduled into a term it doesn't run in would silently produce a wrong plan.

---

## 4. The core engineering problem — prerequisite parsing

This is now the long pole, not data acquisition. `prerequisites` is unstructured prose with real logical complexity:

- **AND / OR nesting**: "Grade C or better in CSCE 120 or CSCE 121; grade of C or better in CSCE 222/ECEN 222..."
- **Cross-listed courses**: "CSCE 222/ECEN 222 or ECEN 222/CSCE 222" — same course, two department codes, redundantly listed both orders
- **Concurrent enrollment / corequisites** embedded in the same sentence, distinguished only by phrasing ("or concurrent enrollment") rather than a separate field
- **Grade minimums** ("Grade of C or better") — not currently modeled anywhere; the planner needs to at least be aware a grade floor exists, even if it doesn't enforce it in v1

**Recommendation:** treat this as its own parsing/normalization pass, run once per course record (not per-student, per-request) and cached — same "never call live per request" architecture principle already established for job-posting data in the backlog. Output should be a structured intermediate form (e.g. `{requires_all: [...], requires_any: [...], coreq_allowed: [...], grade_min: "C"}`) that the scheduler consumes, rather than re-parsing prose at scheduling time.

**Confirmed at full-catalog scale (not just CSCE):**
- **Field-overloading.** Both schools store non-prerequisite content in the same `prerequisites` column: SMU has ~20 rows that are pure program/major restrictions with no prereq logic at all ("Restricted to Lyle seniors.", "Restricted to NexPoint Tower Scholars."). TAMU departments outside CSCE frequently append unrelated trailing clauses ("also taught at Galveston and Qatar campuses.", "Replaces CHEM 323 in previous catalogs.") onto otherwise-real prereq text. **The parser needs a pre-filter/classification step before AND/OR tokenization** — not just a tokenizer.
- **CSCE was not representative of TAMU's format diversity.** CSCE consistently uses a `Prerequisite(s):` label with standard AND/OR/grade-threshold prose. Most other TAMU departments (STAT, ENGL, HIST, CHEM, MKTG, PHYS, ISTM, ...) drop the label entirely and store bare comma/semicolon-separated course lists or standalone eligibility text (e.g. "Junior or senior classification."). Parser rules need to handle labeled and unlabeled forms, not assume the CSCE pattern generalizes.
- **No scraper corruption found** at scale — zero HTML fragments, truncation, encoded-entity leaks, or placeholder values across all 1,598 populated SMU rows and 2,312 populated TAMU rows. Whatever's there is genuine prose, just format-inconsistent across departments.

This parser is worth its own audit-then-spec cycle before being built — it's a meaningfully hard NLP-adjacent problem and deserves the same scrutiny FIT/SHIFT got.

---

## 5. TAMU sequencing — SMU-first confirmed

SMU-first sequencing (§2) is confirmed, not just assumed. The upper-level prerequisite null rate that raised doubt in the prior revision of this spec (§3.4) turned out to be ~95% genuine (courses that legitimately have no prerequisite) and ~5% a narrow, mechanically fixable parser gap — not a scraper problem requiring re-work. Two small follow-ups are recommended before or alongside the requirement-skeleton build, not full blockers:

1. Extend `split_description()`'s `REQUISITE_SENTENCE` regex to catch permission/approval phrasing (e.g. "permission required", "instructor permission", "Dean's Office-approved") — fixes ~48 rows, concentrated in independent-study/special-topics templates.
2. The v1 scheduler should treat a genuinely-null `prerequisites` value as "no constraint" rather than an error or a blocking case — this is now confirmed to be the correct semantic for ~95% of null rows, not a workaround for a data gap.

TAMU requirement-skeleton ingestion remains a parallel/later track (§3.2), picked up once the prerequisite parser (§4) is stable, since it's the only school-specific piece left after that.

---

## 6. Recommended build sequence

1. **Regex extension (small, immediate)** — extend `split_description()`'s `REQUISITE_SENTENCE` pattern to catch permission/approval phrasing per §5. ~48-row fix, no schema change, no new data source. **Landed:** branch `smu-catalog-prereq-and-group-id`, commit `6a3ad7a`, 14 new tests, full suite (1396 tests) passing.
2. **SMU requirement-ID resolution — plumbing landed, join deferred.** `courseGroupId` now flows from Coursedog's `courses/search` response through `build_course()` → `import_catalog.py`'s `to_row()` → stored as `course_catalog.coursedog_group_id` (migration `20260817230000_course_catalog_coursedog_group_id.sql`, no RLS change needed — table-level `course_catalog_read_public` already covers it, same precedent as `course_records.catalog_course_id`). Branch `smu-catalog-prereq-and-group-id` off `dev`, not yet merged/pushed. **Still not built:** the actual ID→course-code join and requirement-skeleton ingestion logic — that's the next task, using this column as the join key against `programs/search/$filters`' `requisites` tree.
3. **Prerequisite parser** — its own spec/audit cycle per §4, built school-agnostic.
4. **Requirement-skeleton ingestion (SMU CS-BS only)** — pull and store the structured requirement buckets from §3.1, resolved to course codes via step 2.
5. **Requirement-satisfaction engine** — deterministic, rule-based (not LLM): map transcript against requirement buckets, produce a gap list of what's unsatisfied.
6. **Scheduler** — topological sort of remaining requirements using parsed prereq data (step 3), packed into terms bounded by a credit-hour cap (default: standard full-time load, e.g. 15, unless a better signal exists in the student's own course-load history).
7. **Elective slotting** — wherever the scheduler has open elective room, prefer GAP-recommended, target-role-relevant courses (reuses existing Course Discovery logic).
8. **UI** — 4-year term-by-term view, placed under Course Discovery per the original screenshot.

TAMU requirement-skeleton ingestion (§5) can be picked up in parallel once step 3 (parser) is stable, since it's the only school-specific piece left.

---

## 7. Explicitly out of scope for this spec

- Term-offering-pattern data (fall/spring/alternating-year) — flagged as a real risk in §3.4 but not solved here; needs its own investigation before the scheduler can be trusted for courses with irregular offering patterns
- Grade-minimum enforcement — parser should capture it (§4) but scheduler doesn't need to enforce it in v1
- TAMU requirement-skeleton scraper build (§5) — sequenced after SMU, not designed in this document
- Any UI/visual design work — this spec is data + logic only

---

## 8. Requirement-skeleton ingestion — design addendum

**Status:** DRAFT design, not yet a build prompt. Flagging open questions before committing to a schema.

### 8.1 Two different requirement-group shapes — must both be supported

SMU's CS-BS requirements (§3.1) contain two structurally different kinds of requirement group, confirmed from the live `requirements-krhha` page **and, this session, from the raw Coursedog `programs/search/$filters` response itself** (program `_id=CS-BS-2026-05-21`, queried live via the same unauthenticated Referer/Origin pattern as the courses endpoint):

- **Enumerated list**: a fixed, finite set of course options. Coursedog encodes this as `condition: "completedAllOf"` (all listed courses required) or `condition: "completedAtLeastXOf"` (choose N of the listed courses, N given by a sibling `restriction` field) on the rule object. The courses live in `value.values[]`, each entry an array of one or more `coursedog_group_id`s plus a `logic` of `"and"`/`"or"` — an `"and"` pair is a co-requisite bundle counted as one option (e.g. a lecture+lab pairing), not two alternatives.
- **Filter rule** (e.g. Technical Electives, 9 Credit Hours — "Nine credit hours of CS courses at the 3000 level or above as approved by adviser"): **confirmed not to be a structured filter object.** Coursedog encodes this as `condition: "freeformText"`, where `value` is just a generic label string (`"Complete the following:"`) and the entire actual constraint — department, level threshold, adviser-approval clause — lives only as prose inside the rule's `notes` field (HTML). No department code, no level-number field, nothing machine-parseable exists anywhere in the payload for this shape. See §8.3 for the full confirmation.

**Also found this session, not anticipated in the original draft: a third shape — compound/nested groups.** Two of CS-BS's seven major-requirement rules (`Lyle EDGE Curriculum`; a "Two Courses" rule choosing one lab-science sequence out of several) use `condition: "allOf"` / `"anyOf"` with a `subRules[]` array in place of a flat `value` — each sub-rule is itself a full rule object (enumerated, freeform, or further nested). This isn't an edge case in some other program; it's present in CS-BS's own major requirements, so ingestion can't skip it.

The requirement-skeleton schema must model all three shapes, or ingestion will either crash or silently store some groups as empty enumerated lists.

### 8.2 Revised schema shape (draft, not final — supersedes the original draft)

Revised per §8.3's filter-rule-shape findings: the original draft's `filter_department` / `filter_level_min` columns assumed a structured filter source that turned out not to exist, and the original draft had no shape for compound/nested groups.

    requirement_groups:
      - id
      - program_id (SMU CS-BS specifically for v1)
      - catalog_year: text, not null — mirrors course_catalog.catalog_year's existing precedent (§3.1: stored per-row, not in a separate version table). Pins this row to one snapshot ("2026-2027" for v1); a future re-scrape writes new rows under a new catalog_year rather than requiring a schema change. No cross-year coexistence or per-student catalog-year matching in v1 — see §8.3.
      - coursedog_rule_id: text — the source rule/group's own `id` field (e.g. "AjzAZTn4"), for traceability and idempotent re-import
      - parent_group_id: nullable self-reference — populated only for a subRule of a compound group
      - name: text (e.g. "Technical Electives (9 Credit Hours)")
      - group_type: enum('enumerated_all', 'enumerated_at_least_n', 'compound_all', 'compound_any', 'freeform') — maps 1:1 to Coursedog's `condition` field (completedAllOf, completedAtLeastXOf, allOf, anyOf, freeformText)
      - n_required: int, null unless group_type = 'enumerated_at_least_n' (value is Coursedog's `restriction` field)
      - credit_hours_required: int, null if not parseable from the group name's "(N Credit Hours)" suffix
      - notes_html: text, null if the source rule has no notes — captured whenever present, not just for freeform groups, since enumerated groups can carry qualifying prose too (e.g. Mathematics and Science's "one 3000-level or higher MATH or STAT course" note sits alongside an already-enumerated values[] list)
      - requires_manual_definition: boolean, default false, true when group_type = 'freeform' — tells the requirement-satisfaction engine (§6 step 5, not yet built) to treat this group as un-checkable against a transcript in v1 and surface it to the student as "ask your adviser," rather than silently marking it satisfied or unsatisfied

    requirement_group_options (only for group_type in ('enumerated_all', 'enumerated_at_least_n')):
      - id
      - requirement_group_id
      - option_index: int — position in the source values[] array
      - logic: enum('and', 'or') — mirrors that value entry's own `logic` field; 'and' means every course under this option_index must be completed together (e.g. lecture+lab), not that any one alone satisfies the option

    requirement_group_option_courses:
      - requirement_group_option_id
      - coursedog_group_id (joins to course_catalog.coursedog_group_id, per §3.1's confirmed join key)

This is a draft for review, not a migration to write yet.

### 8.3 Open questions for next session

**Unresolved course IDs — decided.** When a requirement group's course reference doesn't resolve against `coursedog_group_id` (~5% rate, likely inactive/renumbered courses per the prior audit), ingestion flags it (e.g. a nullable `unresolved_course_ref` field, surfaced in UI/logs) and continues importing the rest of the program's requirements. Does not fail the whole import.

**Corequisite satisfaction — decided.** "Concurrent enrollment allowed" counts a requirement group as satisfied once the student is enrolled in the course, not only once completed with a grade — matches how registration itself treats it. The requirement-satisfaction engine should check enrollment status, not just completed/graded transcript entries.

**Catalog-year scoping — resolved.** No demo student record (`data/students/*.json`) or production schema table (`students`, `student_institutions`, `academic_terms` — `supabase/migrations/20260728000103_institution_grading_schema.sql`) carries an explicit `catalog_year` / `admit_term` / `entry_term` field. Checked all five demo students (Jordan Reyes, Ethan Brooks, Marcus Webb, Priya Nair, Sofia Ramirez) and the production `students`/`student_institutions`/`academic_terms` DDL directly — neither has one. It's derivable in principle: `academic_terms` stores one row per student per term (`year`, `season`, `sequence`, where `sequence = 1` is the student's own first term at that institution), which combined with `data/reference/smu_term_dates.json`'s term-date table gives an entering term a future feature could map to a catalog year — but that derivation logic doesn't exist yet and is out of scope for this build.

Resolution follows the project's own existing precedent rather than inventing a new one: `course_catalog.catalog_year` is already stored per-row instead of in a separate version table (§3.1). `requirement_groups` gets the same treatment (§8.2) — a per-row `catalog_year`, populated with the single current snapshot ("2026-2027", matching `course_catalog`) for v1. This future-proofs the column for a later re-scrape without a schema migration, but v1 does not implement per-student catalog-year matching: the requirement-satisfaction engine (§6 step 5) matches every student against the one current `requirement_groups` snapshot, same as course matching already implicitly does today. Per-student catalog-year resolution via `academic_terms` is a real follow-up, not a v1 blocker.

*Separate finding surfaced by this check, flagged for Deepak rather than decided here:* none of the five demo/test students attend SMU or major in Computer Science — all five are TAMU students (Business Administration, Computer Engineering-intended, Psychology, Aerospace Engineering, Biology). There is currently no fixture student to run the SMU CS-BS requirement-satisfaction engine against end-to-end once it's built. Doesn't block the migration/ingestion work itself (program data, not student data), but worth a decision before step 5 in §6 — either add a sixth demo student or re-profile one of the five as an SMU CS major.

**Filter-rule shape — resolved.** Pulled the live CS-BS payload from Coursedog's `programs/search/$filters` endpoint this session (program `_id=CS-BS-2026-05-21` — the exact ID from the original audit's example, confirmed live via a filtered query on `_id`; same unauthenticated Referer/Origin pattern as §3.1, executed via Chrome's page context so the request carried the site's own headers, robots.txt on catalog.smu.edu not applicable to this XHR-origin request). Findings, superseding the "likely encodes this differently... needs confirmation" language in the original §8.1:

- Filter-rule groups (Technical Electives; Advanced Major Electives — 2 of CS-BS's 7 major-requirement rules) use `condition: "freeformText"`, with no department/level fields anywhere in the payload — the entire constraint is prose in `notes`. The original draft's `filter_department`/`filter_level_min` columns have no source to populate from and are dropped in the revised §8.2.
- Enumerated groups use `condition: "completedAllOf"` (all required) or `"completedAtLeastXOf"` (choose N, N in a `restriction` field) — confirmed against Computer Science Core (11 courses, completedAllOf) and Engineering Leadership (6 courses, choose 2, completedAtLeastXOf/restriction:2), alongside the already-audited "Required Courses" example.
- A third shape not anticipated in the original draft: compound groups (`condition: "allOf"`/`"anyOf"` wrapping a `subRules[]` array of further rule objects), used by 2 of CS-BS's 7 major-requirement rules (Lyle EDGE Curriculum; the lab-science-sequence choice). The revised §8.2 supports this via `parent_group_id` self-reference — not optional, since it's present in CS-BS's own major requirements, not just some other program.

§8.2 has been revised to match all three shapes. Still a draft for the build prompt to implement, not a migration that's been written.
