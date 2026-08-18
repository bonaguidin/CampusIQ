-- Add an explicit 'dropped' status to course_records, for the semester
-- lifecycle work (PLANNED -> IN PROGRESS -> COMPLETED, with an explicit exit
-- for withdrawal).
--
-- WHY ADDITIVE-ONLY
-- ------------------
-- course_records.status already carries a CHECK constraint restricting it to
-- ('completed', 'in_progress') (20260728000103_institution_grading_schema.sql:91).
-- Withdrawing from an in-progress course must not mean deleting the row --
-- that would destroy history a student may need later (repeat detection,
-- academic advising, "why did my hours drop"). An explicit status is the
-- alternative the existing model already supports: gpa.py's compute_gpa
-- scopes strictly to {"completed"} or {"completed", "in_progress"} per mode
-- (academics/gpa.py:147-152), so a 'dropped' row falls outside both scopes
-- automatically -- no new exclusion branch needed there. counts_flags in
-- transcript/store.py already returns (False, False) for any status other
-- than 'completed' (transcript/store.py:166-167), so a dropped row's
-- informational counts_toward_credit/counts_toward_gpa flags fall out
-- correctly too.
--
-- Constraints are dropped and recreated by name (not ALTER ... ADD VALUE,
-- which is for native enum types -- this column is plain text with a CHECK).
alter table course_records
  drop constraint course_records_status_check;

alter table course_records
  add constraint course_records_status_check
  check (status in ('completed', 'in_progress', 'dropped'));

comment on constraint course_records_status_check on course_records is
  'planned courses live in planned_courses, not here (20260811120100). '
  'dropped is an explicit withdrawal, added for the term-lifecycle '
  'promotion/finalization flow (20260817220000) -- it is excluded from both '
  'GPA modes and from earned/gpa hours by academics/gpa.py''s existing scope '
  'sets, with no code change required there.';
