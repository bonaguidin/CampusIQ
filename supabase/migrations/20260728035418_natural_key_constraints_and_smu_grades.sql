-- Follow-up to 20260728000103_institution_grading_schema.sql.
--
-- Two unrelated pieces of follow-up work, bundled here because they
-- landed at the same time:
--   1. Unique constraints/indexes backing the natural keys that
--      scripts/import_students.py upserts on. That script currently
--      does its own application-level check-then-write instead of
--      `ON CONFLICT` specifically because none of these keys existed
--      yet — this migration closes that gap but does not change the
--      importer.
--   2. SMU grade_point_map corrections: an 'P' (pass/fail pass) row,
--      plus comments recording verification of the existing 12 SMU
--      rows and two known gaps that are out of scope for this
--      migration.
--
-- Not applied. DDL only.

-- ============================================================================
-- 1. Unique constraints for the importer's natural keys
-- ============================================================================

-- students(auth_user_id): both columns NOT NULL, so a plain unique
-- constraint is sufficient — no NULL-handling edge case exists here.
alter table students
  add constraint students_auth_user_id_key unique (auth_user_id);

-- student_institutions(student_id, institution_id): both columns
-- NOT NULL, so a plain unique constraint is sufficient. (This is
-- separate from the existing student_institutions_one_home_per_student
-- partial index, which enforces at most one 'home' row per student
-- regardless of institution; this new constraint instead enforces at
-- most one row per (student, institution) pair regardless of
-- relationship type.)
alter table student_institutions
  add constraint student_institutions_student_institution_key
    unique (student_id, institution_id);

-- academic_terms(student_id, sequence): both columns NOT NULL, so a
-- plain unique constraint is sufficient.
alter table academic_terms
  add constraint academic_terms_student_sequence_key unique (student_id, sequence);

-- course_records(student_id, term_id, course_code): term_id is
-- NULLABLE (a course can be recorded with no known term, e.g. exam
-- credit). A plain unique constraint would NOT catch duplicates when
-- term_id is null, because SQL unique constraints treat every NULL as
-- distinct from every other NULL — two rows with the same student_id
-- and course_code but both NULL term_id would NOT violate a plain
-- constraint. `alter table add constraint unique` also cannot express
-- NULLS NOT DISTINCT, so this requires `create unique index`, using
-- NULLS NOT DISTINCT (PostgreSQL 17) to treat NULL term_id values as
-- equal to each other for uniqueness purposes, natively — no COALESCE
-- workaround needed.
--
-- ASSUMPTION FLAGGED: this key assumes a student does not retake the
-- same course_code within the same term. That assumption does NOT hold
-- for repeat-for-credit courses (e.g. independent study, applied music
-- lessons, special topics sections repeated in the same term under one
-- course_code) — a legitimate second enrollment in the same course
-- within the same term would collide with this key and get silently
-- treated as an update of the first attempt by the importer's
-- check-then-write logic, rather than inserted as a second row. This
-- migration does not change the key to address that — flagging it here
-- per instructions rather than redesigning the key.
--
-- This is a DISTINCT issue from SMU's Grade Replacement Repeat policy
-- noted below: a repeat taken in a *different* term does not collide
-- with this key at all (different term_id), so the two gaps do not
-- overlap and neither one's fix substitutes for the other's.
create unique index course_records_student_term_course_key
  on course_records (student_id, term_id, course_code)
  nulls not distinct;

-- certifications(student_id, name): both columns NOT NULL, so a plain
-- unique constraint is sufficient.
alter table certifications
  add constraint certifications_student_name_key unique (student_id, name);

-- work_experience(student_id, employer, role): `role` is NULLABLE (a
-- work-experience entry can omit role). Same NULL-handling gap as
-- course_records above: a plain unique constraint would not catch two
-- rows for the same (student_id, employer) both with NULL role, so this
-- uses `create unique index` with NULLS NOT DISTINCT (PostgreSQL 17) to
-- treat NULL role values as equal to each other natively.
create unique index work_experience_student_employer_role_key
  on work_experience (student_id, employer, role)
  nulls not distinct;

-- projects(student_id, name): both columns NOT NULL, so a plain unique
-- constraint is sufficient.
alter table projects
  add constraint projects_student_name_key unique (student_id, name);

-- ============================================================================
-- 2. SMU grade_point_map corrections
-- ============================================================================

-- Verification (2026-07-28, read-only query against the live database):
-- all 12 existing SMU rows (A 4.0, A- 3.7, B+ 3.3, B 3.0, B- 2.7, C+ 2.3,
-- C 2.0, C- 1.7, D+ 1.3, D 1.0, D- 0.7, F 0.0) already match SMU's
-- published grade-point scale exactly. No corrections needed to those
-- rows -- nothing below touches them.

-- ADD: 'P' (pass/fail pass) row.
-- Unlike the existing W and I rows -- which have counts_toward_credit
-- false because withdrawing or leaving a course incomplete earns no
-- credit -- a Pass under SMU's pass/fail option DOES earn credit hours;
-- it is only excluded from the GPA calculation itself. Per SMU's
-- registrar, a Fail taken under the pass/fail option is instead
-- recorded as a literal F and counts toward the GPA normally (no
-- special-cased 'fail' letter needed here; F already exists in the map
-- with counts_toward_gpa/counts_toward_credit both true).
--
-- ON CONFLICT DO NOTHING makes this idempotent against the existing
-- unique (institution_id, letter) constraint from the prior migration --
-- safe to re-run, will not duplicate or error on a second apply.
insert into grade_point_map (institution_id, letter, points, counts_toward_gpa, counts_toward_credit)
select id, 'P', null, false, true
from institutions
where institutions.name = 'Southern Methodist University'
on conflict (institution_id, letter) do nothing;

-- DO NOT ADD: 'A+'.
-- SMU's published grade-point table has no A+ row. Verified against SMU
-- registrar and catalog sources on 2026-07-28. This absence is
-- deliberate, not an oversight: an 'A+' letter grade on an SMU
-- transcript will resolve as unmapped (CampusIQ_career.academics.gpa
-- .resolve_grade) and surface in a course_record's excluded list rather
-- than being silently scored as a 4.0 (or higher). If SMU is later
-- confirmed to award A+ as a distinct grade, that gets its own
-- migration -- not folded in here.

-- KNOWN GAP (comment only -- no schema change in this migration):
-- SMU's Grade Replacement Repeat policy. For courses taken Fall 2017 or
-- later, a student who earned D+ or lower may repeat the course; the
-- second grade replaces the first in the SMU GPA calculation, but the
-- first attempt remains on the transcript. course_records has no column
-- marking a superseded attempt, so CampusIQ_career.academics.gpa
-- .compute_gpa would currently count both attempts' quality points and
-- hours, double-counting a repeated course instead of applying the
-- replacement. Fixing this requires both a new course_records column
-- (e.g. a superseded/excluded-by-repeat flag) and a change to
-- academics/gpa.py's inclusion logic -- neither is done here. Recorded
-- so the gap is not lost, not addressed.
