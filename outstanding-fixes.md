# GradusIQ — Improvements Backlog

_Running list: bugs, gaps, and feature ideas. Update as items close._

---

## 🔴 Blocking / real students affected

- [x] ~~`GradusIQ_career/` bytecode leftover~~ — resolved. Confirmed 2026-08-12: zero tracked `CampusIQ_career` files on origin/dev; the only remaining reference is inside an unrelated agent worktree (`.claude/worktrees/`), which isn't part of the repo proper. Cosmetic, no action needed.
- [x] ~~Confirm `feat/resume-review-redesign` actually landed on `main`~~ — confirmed 2026-08-12: merged via `e8bfc06` (PR #22), ancestor of main.

## 🟠 Product integrity — unsourced claims presented as data

- [x] ~~FIT has zero market grounding~~ — **resolved and merged to main** (`4ce2bab`, PR #39, 2026-08-12). FIT now pulls the same O*NET-backed providers GAP/SHIFT use (`get_market_requirements`, `get_shift_signals`, `_nearest_rated_neighbour`), with the dead "Live DFW Posting Requirements" injection block removed — including a second stale reference the first fix missed ("live DFW postings from web search" survived in the prompt header even after the block itself was deleted). Verified before/after across all 5 demo bundles: named employers 17→0, posting-language 4→0, unsourced percentages 0→0, internal field-name leaks 0. Backed by real regression tests (fail pre-fix, pass post-fix — verified by reverting, not asserted).
- [x] ~~SHIFT has zero market grounding~~ — resolved, same merge. 1 residual hit post-fix, traced to pre-fix cached demo output, not a code gap.
- [x] ~~Demo cache rebuild blocked on FIT~~ — resolved. Demo cache regenerated as part of the FIT fix; fabrication eliminated in FIT (0/0/0/0 across all 5 bundles). Two known non-blocking residuals remain, both in GAP, both soft phrasing rather than fabrication:
  - `jordanReyes`: "Google Data Analytics Certificate" — a real certification from the student's own source profile, not an invented claim.
  - `marcusWebb`: "...hiring managers will expect" — grounded in a real O*NET importance-90 score, but the phrasing asserts an employer-expectation claim nothing directly measured. Worth tightening next time GAP's prompt copy is revisited; not urgent.
- [x] ~~`validate_data` signature conflict~~ — new item this session, now resolved. Two independent implementers (`gap.py` on a feature branch, `academic.py` on dev) had incompatible signatures. Resolved in dev's favor (`(data, student_profile) -> list[str]`, the strict superset — it's what powers `academic.py`'s citation checking); GAP's guard ported to match, coexistence verified (no shared state, single call site repo-wide).
- [x] ~~GAP wastes agent calls on roles it could resolve locally~~ — new item this session, now resolved. `role_requirements_for()` previously skipped the research agent only on `provenance == "onet"`; roles that borrowed from a rated neighbor (`onet_neighbor`) still triggered a wasted live research call. Fixed: `grounded = provenance in ("onet", "onet_neighbor")`.
- [x] **O\*NET reference data now unmemoized on load** — new item this session. `data/reference/onet_soc_requirements.json` grew 31KB → 5.4MB as part of the FIT/GAP grounding work; `_load_onet()` reparses the full file on every provider call instead of caching like its sibling `_role_soc_cache`. Fixed in `43264c6` (merged to main) — module-level memoization added, deliberately does NOT cache a failed load (so a transient read error during deploy can't permanently pin an empty catalog for the process lifetime). Closing this item; listed here for the record since it was found and fixed same-day.
- [ ] **fit.py's `_resolve_major` mishandles an empty Current major.** If a student has no `major_current` set and indicates they're switching majors, `_resolve_major` returns `(intended, "switching")` — FIT tells the student they're switching into what is actually their only declared major. Not a crash; a coherent-but-wrong framing. Found 2026-08-12 while building the profile-completion modal's switching-major checkbox (frontend correctly left this alone since it's a fit.py fix, not a form fix). Fix: `_resolve_major` should treat an empty current major as a declare, not a switch, regardless of the checkbox state.
- [ ] **Tavily is the wrong grounding tool for FIT/SHIFT's quantitative claims** — still open, unrelated to the fix above. Tavily is a search/summarization API — correct fit for GAP's actual use (qualitative role research), wrong for claims requiring structured counts (postings, percentages). Same underlying gap as the job-posting-vendor item below; the FIT fix worked by removing the false promise of data, not by adding real posting data. That's still a future project.

## 🟡 Data coverage — no API needed, pure data work

- [x] ~~O*NET static file covers the wrong roles~~ — substantially improved this session. Reference JSON expanded from ~2 to 12 grounded demo roles (+191,506 lines via the grounding work merged in PR #37). Still short of full 14/14 target-role coverage.
- [ ] **No generation script for the O*NET file** — `data/onet/build_onet.py` exists now (375 lines) but coverage is still curated/manual, not automated against the full O*NET release.

## 🟡 Job posting data — doesn't exist at all

- [ ] **Vendor never actually decided.** `market_data.py` docstring says Adzuna/JSearch. `react-dashboard-plan.md` says Lightcast. No credential, no config, no code for any of them. `dfw_postings: None` is a hardcoded literal.
- [ ] **Quota math requires cache-first architecture** — Adzuna ~1,000 calls/mo (~33/day), JSearch free tier ~200/mo. Must fetch-on-schedule + cache, never call live per student request.
- [ ] **No TTL primitive exists anywhere in the codebase.** The one cache that exists (`role_research_cache.json`) has no timestamp field — would need to be built from scratch for posting data, which goes stale in days not years.
- [ ] **Cache architecture won't scale as-is even once built.** Flat single-file read-modify-write, no locking under `WEB_CONCURRENCY > 1`. Fine at 15 roles; wrong shape for one-to-many posting data.

## 🟢 Academic Record — term structure (Phase 1 audited and built, not yet merged)

Full audit complete (2026-08-11) and Phase 1 implementation built and staged (2026-08-11), not yet committed. Key findings/decisions, for reference:

- **Schema:** terms live in `academic_terms` (per-student rows: label, year, season, sequence), joined to `course_records` via `term_id`. `course_records.status` has a live DB CHECK, currently `{'completed', 'in_progress'}` only — no 'planned' value exists.
- **Decision made:** planned courses get a **separate `planned_courses` table**, not a third `course_records.status` value — this avoids the `course_records_student_term_course_key` unique-index collision, where a real transcript row could silently lose to a stale planned placeholder under the old approach.
- **TAMU term dates:** hardcoded per-year table, sourced from TAMU's official academic calendar PDF (verified by reading the PDF text directly, not a search summary — one intermediate summary source had the wrong date for Spring 2027).
- **SMU term dates:** fetched live from Coursedog's unauthenticated terms endpoint, snapshotted (not called live at runtime) into `data/reference/smu_term_dates.json`. 16 real terms imported for 2026-2027, including first-class January/May/August intersessions. Coursedog's unflagged far-future placeholder rows (e.g., Fall 2027 shown as raw month boundaries) were correctly excluded from the import window.
- **Status:** ~~migrations written but NOT applied to production~~ — **applied and live as of 2026-08-12.** `supabase migration list --linked` shows `20260811120000` (academic_term_dates), `20260811120100` (planned_courses) and `20260811120200` (course_catalog_search) all present remotely, local and remote in sync with no drift. SMU's `--push` has also run (`2a9909f`): 16 coursedog rows are live in `academic_term_dates`, carrying `source_last_checked` 2026-08-12, and the committed snapshot matches them byte-for-byte apart from the re-read stamps.
- **Explicitly deferred to Phase 2:** reconciliation logic for what happens when a real transcript arrives for a course a student had marked "planned" — this needs its own careful pass, not bolted onto Phase 1.
- [x] ~~Commit the staged Phase 1 work, apply migrations, run SMU `--push`, wire up frontend against live data.~~ — all four done and merged to main 2026-08-12: schema (`7f17185`), backend (`a95e417`), frontend term dropdown and planned-course search (`fe5f395`, `dd69e72`), SMU push (`2a9909f`), via PRs #40 and #42.

## ✅ Confirmed working / not actually broken (don't re-investigate)

- GAP's Tavily-backed live role research (`role_research_agent.py`) — genuinely live, timeout-bounded, injection-bounded, fails safe to static, 15 roles cached.
- Demo-analysis cache (`data/demo_cache/`) infrastructure — the old "failed entries served as successes" bug is confirmed fixed.
- The O*NET *data itself* isn't fake — real O*NET 30.3, correctly rescaled. It's a coverage mismatch, not a correctness bug.
- **CI gate is live and working.** No direct-to-main pushes by anyone since 2026-08-09; all subsequent PRs (#23 through #39) landed as proper merge commits with passing checks.
- **FIT/GAP/SHIFT grounding, `validate_data` conflict, and demo-cache fabrication** — all resolved and merged to main as of 2026-08-12 (PRs #37, #38, #39). See 🟠 section above for specifics. Don't re-audit from scratch; the known residuals are documented there.

## 🟢 Agentic architecture — proposed, not started

### Runtime foundation

- [x] Canonical `AgentContext` and shared bounded `AIRuntime` for authenticated FIT/GAP/SHIFT.
- [x] Strict typed FIT/GAP/SHIFT output contracts with one bounded structured repair.
- [x] Canonical authenticated stateless Chat with validated text output and AI concurrency enforcement.
- [x] Versioned, safe in-memory invocation traces plus deterministic evaluation scenarios and comparison support (Phase B1).
- [x] B2 live-baseline readiness blockers: transient outputs are narrowly ignored, live scenarios carry distinct typed synthetic inputs, and SHIFT has three meaningful live cases.
- [x] B2 reviewability blockers: ignored eval artifacts retain validated output, safe grounding/research accounting, stage timing, and interruption-safe incremental results.
- [x] B2R harness blocker: align the live adapter's `research_summary.research_ms` with the strict typed review-artifact contract and cover live-shaped serialization end to end.
- [x] Phase C1 deterministic course foundation: institution-scoped local catalog search/lookup, trusted completed/planned status, conservative prerequisite and eligibility checks, provenance, and read-only future-agent tools.
- [x] Phase C2 bounded Course Discovery Agent: deterministic O*NET career needs, four C1-only read tools, strict observed-course proposals, unavoidable final verifier, authenticated trusted scope, safe traces, and offline evaluation coverage.
- [x] C2R.1 live-evaluation harness blocker: Course Discovery is a first-class eval feature with a separate six-case controlled suite, dual live opt-in, synthetic trusted contexts, production-path mocked coverage, incremental ignored artifacts, and typed result/trace reload validation.
- [ ] Run a controlled C2 live evaluation and tune course-recommendation quality from reviewed artifacts; implementation made zero live provider calls.
- [ ] Course degree applicability and term offering/section/seat availability remain unresolved; no authoritative degree-planning or schedule model exists.
- [ ] Advisor orchestration remains proposed; do not grant course-write or registration authority.
- [ ] Run and review the controlled B2 live baseline (12 synthetic evaluations; explicit paid/network opt-in required).
- [ ] Phase B2: choose and review durable trace storage/retention before enabling production persistence. Cost estimation remains deferred until reliable repository-controlled model pricing exists.

- `role_research_agent.py` is the one real agent in the codebase (bounded tool loop, Tavily, timeout/injection bounds, cache-first). Copy this pattern, don't reinvent it.
- FIT/GAP/SHIFT/PCA are single-shot LLM calls (`CareerFeatureRunner`) — no tool use, no loop. Chat is session-only today.

Proposed agents, roughly in order of leverage:

- [ ] **Orchestrator Agent** — runs FIT/GAP/SHIFT/PCA together, synthesizes one coherent narrative instead of four disjoint outputs.
- [ ] **Market Intelligence Agent** — owns the job-posting fetch/cache/refresh cycle. Scheduled, not request-triggered.
- [ ] **Course Planning Agent** — cross-references `course_catalog` + transcript + GPA + GAP's skill gaps → recommends actual next-semester courses. Now has a natural home once Phase 1's `planned_courses` table lands.
- [ ] **Advisor Agent (persistent chat)** — existing chat + cross-session memory + tool access to the other agents' outputs.

## 🟢 Student memory system — proposed, not started

- **Session memory** (exists) vs. **longitudinal memory** (doesn't exist — target role changes, closed skill gaps, corrections that shouldn't re-flag).
- [ ] Design a `student_events` / `student_memory` table: student_id, fact, source, confidence, first_seen, last_confirmed.
- [ ] Feature runners write to it when they detect something durable.
- [ ] Advisor Agent reads from it via tool-calling, not by re-deriving from scratch.

## 🔵 Bigger picture — process & product gaps

- [ ] **Canvas integration is still mocked.** The academic side is fake for every real student while career data (resume/transcript) is now genuinely real. This asymmetry gets worse, not better, once real students sign up.
- [x] ~~No CI gate before deploy~~ — resolved 2026-08-10. All PRs since have gone through it cleanly.
- [ ] **No end-to-end smoke test.** 820+ unit tests, zero tests walking the real signup→provision→upload→confirm→run-a-feature flow against live/staging. More urgent than before: post-confirm flow, document processing states, and the career profile redesign all shipped to production, and the test account used for manual dry-runs was deleted.
- [ ] **PCA (Professor Comment Analyzer) has never been audited this session.** Every other feature turned out shakier than it looked on inspection. PCA's data source (Canvas) is mocked, so it may have the same fabrication problem FIT had.
- [ ] **Design consistency pass, once the review screen pattern settles.** Worth checking whether FIT/GAP/SHIFT displays and the GPA view still look like the old generic-form aesthetic. Note: the career-profile section on the authenticated dashboard was reordered 2026-08-12 (analysis panels now above the profile, matching the demo page) — worth including in this pass.
- [ ] **Surface data provenance to students, not just internally.** Real `catalog_year` / `source_last_checked` fields exist but never reach the UI.
- [ ] **`authenticatedDashboardPreview.tsx` doesn't wire up institution theming.** The harness substitutes its own `AuthContext.Provider value`, so `institutionTheme.ts`'s effects never run and every preview renders with the neutral `:root` accent regardless of `?institution=`. Confirmed `institutionTheme.ts` itself is correct — driving it directly with TAMU's `#500000` produces the expected tokens. Harness-only gap. Low priority: previews stay functionally useful, just not visually representative of a themed institution. Found 2026-08-12 verifying the profile-completion modal.
- [ ] **Stale `CampusIQ`/`campus_iq` brand-string leftovers found post-rename.** Confirmed remaining as of the last full sweep:
  - `transcript/parser.py:205` — `"You are Campus IQ."` ships to the model at runtime. Highest priority — it's model-facing, not just a comment.
  - `gradus_iq_prompt_TRANSCRIPT.md` — 3 brand-string hits
  - `transcript/__init__.py:1` — docstring reference
  - `data/catalog/fetch_smu_catalog.py:65` — `User-Agent: CampusIQ-catalog-fetch/1.0` header string
  - 3 SQL migration files — stale path references inside comments only, inside already-applied migrations. Do not edit applied migrations to fix; track separately if it matters.
  - `.env.example` — `CAMPUSIQ_MODEL_ACADEMIC`/`_CAREER` unread by any code post-rename. Currently harmless (defaults match), but silently misleading.
- [x] ~~Verify `frontend/src/api/resume.ts:5` header name matches backend~~ — resolved. Confirmed 2026-08-12: **not a live auth mismatch**, only a stale comment. The header actually sent is `X-GradusIQ-Proxy-Secret` (`frontend/vite.config.ts:18`, asserted throughout `frontend/tests/proxy.test.mjs`); nothing reads the `CampusIQ` spelling. Comment corrected in `05831c0`.
- [x] ~~`onet-data-load` branch~~ — confirmed with Kasheia and deleted 2026-08-11. Was a strict subset of the grounding work now merged to main.
- [ ] **`ats-fetcher` work is a single point of failure.** Per dev's `STATUS.md`, the fetcher implementation and `skill_terms_review.csv` exist only on one local branch on one machine — untracked corpus, no remote copy, no history anywhere. Accepted risk per the file, but worth confirming whether `skill_terms_review.csv` is reusable before it's the only copy left.
- [ ] **4 grounding-related commits never remapped/merged, deliberately deferred.** From `feat/gap-shift-grounding`, still living only on that branch (pre-rename paths): SHIFT concurrency (`a5b5ae0`, `ThreadPoolExecutor` around `get_role_trends`), 30-day trend-cache expiry (`f1e1635`), `.env` loading in `build_demo_cache.py` (`31cdc5a`), and a generic parse-retry loop in `base.run()` (`48aa9fb`). None were in scope for the FIT/GAP fabrication fix. The retry loop touches `base.py` and will need the same signature care the FIT/GAP work needed if picked up later — though `validate_data` is now settled, which makes it easier than it would have been.

---

## Suggested order

1. ~~Delete the `.pyc` leftovers~~ — non-issue, confirmed cosmetic only
2. ~~Fix FIT grounding~~ — done, merged to main (PR #37, #38, #39)
3. ~~Rebuild the demo cache~~ — done, verified 0/0/0/0 for FIT
4. **Commit and deploy Phase 1** (academic term structure) — migrations written, staged, not yet applied to production. Apply migrations → run SMU `--push` → wire frontend → verify live.
5. Decide the job-posting vendor for real (Adzuna vs JSearch vs drop Lightcast from the plan doc)
6. Build the posting-data cache layer (new, TTL-aware)
7. Wire FIT/SHIFT into real market data once the vendor is chosen — this is the actual fix for the Tavily-mismatch problem, not just prompt-level restraint
8. Add an end-to-end smoke test before the next production deploy
9. Audit PCA — the one core feature never checked this session
10. Clean up stale brand strings, starting with `transcript/parser.py:205`
11. ~~Confirm `frontend/src/api/resume.ts` header name against backend~~ — done, stale comment only, no auth mismatch
12. Extend O*NET role coverage toward full 14/14
