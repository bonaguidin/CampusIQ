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
- **Open gap:** requirement groups reference courses by internal Coursedog ID (e.g. `0045691`), not human-readable course number. Needs confirmation that the existing Coursedog course-catalog integration can resolve these IDs to course codes — not yet checked.

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

### 3.4 What's still genuinely unconfirmed
- **Coverage breadth.** Confirmed populated for 5 CSCE courses. Not confirmed across the full catalog (1,374 TAMU / 3,249 SMU courses). Likely broadly populated since it's the same scraper/parser, but not verified — first build-time check, not a blocker (see §6).
- **SMU internal-ID → course-code mapping** for the degree-requirements endpoint (§3.1 open gap above).
- **Term-offering pattern** (fall-only / spring-only / alternating-year courses) — not investigated at all this round. A required course scheduled into a term it doesn't run in would silently produce a wrong plan.

---

## 4. The core engineering problem — prerequisite parsing

This is now the long pole, not data acquisition. `prerequisites` is unstructured prose with real logical complexity:

- **AND / OR nesting**: "Grade C or better in CSCE 120 or CSCE 121; grade of C or better in CSCE 222/ECEN 222..."
- **Cross-listed courses**: "CSCE 222/ECEN 222 or ECEN 222/CSCE 222" — same course, two department codes, redundantly listed both orders
- **Concurrent enrollment / corequisites** embedded in the same sentence, distinguished only by phrasing ("or concurrent enrollment") rather than a separate field
- **Grade minimums** ("Grade of C or better") — not currently modeled anywhere; the planner needs to at least be aware a grade floor exists, even if it doesn't enforce it in v1

**Recommendation:** treat this as its own parsing/normalization pass, run once per course record (not per-student, per-request) and cached — same "never call live per request" architecture principle already established for job-posting data in the backlog. Output should be a structured intermediate form (e.g. `{requires_all: [...], requires_any: [...], coreq_allowed: [...], grade_min: "C"}`) that the scheduler consumes, rather than re-parsing prose at scheduling time.

This parser is worth its own audit-then-spec cycle before being built — it's a meaningfully hard NLP-adjacent problem and deserves the same scrutiny FIT/SHIFT got.

---

## 5. TAMU sequencing — explicitly not a blocker

TAMU requirement-skeleton ingestion (§3.2) doesn't exist yet and isn't scoped in this spec. Given SMU is confirmed end-to-end (requirements structure + prereq data, both live), building the requirement-skeleton engine against SMU first, then porting the same engine to TAMU once its plan-grid scraper exists, is the lower-risk path. The prereq-parsing work in §4 is shared across both schools and should be built school-agnostic from the start.

---

## 6. Recommended build sequence

1. **Coverage-breadth check** (cheap, first) — query `prerequisites` population rate across the full SMU catalog, not just the 5 sampled courses. If coverage is spotty, that changes the parser's error-handling requirements (must degrade gracefully on missing data, not assume every course has a value).
2. **SMU requirement-ID resolution** — confirm whether the existing Coursedog course-catalog integration can resolve the internal IDs from `catalog.smu.edu`'s requirements endpoint to human-readable course codes. This blocks the requirement-skeleton ingestion specifically.
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
