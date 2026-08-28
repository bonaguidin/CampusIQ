# Syllabus Grade-Profile Review — Redesign Spec

_Companion to PR #54 (syllabus grade-profile feature). This replaces the flat
"Still Needs Your Review" list with three separate, purpose-built surfaces._

---

## 1. Problem with current behavior

The current screen puts every unresolved item — genuine ambiguities, missing
data, and informational rules alike — into one flat list with a bare `×`
dismiss button. Three different problems are being treated as one:

| Item type | Example | Current treatment | Problem |
|---|---|---|---|
| Genuine ambiguity | B/C cutoffs overlap (80–90 vs 70–80) | Flagged with `!`, dismissible | Student can't actually resolve it here |
| Missing extractable data | "Number of assessments: Unknown" | Blocks the category from being usable | Forces per-assessment entry the syllabus never provided |
| Informational rule, correctly extracted | "No late homework accepted" | Shown as a blocking review item with an "Ignore this rule for What-If calculations" button | It's not ambiguous, not missing, and not something to "ignore" — it's just a fact the student should see while calculating |

## 2. Redesign — three surfaces

### A. Clarifying Questions (new, shown before the calculator)

Anything the parser genuinely cannot resolve from syllabus text becomes a
question asked directly to the student, answered once, and never shown again
as a review item.

**Trigger conditions** (only these generate a question):
- Two or more letter-grade cutoffs overlap
- A category's weight is stated but assessment count is not, **and** the
  student hasn't yet indicated they'll enter an average directly
- A value CampusIQ extracted with low confidence and could not confirm
  against syllabus text (the current "We couldn't automatically confirm this
  value" items)

**Not a question** — correctly-extracted informational rules (curve, late
work, makeup work) never appear here. They move to surface C.

**Question copy patterns:**

```
Q: Cutoff conflict (proposed default, confirm or override)
"Your syllabus lists B as 80–90 and C as 70–80 — these overlap at 80.
We'll default to the higher grade winning ties, so 80 is a B, not a C.
Sound right?"
[Yes, that's right]  [No, let me set it myself → number input]

Q: Missing assessment count
"How many homework assignments count toward your grade?"
[ number input ]  [I'd rather just enter my current average]

Q: Low-confidence extraction
"We found '{value}' on page {n} but couldn't confirm it's the {field}.
Is this right?"
[Yes, that's correct] [No, let me enter it]
```

Each question resolves to a stored value on the student's grade profile.
Once answered, it's done — it does not resurface on later visits unless the
syllabus is re-uploaded.

**Decided:** cutoff-overlap conflicts always resolve to "higher grade wins
the tie" as the proposed default — the boundary score belongs to the higher
letter grade (e.g. 90 is an A, not a B; 80 is a B, not a C). This is
proposed to the student as a confirm/override, never asked as open
free-text. Applies uniformly across all cutoff pairs in a syllabus, not
just B/C.

### B. Grade Calculator inputs (replaces assessment-by-assessment extraction)

Drop "Number of assessments: Unknown" as a blocker entirely. Per category,
ask for what the student actually has:

```
Homework          Average: [ ___ ]%     (or: add individual scores ▾)
Labs              Average: [ ___ ]%
Midterm Exam      Score:   [ ___ ]%
Final Exam        Score:   [ ___ ]%
```

- Default entry mode is a single average per category — this is what most
  students actually know, and it's strictly better than a syllabus-derived
  assessment count CampusIQ can't reliably produce anyway.
- "Add individual scores" is an optional expand-in-place for students who
  want more precision; not required, no partial-data blocking if they only
  enter some.
- Weights (25% / 25% / 25% / 25%, Total 100%) stay exactly as they render
  today — that part already works and needs no change.

### C. Professor's Rules (new persistent sidebar)

Curve / late work / makeup work rules move out of the review list entirely
and into a reference panel next to the calculator:

```
PROFESSOR'S RULES                                    [always visible]

Curve
Grades will be curved if necessary.
Source: page 4

Late work
No late homework will be accepted.
Source: page 3

Late work
No late lab submission will be accepted.
Source: page 4

Late work
Unexcused late work will not be accepted.
Source: page 4

Makeup work
Work submitted as makeup for an excused absence is not considered late
and is exempt from the late work policy.
Source: page 4
```

- No dismiss button, no "Ignore this rule for What-If" button — these were
  never things to resolve or block on, just information.
- Sourced with page numbers exactly as now, since that provenance is worth
  keeping.
- Stays visible while the student runs What-If scenarios, since "can I turn
  this late assignment in" is exactly the moment they need to see it.

## 3. What gets removed

- The flat "Still Needs Your Review" list (split into A and C above)
- "Number of assessments: Unknown" as a blocking state
- "Ignore this rule for What-If calculations" button (no longer meaningful
  once rules aren't gating anything)
- The bare `×` dismiss affordance (replaced by an actual answer flow in A)

## 4. Data model implications (for Claude Code to verify against the live schema, not assume)

- Clarifying-question answers need somewhere to persist per student per
  syllabus upload — likely new columns/fields on the existing grade-profile
  table rather than a new table, but confirm against what PR #54 actually
  shipped before designing new schema.
- Category input mode (average vs. individual scores) needs a stored flag
  so the UI knows which entry mode to render on return visits.
- Rules panel content is presumably already the same extracted-rules data
  currently feeding the review list — this should be a display change only,
  not a new extraction pass.

## 5. Decisions confirmed after audit (2026-08-28)

1. Reclassifying curve/late-work/makeup findings: add
   non_deterministic_grading_rule, possible_curve, and ambiguous_rule to
   NON_BLOCKING_WARNING_CODES. Existing blocking-assertion tests are
   updated to reflect this, not preserved as-is.
2. Schema for clarifying-question answers: single clarifying_answers
   jsonb column on syllabus_grade_revisions (keyed log), not several
   narrow columns. Trigger guard is a blocklist and does not need
   modification for this column.
3. Cutoff-resolution scope: canonical A-F, rank-adjacent, exact-boundary
   overlaps only. Non-adjacent/multi-way/single-bound overlaps are
   returned unresolved, not guessed at, and single-bound exclusion from
   detection is tracked separately in outstanding-fixes.md rather than
   fixed in this pass.

**Status — backend + schema piece implemented (2026-08-28, branch
`feat/syllabus-review-backend-reclassification`):** migration
`20260828120000_syllabus_grade_revisions_clarifying_answers.sql` (staged,
not applied), the reconciliation reclassification, and the pure
`cutoff_resolution.resolve_cutoff_overlaps` function all landed with tests.
Not yet done and out of scope for that pass: wiring clarifying_answers /
the resolution function into corrections.py or the API response, and all
frontend work (clarifying-questions flow, calculator input change,
Professor's Rules sidebar, removing the "Ignore this rule" button).

## 6. Notes for the Claude Code build prompt

Per existing project discipline:
- **Audit first.** Confirm exactly what PR #54 stored (schema, field names,
  what's already computed vs. rendered) before writing any new code —
  documented intent and live behavior have diverged before on this project.
- Cutoff-overlap resolution logic (§2A) is decided: higher-grade-wins,
  propose-and-confirm. Implement as a pure function over the parsed cutoff
  list so it's testable independent of the question-flow UI.
- Stop-and-report gate if the live grade-profile table doesn't already
  cleanly separate "ambiguous/missing" fields from "informational rules" —
  that split may not exist yet and would need its own migration.
- Thematic commits: schema/migration (if needed) → backend question-trigger
  logic → frontend clarifying-questions flow → frontend calculator input
  change → frontend rules sidebar. Five separable pieces, same pattern as
  PR #54's five-commit structure.
