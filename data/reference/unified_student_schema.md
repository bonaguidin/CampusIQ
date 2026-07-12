# Unified Student Profile Schema

This is the foundation contract for Campus IQ. Every feature should read from
one student record that contains both Canvas-derived academic data and
student-entered career data.

## Source Boundary

Canvas-derived fields are refreshed by the Canvas pull/mock data process:

- `student`
- `courses`
- `enrollments`
- `assignments`
- `submissions`
- `examTopicTags`

Student-entered fields are created or updated by onboarding/edit flows:

- `career`

System-generated fields are calculated by Campus IQ:

- `profile_completeness`

## Required Top-Level Keys

Every file in `data/students/` must include:

- `_notes`
- `student`
- `courses`
- `enrollments`
- `assignments`
- `submissions`
- `career`
- `profile_completeness`
- `examTopicTags`
- `_schema_notes`

The validator enforces the feature-critical keys and record counts.

## Student Block

`student` stores the basic identity and academic snapshot:

```json
{
  "id": 601,
  "name": "Jordan Reyes",
  "major": "Business Administration (pre-major)",
  "classification": "Freshman",
  "institution": "Texas A&M University",
  "gpa_current": 3.0
}
```

Future features should depend on these fields for basic personalization,
timeline logic, and GPA-aware academic guidance.

## Academic Blocks

Academic features should use:

- `courses`: active courses for the current term
- `enrollments`: grade and score state by course
- `assignments`: assignment metadata, due dates, points, and states
- `submissions`: student scores and professor comments
- `examTopicTags`: Campus IQ topic tags used by exam gap and study guide features

Professor comment analysis should read from `submissions[].submission_comments`.
Exam gap analysis and study guide generation should combine assignment scores
with `examTopicTags`.

## Career Block

`career` stores onboarding and resume-style information:

```json
{
  "target_roles": [],
  "interests": [],
  "career_goals": "",
  "geographic_preference": "",
  "ai_anxiety_level": "",
  "skills_self_reported": {},
  "certifications": [],
  "work_experience": [],
  "projects": []
}
```

The top-level `skills_self_reported`, `certifications`, `work_experience`, and
`projects` fields are the current canonical resume-style fields. Earlier drafts
included a nested `career.resume` object, but it is not present in the current
student JSON files and should not be treated as required unless the schema is
changed again.

`certifications` may be empty. Work experience and projects should be present
for mock/demo profiles so downstream features can test realistic cases.

## Profile Completeness

`profile_completeness` is a feature gate and dashboard signal:

```json
{
  "academic": 1.0,
  "career": 1.0,
  "overall": 1.0,
  "by_feature": {
    "FIT": {
      "ready": true,
      "required": {}
    },
    "GAP": {
      "ready": true,
      "required": {}
    },
    "SHIFT": {
      "ready": true,
      "required": {}
    }
  }
}
```

For the MVP mock data, all five current profiles should have complete academic
and career sections. Later onboarding flows can lower these values when a real
student skips optional fields.

## Validation

Run the schema and count checks before committing profile changes:

```bash
uv run python data/students/validate_students.py
uv run python data/validate_catalog.py
```

`validate_students.py` checks:

- required top-level keys
- expected counts for the five mock profiles
- required student identity fields
- required career fields
- profile completeness values between `0.0` and `1.0`
- `profile_completeness.by_feature` gates for FIT, GAP, and SHIFT

## Build Rule

New features should not create separate student profile shapes. If a feature
needs a new field, add it to this schema first, update the validator, then build
the feature against the unified record.
