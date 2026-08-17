# Deterministic course discovery boundary

C1 is read-only software authority. It searches institution-scoped local
catalog snapshots, checks confirmed and planned course evidence, conservatively
evaluates supported prerequisite shapes, and verifies proposed course codes.
It does not call an LLM, the network, Supabase, or a schedule service.

`CourseDiscoveryContext` deliberately combines the unchanged canonical profile
with typed, student-scoped planned-course evidence. Planned courses therefore
do not enter FIT, GAP, SHIFT, or Chat prompts.

The local JSON prerequisite parser preserves a flat list of codes and selected
restriction phrases, not an expression tree. C1 supports a single course and
unambiguous flat AND/OR text only. Mixed logic, minimum grades, corequisites,
major/classification/GPA/approval restrictions, and other natural-language
conditions return `UNRESOLVED`. In-progress prerequisites are unresolved;
planned prerequisites are not satisfied.

No current `GapOutput` field is course-discovery authority. Its gap labels,
strengths, next steps, course/certification suggestions, dates, inferred
experience, and research prose remain model-authored narrative. A future C2
adapter must derive `CareerSkillNeed` values from deterministic role grounding
and confirmed profile evidence, carrying an explicit evidence state.

Eligibility is not degree applicability, term availability, seat availability,
registration permission, or a graduation guarantee. Those remain unknown.
