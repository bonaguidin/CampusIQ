-- Adds planned_courses: courses a student intends to take in a term that has
-- not happened yet.
--
-- Phase 1 of term-organized Academic Record. DDL only.
--
-- ============================================================================
-- VERIFICATION (2026-08-11, read-only against the live linked database)
-- ============================================================================
--
-- 1. No table named planned_courses exists:
--      GET /rest/v1/planned_courses -> HTTP 404 (PGRST205)
--
-- 2. course_records.status is live-constrained to exactly two values, verified
--    behaviourally rather than by reading the migration. An INSERT carrying
--    status='planned' and a student_id that exists in no row (so the foreign
--    key guarantees nothing can be written either way) returns:
--      {"code":"23514","message":"new row for relation \"course_records\"
--       violates check constraint \"course_records_status_check\""}
--    while the same INSERT with status='completed' gets past the CHECK and
--    fails on the FK (23503). So 'planned' is not, and was never, a value
--    course_records could hold.
--
-- ============================================================================
-- WHY A SEPARATE TABLE RATHER THAN A THIRD course_records.status
-- ============================================================================
--
-- course_records means "this happened". Every consumer is built on that:
-- gpa.py scores it, repeats.py reconciles attempts within it, the transcript
-- upsert treats (student_id, term_id, course_code) as an identity that can be
-- safely deduplicated. A planned course is a statement of intent, and it is
-- wrong in a specific, expensive way inside that table:
--
--   course_records_student_term_course_key is UNIQUE on
--   (student_id, term_id, course_code) with NULLS NOT DISTINCT, and
--   store_parsed_transcript upserts with ignore_duplicates=True. A planned
--   CSCE 314 in Fall 2026 therefore occupies the exact key the real graded
--   CSCE 314 will arrive under -- and the real row would be SILENTLY DROPPED,
--   leaving the ungraded placeholder standing in for the actual result.
--
-- A separate table cannot collide with that key, and needs no changes to
-- course_records, its CHECK constraint, its unique index, or gpa.py. Nothing
-- in the GPA path reads this table.
--
-- ============================================================================
-- NO UNIQUE CONSTRAINT, DELIBERATELY
-- ============================================================================
--
-- There is no unique key mirroring course_records_student_term_course_key. A
-- student may add the same course twice, remove it, add it again, or hold two
-- candidate sections of the same course while deciding -- planning is a
-- scratchpad, and a database error is a bad answer to "you already added
-- that". The UI de-duplicates what it displays and disables an add for a
-- course already planned in the selected term; that is a UI affordance, not an
-- invariant, and nothing downstream depends on it holding.
--
-- ============================================================================
-- OUT OF SCOPE: RECONCILIATION (Phase 2)
-- ============================================================================
--
-- Nothing here reacts to a transcript arriving that contains a planned course.
-- No trigger, no foreign key to course_records, no status column tracking
-- fulfilment. A planned row stays exactly as the student left it until
-- something in Phase 2 decides what fulfilment means. Stated explicitly so the
-- absence reads as a decision rather than an oversight.

create table planned_courses (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students (id),
  institution_id uuid not null references institutions (id),
  term_id uuid null references academic_terms (id),
  course_code text not null,
  title text null,
  credit_hours numeric(4, 2) null,
  catalog_course_id uuid null references course_catalog (id),
  created_at timestamptz not null default now()
);

comment on table planned_courses is
  'Courses a student intends to take. Distinct from course_records, which is '
  'what a student actually took: nothing here counts toward GPA, earned '
  'hours, or repeat reconciliation, and no code in GradusIQ_career/academics '
  'reads this table. Deliberately carries no unique key -- see the migration.';

comment on column planned_courses.term_id is
  'The term being planned for. NULLABLE so a student can save a course before '
  'deciding when to take it. Points at the same per-student academic_terms '
  'rows course_records.term_id does, so a term the student has never enrolled '
  'in must be created there first -- which is what makes a planned course '
  'appear under its term in the dropdown alongside real coursework.';

comment on column planned_courses.credit_hours is
  'NULLABLE, unlike course_records.credit_hours which is NOT NULL. A planned '
  'course may be a variable-credit course whose hours the student has not '
  'chosen (course_catalog carries credit_min/credit_max, differing on 11.5% '
  'of rows), and there is no GPA math here that a null would break.';

comment on column planned_courses.catalog_course_id is
  'Set when the course came from catalog search, which is the normal path '
  'here -- unlike course_records, where it is null for every transcript row '
  'the catalog could not match. Still nullable: a student may plan a course '
  'this catalog does not carry, and course_code remains authoritative.';


-- ============================================================================
-- Row level security
-- ============================================================================

-- Student-owned data, so this follows course_records' owner policy shape
-- exactly (20260728000103_institution_grading_schema.sql:236-251) rather than
-- the public-read shape used by the reference tables: a student reads and
-- writes only their own rows, resolved through students.auth_user_id.
--
-- FOR ALL rather than separate policies per command: unlike course_records --
-- whose INSERTs come from the service-role importer and whose confirmed_at is
-- writable only by a gated endpoint -- every write here is the student's own
-- ordinary editing of their own plan. There is no privileged column to
-- protect and no confirmation gate to route around.

alter table planned_courses enable row level security;

create policy planned_courses_owner_all
  on planned_courses for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = planned_courses.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = planned_courses.student_id
        and students.auth_user_id = auth.uid()
    )
  );

-- anon gets no policy at all, so PostgreSQL default-denies every command for
-- it. The grant is stripped as well, for the same reason as the reference
-- tables: policy and grant are independent, and leaving the default
-- `GRANT ALL` in place would mean only the policy stands between anon and a
-- write.

revoke insert, update, delete, truncate on planned_courses from anon;
revoke select on planned_courses from anon;


-- ============================================================================
-- Index
-- ============================================================================

-- The only read pattern is "this student's planned courses, for one term or
-- for all terms" -- issued on every render of the Academic Record tab.
create index planned_courses_student_term_idx
  on planned_courses (student_id, term_id);
