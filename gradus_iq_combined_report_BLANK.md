# Gradus IQ — Combined Report

**{{student.name}}** · {{student.institution}} · Generated {{report_date}}

---

## At a Glance

<!-- FACTUAL — direct pull, no AI. Omit any row whose source field is null/empty. -->

| | |
|---|---|
| **Current major** | {{student.major_current}} |
| **Intended major** | {{student.major_intended}} |
| **Classification** | {{student.classification}} |
| **Current GPA** | {{student.gpa_current}} |
| **Expected graduation** | {{student.expected_graduation}} |
| **Target roles** | {{career.target_roles | join " · "}} |
| **Features run** | {{features_run_summary}} |

---

## The Through-Line

<!-- GENERATED — Career Synthesis step. Requires ≥2 features. OMIT this whole section if <2 features ran. -->
<!-- Purpose: the single integrated insight that ties academic signals to career readiness, stated once, up front. -->
<!-- 1 short paragraph. Second-person voice. This is the demo/judge takeaway line. -->

[SYNTHESIS: opening integrated insight — name the one pattern the rest of the report supports]

---

## Academic

<!-- Each ### block below is INDEPENDENTLY OMITTABLE. If the agent didn't run, drop the entire block — header included. Never leave an empty header. -->

### Professor Comment Analyzer

<!-- GENERATED — Professor Comment Analyzer agent. Grounded in: submissions[].submission_comments -->
<!-- Summary-level: name the recurring theme(s) across courses, cite 2–4 representative comments. Depth lives in the per-feature report. -->

[BLOCK: recurring feedback themes + representative quotes by course]

### Exam Gap Analysis

<!-- GENERATED — Exam Gap Analysis agent. Grounded in: examTopicTags, enrollments[].grades -->
<!-- Summary-level: where points leak, by topic. Surface the pattern, not every data point. -->

[BLOCK: topic-level score patterns + where the gaps cluster]

### What To Do — Study & Course Support

<!-- GENERATED — Study Guide Generator + Course & Cert Recommender agents. -->
<!-- Grounded in: examTopicTags gaps + TAMU course catalog (course rec). -->
<!-- Keep actionable. Flag catalog-dependent lines if the recommender hasn't run. -->

- **Immediate:** [study action targeting the exam gaps above]
- **Next term:** [course-load guidance] *(specific catalog pull inserts here once the recommender runs)*

---

## Career

<!-- Same rule: each ### block independently omittable. -->

### FIT — Role Explorer

<!-- GENERATED — FIT agent. Grounded in: career.target_roles, career.interests, student.major_intended + live/snapshot market data -->
<!-- Summary-level: 3–5 role matches with one-line why-fit each, geography-anchored. -->

[BLOCK: ranked role matches, each with a why-fit line]

### GAP — Readiness Check

<!-- GENERATED — GAP agent. Grounded in: career.skills_self_reported, work_experience, certifications, expected_graduation + O*NET/postings -->
<!-- Structure: strengths → must-close gaps → nice-to-have → runway. Actionable, not diagnostic. -->

**Where you stand strong:**
- [strength]

**Must-close gaps for your target roles:**
- [gap + why it matters to employers]

**Nice-to-have (not urgent):**
- [lower-priority item]

**Your runway:** [time-to-graduation framing tied to expected_graduation]

### SHIFT — Trend-Aware Guidance

<!-- GENERATED — SHIFT agent. Grounded in: career.target_roles, skills_self_reported, ai_exposure + static AI-impact context block -->
<!-- Tone: path-clarity, NOT threat. Structure: what's changing → what stays durable → how to articulate AI fluency. -->

- **What's changing:** [role evolution / AI-tooling expectation]
- **What stays durable:** [automation-resistant fundamentals]
- **How to talk about it:** [AI-articulation coaching]

---

## Integrated Synthesis & Action Plan

<!-- GENERATED — Career Synthesis step. Requires ≥2 features. OMIT if <2 ran. -->
<!-- This is the value-add that makes the report COMBINED, not stapled. Explicitly connect academic signal → career readiness. -->

**The connection:** [name where an academic pattern and a career gap are the same underlying thing]

**Your prioritized next steps:**

1. [highest-leverage move — ideally one that serves both academic + career]
2. [next]
3. [next]
4. [exploration / reassurance note appropriate to classification]

[SYNTHESIS: closing takeaway — direction vs. evidence framing]

---
---

## Template Spec

*Scaffolding for the build team — not part of the student-facing report. Strip everything from this rule down before export.*

### Data provenance

| Section | Source | AI? |
|---|---|---|
| At a Glance | `student` + `career.target_roles` + `profile_completeness` | No — factual |
| Through-Line | Career Synthesis | Yes |
| Professor Comment Analyzer | `submissions[].submission_comments` | Yes |
| Exam Gap Analysis | `examTopicTags`, `enrollments[].grades` | Yes |
| Study & Course Support | Study Guide + Course Recommender (+ TAMU catalog) | Yes |
| FIT / GAP / SHIFT | `career` block + market data | Yes |
| Integrated Synthesis | Career Synthesis | Yes |

### Degradation rules

- **Every `###` block is independently omittable.** Agent didn't run → drop the whole block, header included. Never render an empty header.
- **Synthesis sections (Through-Line + Integrated Synthesis) require ≥2 features.** Only one feature ran → skip both synthesis sections, export the single block plus At a Glance.
- **Minimum viable report:** At a Glance + ≥1 feature block.
- **At a Glance rows** drop individually if their source field is null.

### Heading hierarchy (export keys off this)

- `#` → title → DOCX `Heading 1` / PDF top bookmark
- `##` → major section → DOCX `Heading 2` / PDF section bookmark
- `###` → feature block → DOCX `Heading 3`
- Keep levels consistent — the export script builds bookmarks/TOC/page breaks from heading depth.

### Interpolation tokens

- `{{field.path}}` — direct JSON pull (e.g. `{{student.gpa_current}}`)
- `{{... | join " · "}}` — array joined with a separator
- `[BLOCK: ...]` — a full generated block, replaced by agent output
- `[SYNTHESIS: ...]` — Career Synthesis prose
- `*(... inserts here)*` — conditional content flagged when its source agent hasn't run

### Format proposal to whoever builds the Report Generator (Rep)

This template *is* the proposed Rep output contract: **markdown · second-person voice · headers + bullets · feature blocks as summaries · synthesis as the value-add.** If Rep emits this shape, export is a clean markdown → PDF/DOCX pass. If Rep will emit something else (JSON, structured objects), settle that against this file *before* export is built.
