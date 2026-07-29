-- Repeat-policy support: closes the "KNOWN GAP" flagged at the bottom of
-- 20260728035418_natural_key_constraints_and_smu_grades.sql (SMU's Grade
-- Replacement Repeat policy) and also covers TAMU Student Rule 10.22 (a
-- repeat of a B-or-better course excluded from the degree audit, though
-- NOT from the cumulative GPA -- see the repeat_policy seed values below).
--
-- Verification (2026-07-29, read-only queries against the live database):
--   - institutions has exactly the two expected rows: Texas A&M University
--     (id 75d68331-91d2-47e8-9671-2a3b065955d0) and Southern Methodist
--     University (id 6b180bbf-66d7-4aef-b8c6-2ae534c78e9a).
--   - course_records has no column named excluded_from_gpa_by or
--     repeat_policy (checked via the PostgREST OpenAPI schema listing:
--     id, student_id, term_id, institution_id, course_code, title,
--     credit_hours, letter_grade, credit_type, counts_toward_credit,
--     counts_toward_gpa, status, source, exam_source, exam_score,
--     confirmed_at, created_at, updated_at).
--   - institutions likewise has no repeat_policy column (id, unitid,
--     source_system, name, canvas_host, catalog_base_url, uses_plus_minus,
--     transfer_grades_count_toward_gpa, created_at, updated_at,
--     brand_primary_hex, brand_rail_hex, brand_on_primary_hex).
--
-- Not applied. DDL and seeds only.

-- ============================================================================
-- 1. course_records.excluded_from_gpa_by
-- ============================================================================

-- This record is excluded from GPA because of the referenced record.
-- Direction-neutral by design -- it covers both SMU's grade replacement
-- (first attempt excluded by the second) and TAMU Rule 10.22 (a repeat of
-- a B-or-better course excluded by the original). The excluded record
-- remains on the transcript and still counts toward earned credit where
-- its grade earned credit.
alter table course_records
  add column excluded_from_gpa_by uuid null references course_records (id);

alter table course_records
  add constraint course_records_excluded_from_gpa_by_not_self
    check (excluded_from_gpa_by is distinct from id);

-- ============================================================================
-- 2. institutions.repeat_policy
-- ============================================================================

-- Tells the transcript parser and review UI which policy applies when a
-- course is repeated. academics/gpa.py does NOT read this column -- gpa.py
-- honors excluded_from_gpa_by regardless of institution, so policy
-- enforcement (deciding which record's excluded_from_gpa_by to set) stays
-- with whoever sets the column.
alter table institutions
  add column repeat_policy text null
    check (repeat_policy in ('all_attempts_count', 'latest_replaces'));

-- TAMU: per Student Rule 10.21, cumulative GPA includes all graded
-- courses; the highest-grade rule applies only to the degree audit.
update institutions
set repeat_policy = 'all_attempts_count'
where name = 'Texas A&M University';

-- SMU: per SMU registrar, a repeat of a D+ or lower taken Fall 2017 or
-- later replaces the original in the SMU GPA.
update institutions
set repeat_policy = 'latest_replaces'
where name = 'Southern Methodist University';
