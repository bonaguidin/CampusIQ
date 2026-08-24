-- Adds a course_code join path to requirement_group_option_courses, for
-- schools with no Coursedog backing (TAMU today, any future
-- non-Coursedog school later). Purely additive: SMU's existing
-- coursedog_group_id-based rows and the evaluator's behavior against them
-- are unaffected -- see GradusIQ_career/course_discovery/
-- requirement_satisfaction.py and GradusIQ_career/
-- requirement_satisfaction_fetch.py for the accompanying (separate,
-- not-yet-applied) code changes.
--
-- WHY A NEW COLUMN, NOT unresolved_course_ref: unresolved_course_ref means
-- "a Coursedog ID that failed to resolve against course_catalog" -- a
-- specific, already-load-bearing meaning the requirement-satisfaction
-- evaluator treats as a permanently dead reference (see
-- requirement_satisfaction.py's test_unresolved_course_ref_never_
-- satisfies_an_and_option). TAMU has no Coursedog ID at all to fail to
-- resolve -- its course references are plain course_catalog.code strings
-- from the start (planning-docs/degree-planner-spec.md §8.4 confirmed
-- course_catalog.coursedog_group_id is null on every TAMU row). Reusing
-- unresolved_course_ref for this would both be semantically wrong and
-- would make every TAMU requirement permanently unsatisfiable regardless
-- of a student's real transcript -- exactly the failure mode this
-- migration exists to avoid.
--
-- Not applied. DDL only.
--
-- ============================================================================
-- VERIFICATION (2026-08-23, against the live linked database via the
-- secret-key REST client -- same project as prior migrations in this
-- family; NO direct Postgres connection string is available in this
-- session's .env, unlike 20260819160000's pg_constraint introspection, so
-- the constraint's exact text below is taken from
-- 20260818130000_smu_requirement_skeleton.sql's CREATE TABLE (applied,
-- unedited since) rather than freshly queried -- flagged as a real gap
-- versus the prior migration's verification standard, not glossed over)
-- ============================================================================
--
-- 1. `supabase migration list --linked` confirms 20260818130000 is applied
--    both locally and remotely -- this migration is a new delta, per this
--    session's "never edit an applied migration in place" rule, not an
--    edit to 20260818130000.
--
-- 2. requirement_group_option_courses has no course_code column today
--    (secret-key `select * limit 3`, live 3 sample rows) -- columns
--    present: id, requirement_group_option_id, coursedog_group_id,
--    unresolved_course_ref. No name collision for the new column.
--
-- 3. Every existing row already satisfies "exactly one of two" set --
--    confirmed by counting, not assumed:
--
--      total rows                                67
--      coursedog_group_id is not null            65
--      unresolved_course_ref is not null           2
--      65 + 2 = 67 -- no row has both or neither.
--
--    Backfill is therefore a genuine no-op: the new course_code column is
--    nullable and every existing row keeps course_code null, which still
--    satisfies "exactly one of the three" below (their existing
--    coursedog_group_id or unresolved_course_ref value is unchanged).
--
-- 4. RLS / anon-grant posture: this migration only adds a column and
--    replaces a CHECK constraint -- no new table, no policy change, no
--    grant change. The existing requirement_group_option_courses_
--    read_public policy and the anon revoke from 20260818130000 apply
--    unchanged to the new column.
--
-- ============================================================================

alter table requirement_group_option_courses
  add column course_code text null;

comment on column requirement_group_option_courses.course_code is
  'A plain course_catalog.code value (e.g. "CHEM 107"), for schools with '
  'no Coursedog backing -- application-level join on '
  '(course_catalog.institution_id, course_catalog.code), same '
  'no-foreign-key posture as coursedog_group_id. May be a "/"-joined '
  'cross-listing string (e.g. "ENGR 216/PHYS 216") when the source lists '
  'the same course under two department codes -- see '
  'requirement_satisfaction_fetch.py''s resolution logic for how each '
  'half is checked against course_catalog independently, since '
  'course_catalog stores cross-listed TAMU courses as separate rows, not '
  'a combined code.';

alter table requirement_group_option_courses
  drop constraint requirement_group_option_courses_exactly_one_ref;

alter table requirement_group_option_courses
  add constraint requirement_group_option_courses_exactly_one_ref
  check (
    (
      (case when coursedog_group_id is not null then 1 else 0 end)
      + (case when unresolved_course_ref is not null then 1 else 0 end)
      + (case when course_code is not null then 1 else 0 end)
    ) = 1
  );

comment on constraint requirement_group_option_courses_exactly_one_ref
  on requirement_group_option_courses is
  'Exactly one of coursedog_group_id, unresolved_course_ref, course_code '
  'is set -- extended from "exactly one of two" (20260818130000) to '
  '"exactly one of three" by this migration. Still mutually exclusive, '
  'not "any combination": each row has exactly one join-key shape.';

-- Lookup path the requirement-satisfaction fetch layer needs: "which
-- requirement groups does completing course X (by plain code) count
-- toward" -- same rationale as 20260818130000's coursedog_group_id index.
create index requirement_group_option_courses_course_code_idx
  on requirement_group_option_courses (course_code)
  where course_code is not null;
