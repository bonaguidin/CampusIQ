# GradusIQ — Improvements Backlog

_Running list: bugs, gaps, and feature ideas. Update as items close._

_Full audit pass completed 2026-08-24 — every item below was re-verified against current code/data/DB state, not trusted from prior doc text, including a fresh live read-only trace of the TAMU scheduler pipeline against a real account. See "Recently closed" for items found done-but-unmarked._

---

## 🔴 Blocking / real students affected

- [ ] **GAP's synchronous execution risks exceeding Vercel's function timeout for real students.** Re-verified 2026-08-24, no change since last audit (2026-08-17). The full chain (`api.py:analyze_gap` → `_run_protected_feature` → `GapRunner.run` → `role_requirements_for` → `role_research_agent.get_role_requirements` → `CareerFeatureRunner.run`'s DeepSeek R1 synthesis call) is entirely synchronous. Two costs stack: (1) the DeepSeek R1 call itself, documented as routinely 100–200s+ (`ai/openrouter_client.py:16-20`), timeout set to 300s to accommodate it; (2) `role_requirements_for` (`gap.py:188-201`) loops over uncovered target roles **sequentially**, each bounded by a 90s wall-clock budget (`role_research_agent.py:115`). `frontend/vercel.json` caps `api/proxy.mjs` at `maxDuration: 300` — one uncovered role plus the DeepSeek call can already approach or exceed that ceiling.

  This is a **hard blocker for extending auto-run analysis to real student accounts**. `useCachedAnalysisRun` (`frontend/src/hooks/useCachedAnalysisRun.ts:26-49`) already deliberately withholds auto-run for real students because of this — they only get GAP via a manual click, which still hits this same unbounded path.

  Three fix directions, none implemented:
  - **(a) Decouple into a background job, client polls/receives an event.** Correct long-term fix; no queue/worker infra exists today. `student_analysis_cache` (`api.py:1005-1025`) could grow a status column, but this is a real infra lift.
  - **(b) More aggressive cross-student role-research caching.** Partially moot: `role_research_cache.json` is already shared/global, keyed by role name only, no TTL. Doesn't touch the dominant DeepSeek cost.
  - **(c) Raise the Vercel timeout ceiling.** Cheapest if the plan supports it (unverified — needs checking in the Vercel dashboard, not assumed); even 800s isn't a full fix for a student with multiple uncovered roles.

  **Next step:** (a) is the real fix — scope the background-job/status-column design. (c) is worth a 5-minute check of the actual Vercel plan tier before ruling it out as a stopgap.

## 🟠 Product integrity — unsourced claims presented as data

- [ ] **Tavily is the wrong grounding tool for FIT/SHIFT's quantitative claims** — still open, unchanged. Tavily is a search/summarization API — correct for GAP's qualitative role research, wrong for claims requiring structured counts (postings, percentages). The FIT fix worked by removing the false promise of data, not by adding real posting data. Depends on the job-postings vendor work below actually reaching production use.

## 🟡 Data coverage — no API needed, pure data work

- [ ] **No generation script for the O*NET file** — `data/onet/build_onet.py` exists (375 lines) but coverage is still curated/manual, not automated against the full O*NET release.

## 🟡 Job posting data — vendor decided, infra still doesn't exist

- [x] ~~Vendor never actually decided~~ — **resolved**: Adzuna confirmed as sole primary vendor; JSearch's remaining use is narrow (LinkedIn-source confirmation, untested, not urgent). See ✅ Shipped section — schema and clients are built.
- [ ] **Quota math requires cache-first architecture** — Adzuna ~1,000 calls/mo (~33/day). Must fetch-on-schedule + cache, never call live per student request. Ingest workflow (`.github/workflows/postings-ingest.yml`) implements the schedule; blocked on secrets below.
- [ ] **No TTL primitive exists anywhere else in the codebase** outside the job_postings table itself — `role_research_cache.json` still has no timestamp field. Relevant if that cache is ever reused for postings-adjacent data.
- [ ] **Cache architecture won't scale as-is if extended beyond job_postings** — the one remaining flat-file cache (`role_research_cache.json`) has no locking under `WEB_CONCURRENCY > 1`. Fine at 15 roles; don't reuse this pattern for one-to-many posting data (job_postings already avoids it by being a real table).

## 🟡 Job postings pipeline — manual ops step blocking nightly ingest

- [ ] **GitHub repo secrets not yet added.** `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `SUPABASE_URL`, and `SUPABASE_SECRET_KEY` still need to be added manually to the GitHub repo's Actions secrets before `.github/workflows/postings-ingest.yml` does anything beyond skip cleanly on its nightly schedule. Manual/ops task — no PR closes this.
- [ ] **Workflow's own skip-guard only checks 3 of the 4 secrets.** Re-verified 2026-08-24: `postings-ingest.yml`'s "Check configuration" step tests `ADZUNA_APP_ID`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY` for the `ready=false` skip condition, but **not** `ADZUNA_APP_KEY` — that one is only referenced later in the `Ingest` step's env. If `ADZUNA_APP_KEY` alone is missing, the workflow won't skip cleanly — it'll proceed past the guard and fail inside the Adzuna client call instead. Small fix: add `ADZUNA_APP_KEY` to the guard's missing-check list.

## 🟡 TAMU degree planner — verified working end-to-end, several pieces still soft

TAMU Computer Engineering - BS now has a full pipeline: catalog scrape (`data/catalog/fetch_tamu_requirements.py`, commit `b5560f2`, 2026-08-23 12:55) → requirement-skeleton import (`data/catalog/import_tamu_requirements.py`, commit `01c8f81`, 16:04) → satisfaction engine (`requirement_satisfaction.py`, extended for `course_code` alongside SMU's `coursedog_group_id`) → scheduler (`scheduler_scope.py`'s `_leaf_course_requirements()`, redesigned to return `list[frozenset[str]]` so "/"-joined cross-listings like `ENGR 216/PHYS 216` resolve as "either code satisfies," commit `bc5953b`, 16:27) → SCHEDULE/satisfaction API routes (`cd3988d`, 16:27; `e2403a8`, 16:28).

**✅ Verified working end-to-end against a real account as of 2026-08-24, re-confirmed via a fresh live trace** (not the prior session's self-report — an independent read-only script run against the live Supabase project, replicating `_reconstruct_academic_schedule()`'s exact call sequence for `muralideepak2006@gmail.com`, service-role client, zero writes):
  - `student_institutions.catalog_year` = `'2026-2027'`, resolving to `institution_id 75d68331-91d2-47e8-9671-2a3b065955d0` (Texas A&M University).
  - `_resolve_program_id_for_student` resolves exactly one program: `id=8c240ed7-c7da-4f81-896f-6e04885a9cea, code=ECEN-CPEN-BS, name=Computer Engineering` — matches the previously-cited program ID.
  - `fetch_requirement_tree` → `evaluate_requirement_tree` → `scope_schedule_input` → `structured_candidate_codes` → `select_structured_requirements` → `schedule_courses` ran the full chain live: **31 requirement groups, 33 options, 37 option_courses fetched; scheduler output `SCHEDULED`, 2 terms — 2027-Spring (`CSCE 313, CSCE 350, CSCE 481, ECEN 314, MATH 311`, 15 cr) and 2027-Fall (`MATH 152`, 4 cr) — 6 no-choice courses total, 17 unscheduled** (a mix of 8 `SELECTION_DEFERRED` and 9 `FREEFORM_MANUAL_REVIEW`, not previously broken out). This matches the doc's prior "6 no-choice courses across 2 terms, 17 deferred" claim exactly.
  - **On the contradiction the audit flagged:** `b5560f2` (12:55, "not integrated... no demo student") and `01c8f81` (16:04, "hypothetical transcript, not a real student") both predate the scheduler-extension commits `cd3988d`/`bc5953b`/`e2403a8` (16:27–16:28) by 20+ minutes same-day. Those messages describe an honest earlier point in the same session's timeline, before the code-path wiring was added — not a standing contradiction of the later "works against a real account" claim. Confirmed by commit timestamp ordering, not assumed.
  - **Caveat:** this is a point-in-time verification (run 2026-08-24), not a standing guarantee — schema or data drift could change the result on a future re-run. A read-only live trace against a real account legitimately leaves no commit trail, which is why this needed a fresh out-of-band check rather than a repo grep.

Open items surfaced by this session's work, none of which block the above:

- [x] ~~`requirement_group_option_courses`'s `course_code` column/CHECK migration is written but not applied~~ — **corrected 2026-08-24: it IS applied.** `supabase/migrations/20260823140000_requirement_group_option_courses_course_code.sql` (commit `bada2c2`) adds a nullable `course_code text` and replaces the exactly-one-ref CHECK with a 3-way version (`coursedog_group_id` / `unresolved_course_ref` / `course_code`, exactly one non-null). The file's own header comment still reads "Not applied. DDL only." — **that header is stale**; `supabase migration list --linked` shows `20260823140000` present in both Local and Remote, and the live trace above independently confirms it (37/37 `option_courses` rows fetched with usable `course_code` values). Same pattern as the `job_postings` migration's stale in-file "DRAFT" comment noted below — worth a follow-up pass to update both file headers so they don't keep misleading the next reader, but not an open functional item.
- [ ] **Combinatorial choice engine (`requirement_selection.py`) still resolves courses only via `coursedog_group_id`.** `_option_variants()` (`:159`), `_leaf_choices()` (`:172`), `_choices_for_group()` (`:250`), feeding `select_structured_requirements()` — none take a `catalog_by_code` param, deliberately deferred during the TAMU scheduler build (unlike `structured_candidate_codes()` at `:131`, which was extended). **Why deferred:** this cluster builds combinatorial variant tuples via `product()`/`combinations()` and checks `all(code in satisfied for code in variant)` — a "/"-joined cross-listing needs "either code satisfies," which this shape can't express without a redesign analogous to `scheduler_scope.py`'s `_leaf_course_requirements()`. **Practical effect:** TAMU's genuine choice groups (`ENGL 103 or ENGL 104`, `MATH 251 or MATH 253`, etc.) land in `SELECTION_DEFERRED` — visible in `unscheduled`, not silently wrong, just never auto-selected the way SMU's equivalent groups are. **Next step:** extend with an equivalence-aware course_code path once there's real TAMU choice-group usage to validate the redesign against.
- [ ] **`footnotes_enforced: false` on TAMU requirement data.** `data/catalog/tamu/requirements_computer-engineering-bs.json:10`. Footnote text is stored (JSON remains "the authoritative carrier of footnote text" per `import_tamu_requirements.py:65-72`) but never imported into the DB or enforced by the satisfaction engine. Footnotes 3 and 4 are confirmed shared CourseLeaf boilerplate naming *other* majors (BS-AREN/DAEN/IDIS/CVEN/EVEN/PETE for footnote 3; BS-BMEN/CHEN/MSEN for footnote 4) — each footnote needs per-footnote verification of what actually applies to Computer Engineering before any of them are ever enforced.
- [ ] **`modeling_confidence: "inferred"` on the "Fourth Year — Fall — High Impact Experience" group** (`requirements_computer-engineering-bs.json:739,759`). Footnote 9 just points to "the CSE or ECE advising office" for the actual list of qualifying experiences — this group's modeling was inferred, not sourced from a concrete list, and needs eventual human/advisor verification before being trusted the way the rest of the requirement tree is.
- [x] **`api.py:2520`'s docstring on `get_me_requirement_satisfaction` is confirmed stale.** Currently reads "Live for exactly one program today (SMU CS-BS / Ethan Brooks)." The 2026-08-24 live trace confirms `_resolve_program_id_for_student` now also resolves a second, live program row for TAMU (`8c240ed7-c7da-4f81-896f-6e04885a9cea`, Computer Engineering) — this comment (last touched 2026-08-19, before the TAMU import) is out of date and should be updated to reflect two live programs, not one.
- [ ] **`technical_elective_candidates.py` is SMU-only by design, not yet extended.** Module docstring: "Deterministic provisional candidates for **SMU CS** technical electives" (`:1`); hard-filters `course.institution != CatalogInstitution.SMU` (`:161`) and constructs results with `institution=CatalogInstitution.SMU` unconditionally (`:212`). Unlike the requirement-satisfaction/scheduler path, this is a hard filter, not a missing-data path — it will silently return an empty candidate list for TAMU students rather than erroring. Needs the same institution-generic treatment the requirement-satisfaction stack already got, before TAMU students hit the Career Optimization / technical-elective UI.

## 🟡 Course Discovery / Action Plan demo profiles — landed mid-session, unreviewed until now

Commits `defaf14` ("Bring Course Discovery, Action Plan, and course lifecycle into the demo profiles") and `566bf6c` (rebase fixup) pushed directly to `dev` mid-session. Audited 2026-08-24: **no conflict with the concurrent TAMU work** — the demo push lives entirely in `api.py:1265-1520` (new demo-only routes/resolvers) and `demo/profile_adapter.py`/`demo/build_course_discovery_cache.py`, while the TAMU commits touch `get_me_requirement_satisfaction` (`api.py:2547`) and `_reconstruct_academic_schedule` (`api.py:2641`) — disjoint code, and Course Discovery/Action Plan don't route through the scheduler/requirement-tree path at all. `profile_adapter.py` already builds courses from `course["course_code"]` directly, so it's naturally code-based, not `coursedog_group_id`-dependent. Also fixed in this push: Course Discovery was missing from `ME_ANALYZE_FEATURES` and Action Plan had no proxy rewrite at all for real authenticated students — a pre-existing bug for real students, fixed as a side effect.

- [ ] **Stale `course_id` references in Ethan Brooks's demo fixture, flagged by its own author but not yet fixed.** `data/students/student_ethanBrooks.json:5` — `assignments`/`submissions`/`examTopicTags` still reference old TAMU-era `course_ids` (3010/3012/3014/3023/3024/3025) that no longer exist in the fixture's `courses[]` after the SMU/CS rewrite. Needs a rewrite-or-remove pass.
- [ ] **New demo modules shipped with zero test coverage.** `GradusIQ_career/demo/profile_adapter.py` (real logic: `_course_status`, `_letter_grade`, `_career_items`, `build_demo_intelligence_profile`) and `GradusIQ_career/demo/role_slug.py` (small, but shared between `api.py` and the demo cache builder specifically to prevent filename drift — exactly the kind of contract a regression could silently break) both have no corresponding test file. `build_course_discovery_cache.py` also isn't covered by `test_build_demo_cache.py`.
- [ ] **Demo Action Plan hardcodes `planned_courses` to `[]`.** `api.py:1271` — intentional, documented ("demo students have no planned_courses rows anywhere"), not a bug, but a known scope limit worth remembering if demo Action Plan output looks thinner than the real-student version.

## 🟡 Syllabus grade calculator — cutoff-overlap detection gap

- [ ] **`_check_grade_thresholds` never flags an overlap that involves a single-bound threshold.** `GradusIQ_career/syllabus/reconciliation.py` — the overlap scan runs only over `bounded = [t for t in thresholds if t.minimum is not None and t.maximum is not None]`, so a threshold expressed as one bound only (`"A: 90+"`, `"F: below 60"` → `maximum` set, `minimum` None) is excluded entirely. A syllabus like `A: 90+` / `B: 85–92` genuinely overlaps at 90–92 but produces no `overlapping_grade_thresholds` finding. Pre-existing since PR #54; **not introduced by the syllabus-review backend reclassification pass** (2026-08-28), just surfaced while building `cutoff_resolution.resolve_cutoff_overlaps` — that function reports such pairs as `unresolved` with reason `single_bound_threshold`, but the upstream detector still won't have raised anything for the student to see. Fix would widen the detector to treat a missing bound as ±∞ (matching `cutoff_resolution._overlaps`), then decide whether a single-bound overlap is ERROR or just a clarifying question.

## 🟡 AI model config — unverified placeholder model ID

- [ ] **Gemini 2.5 Pro's OpenRouter model identifier is still a placeholder.** `GradusIQ_career/ai/model_config.py:13` — `OPENROUTER_GEMINI_2_5_PRO = "TODO_OPENROUTER_MODEL_GEMINI_2_5_PRO"`, flagged inline at `:10`. The `PLACEHOLDER_MODEL_PREFIX = "TODO_"` sentinel (`:75`) means a real API call would hard-fail loudly rather than silently misroute — low severity — but whichever role currently points at this constant (the "orchestrator" role, per `test_ai_phase1.py:336,413,421`) will fail the moment it's exercised live. Verify the real OpenRouter identifier before that role ships.

## ✅ Shipped this session (2026-08-22 – 2026-08-24)

- **Degree Planner (SMU)** — term-by-term schedule UI, opt-in career-optimization schedule preview, technical elective candidates surfaced under their requirement group, BIOL 1301/1101 corequisite parsing fix. Merged to `main`.
- **TAMU Computer Engineering - BS pipeline** — catalog scraper, requirement-skeleton import, `course_code`-aware satisfaction engine and scheduler, SCHEDULE/satisfaction API routes threaded with `catalog_by_code`. **Verified working end-to-end against a real account via a fresh live trace on 2026-08-24** — see 🟡 TAMU section above for the full trace output and the still-open follow-ups (footnotes not enforced, one inferred-confidence group, SMU-only technical-electives filter, deferred combinatorial choice engine, a stale docstring).
- **Course Discovery, Action Plan, and course lifecycle in demo profiles** — new demo-only routes/resolvers, static `course_lifecycle_preview` fixtures for all 5 demo students, real-student Course Discovery/Action Plan proxy-routing bug fixed as a side effect. See dedicated 🟡 section above for follow-ups.
- **Postings Grounding** — `job_postings` schema fully applied live (confirmed via `supabase migration list --linked`, Local == Remote, including the `20260822170000` amendment migration), ATS/cross-source identity resolution, Adzuna/JSearch/Workday clients, nightly ingest + retention workflow. Merged to `main`, currently inert pending the secrets above.
- **ATS Fetcher** — remediated and merged: platform-count claim corrected (4 platforms implemented, Recruitee scoped but not built), Greenhouse null-title crash fixed, SmartRecruiters silent-empty-description bug fixed, ~49 new tests. **Open follow-up unchanged:** Recruitee needs a Recruitee-boarded employer added to `employers.json` before it can be built and verified.
- **Node 20 `.ts` import fix** (`6874b82`) — closed. Worth remembering if a new `.ts` file under `frontend/src` hits the same pattern.
- **`data/onet/reference/coverage_gaps.csv`** — salvaged from `origin/onet-data-load` (122 real unrated O*NET occupations). Worth addressing as its own coverage item.

## 🟢 Recently closed — verified done, doc previously didn't reflect it

- [x] **Academic Record — term structure (Phase 1).** Doc previously read "audited and built, not yet merged" and the Suggested-order list still had "Commit and deploy Phase 1" as step 1 — both stale. Re-verified 2026-08-24: migration `7f17185` (adding `20260811120000_academic_term_dates.sql`, `20260811120100_planned_courses.sql`, `20260811120200_course_catalog_search.sql`) is an ancestor of both `main` and `dev`. `supabase migration list --linked` shows Local == Remote for all three, no drift — **applied to production**. Frontend wiring confirmed: `frontend/src/components/TermPlanner.tsx`, `frontend/src/api/planning.ts`, and `GradusIQ_career/planning/{planned,lifecycle,term_view}.py` all reference `planned_courses`/`academic_term_dates` directly. Fully done — schema, backend, and frontend. Phase 2 (reconciling a real transcript arriving for a course marked "planned") remains genuinely deferred, not done.
  - Schema decisions for reference: planned courses live in a separate `planned_courses` table (not a third `course_records.status` value, to avoid a unique-index collision with real transcript rows). TAMU term dates are a hardcoded per-year table sourced from TAMU's official calendar PDF; SMU term dates are snapshotted from Coursedog's terms endpoint (`data/reference/smu_term_dates.json`, 16 terms for 2026–2027).

## ✅ Confirmed working / not actually broken (don't re-investigate)

- GAP's Tavily-backed live role research (`role_research_agent.py`) — genuinely live, timeout-bounded, injection-bounded, fails safe to static, 15 roles cached.
- Demo-analysis cache (`data/demo_cache/`) infrastructure — the old "failed entries served as successes" bug is confirmed fixed.
- The O*NET *data itself* isn't fake — real O*NET 30.3, correctly rescaled. It's a coverage mismatch, not a correctness bug.
- **CI gate is live and working.** No direct-to-main pushes since 2026-08-09; all subsequent PRs landed as proper merge commits with passing checks.
- **FIT/GAP/SHIFT grounding, `validate_data` conflict, and demo-cache fabrication** — resolved and merged to main as of 2026-08-12. Known residuals documented in 🟠 above.
- **"Known blockers" recheck (2026-08-24):** re-audited a recalled list of four items — a "demo-login routing gap," an "overly-broad `confirmed_at` trigger," "mock interview Whisper verification," and an "AI model tier decision." **None of these correspond to anything in this repo.** `git log --all` has zero hits for "whisper," "demo-login," or "model tier/pricing tier" anywhere in history. The one real `confirmed_at`-related commit (`82e9b85`) explicitly states "No auto-update trigger added; none exists anywhere in the schema today" — directly contradicting the recalled "overly-broad trigger." No "mock interview" feature exists in the codebase at all. These appear to be from a different project or a stale/confabulated memory — not tracked here since there's nothing to act on. Flag if a source for these turns up.

## 🟢 Agentic architecture — proposed, not started

- `role_research_agent.py` is the one real agent in the codebase (bounded tool loop, Tavily, timeout/injection bounds, cache-first). Copy this pattern, don't reinvent it.
- FIT/GAP/SHIFT/PCA are single-shot LLM calls (`CareerFeatureRunner`) — no tool use, no loop. Chat is session-only today.

- [ ] Improve prerequisite/restriction data coverage and course-ranking quality if C2R.2 remains unresolved-heavy; do not weaken conservative `UNRESOLVED` semantics.
- [ ] Course degree applicability and term offering/section/seat availability remain unresolved; no authoritative degree-planning or schedule model exists.
- [ ] Advisor orchestration remains proposed; do not grant course-write or registration authority.
- [ ] Run and review the controlled B2 live baseline (12 synthetic evaluations; explicit paid/network opt-in required).
- [ ] Phase B2: choose and review durable trace storage/retention before enabling production persistence. Cost estimation remains deferred until reliable repository-controlled model pricing exists.

Proposed agents, roughly in order of leverage:

- [ ] **Orchestrator Agent** — runs FIT/GAP/SHIFT/PCA together, synthesizes one coherent narrative instead of four disjoint outputs.
- [ ] **Market Intelligence Agent** — owns the job-posting fetch/cache/refresh cycle. Scheduled, not request-triggered.
- [ ] **Course Planning Agent** — cross-references `course_catalog` + transcript + GPA + GAP's skill gaps → recommends actual next-semester courses. Has a natural home now that `planned_courses` is live.
- [ ] **Advisor Agent (persistent chat)** — existing chat + cross-session memory + tool access to the other agents' outputs.

## 🟢 Student memory system — proposed, not started

- **Session memory** (exists) vs. **longitudinal memory** (doesn't exist — target role changes, closed skill gaps, corrections that shouldn't re-flag).
- [ ] Design a `student_events` / `student_memory` table: student_id, fact, source, confidence, first_seen, last_confirmed.
- [ ] Feature runners write to it when they detect something durable.
- [ ] Advisor Agent reads from it via tool-calling, not by re-deriving from scratch.

## 🟡 Test suite — flake watch list (not confirmed broken)

- [ ] **`test_career_optimization_cache_changes_with_selection_add_change_and_clear`** (`tests/test_api_v2_schedule.py`) failed exactly once, on PR #52's CI run, with `assert 4 == 3` (a fingerprint set had one extra unique value). Never reproduced since: clean across 6 isolated local runs (3× on `dev`, 3× on the PR branch), clean across 3 full-suite runs on `dev` (1981 passed each time, this test included), and clean on a same-commit CI re-run. Logging as a watch-item in case it recurs — not treated as a confirmed bug. If it fails again, the fingerprint-uniqueness assertion and whatever seeds/orders the four `OPTIMIZE_URL` calls in that test are the place to start.

## 🔵 Bigger picture — process & product gaps

- [ ] **Canvas (LMS) integration is still mocked.** The academic-grades side is fake for every real student while career data (resume/transcript) and now degree-catalog data (SMU + TAMU) are genuinely real. This asymmetry gets worse, not better, as more schools' catalogs come online.
- [ ] **No end-to-end smoke test.** 820+ unit tests, zero tests walking the real signup→provision→upload→confirm→run-a-feature flow against live/staging. The test account used for manual dry-runs was deleted.
- [ ] **Design consistency pass, once the review screen pattern settles.** Worth checking whether FIT/GAP/SHIFT, the GPA view, and the new degree-planner/term-schedule UI still look consistent with each other.
- [ ] **Surface data provenance to students, not just internally.** Real `catalog_year` / `source_last_checked` fields exist (now for two institutions) but never reach the UI.
- [ ] **`ats-fetcher` work is a single point of failure.** Per dev's `STATUS.md`, the fetcher implementation and `skill_terms_review.csv` exist only on one local branch on one machine — untracked corpus, no remote copy, no history anywhere.
- [ ] **4 grounding-related commits never remapped/merged, deliberately deferred.** From `feat/gap-shift-grounding`: SHIFT concurrency (`a5b5ae0`), 30-day trend-cache expiry (`f1e1635`), `.env` loading in `build_demo_cache.py` (`31cdc5a`), a generic parse-retry loop in `base.run()` (`48aa9fb`). None were in scope for the FIT/GAP fabrication fix.

---

## Suggested order

TAMU's pipeline is confirmed working end-to-end as of this audit (2026-08-24, live trace), so the open work is closing targeted follow-ups, not fixing something broken:

1. **Fix `technical_elective_candidates.py`'s SMU-only hard filter** before a TAMU student hits Career Optimization / technical electives and silently gets nothing.
2. **Fix the `api.py:2520` stale "one program" comment** and the two stale "not applied"/"DRAFT" migration-file headers (`20260823140000`, `20260822170000`) — quick documentation-accuracy pass, low effort, prevents the next person from re-litigating something already resolved.
3. **Add tests for `demo/profile_adapter.py` and `demo/role_slug.py`** — both carry real logic/contract behavior with zero coverage.
4. **Add the GitHub repo secrets** for the postings pipeline (ops task, not code) and fix the workflow's skip-guard to also check `ADZUNA_APP_KEY`.
5. **Extend the combinatorial choice engine** (`requirement_selection.py`) for TAMU once there's real choice-group usage to validate against.
6. **Verify TAMU footnotes 3/4 and the "inferred" High Impact Experience group** before either is ever enforced or presented as authoritative to a student.
7. **Clean up Ethan Brooks's stale fixture `course_id` references** — small, but flagged by its own author and easy to lose track of.
8. **Scope the GAP background-job fix** (🔴 above) — still the biggest real-student risk in the codebase, unchanged this session.
9. **Add an end-to-end smoke test** before the next production deploy.
10. **Extend O*NET role coverage** toward full 14/14.
