-- Adds institutions.grade_scale_verified, the gate the transcript parser
-- checks before letting a student CONFIRM parsed course records.
--
-- Not applied. DDL and seeds only.
--
-- ============================================================================
-- WHY THIS COLUMN EXISTS
-- ============================================================================
--
-- Confirming a course_record is what makes it GPA-eligible: gpa.py excludes
-- every row whose confirmed_at is null (academics/gpa.py, "unconfirmed"
-- exclusion reason). So confirmation is the exact moment an institution's
-- grade_point_map stops being reference data and starts producing a number
-- shown to a student. If that map's point values are wrong, the GPA is wrong,
-- and it is wrong silently -- there is no downstream check that would catch
-- it.
--
-- This column gates that moment, and ONLY that moment. Upload, parse, and
-- review stay open for every institution: a student at an institution whose
-- scale has not been verified can still get their transcript read and see the
-- parsed rows. They just cannot promote those rows into GPA math yet. Gating
-- earlier would mean a student cannot even see what we extracted, which
-- punishes them for an internal data-quality gap they have no part in.
--
-- Default false is the safe direction: an institution added later (a transfer
-- school, a dual-enrollment high school, an exam board) is unverified until
-- someone verifies it, rather than silently inheriting confirmability.
--
-- ============================================================================
-- SEED VALUES: BOTH TRUE, AND WHY
-- ============================================================================
--
-- Both existing institutions have a documented verification, so both are
-- seeded true. Recorded here because the obvious reading of the migration
-- history suggests otherwise:
--
--   TAMU -- verified against data/reference/tamu_gpa_rules.md ("Source: Texas
--   A&M University Official Academic Policy"), which is what
--   20260728000103_institution_grading_schema.sql:339 cites for the 5-letter
--   no-plus/minus scale it seeds.
--
--   SMU -- verified 2026-07-28, recorded at
--   20260728035418_natural_key_constraints_and_smu_grades.sql:96-100: "all 12
--   existing SMU rows (A 4.0, A- 3.7, B+ 3.3, B 3.0, B- 2.7, C+ 2.3, C 2.0,
--   C- 1.7, D+ 1.3, D 1.0, D- 0.7, F 0.0) already match SMU's published
--   grade-point scale exactly." That same migration added SMU's 'P' row and
--   documented the deliberate absence of 'A+'.
--
-- THE TRAP: 20260728000103_institution_grading_schema.sql:352-353 still reads
-- "TODO: verify these point values against SMU's official undergraduate
-- catalog / registrar grading policy before production use". That TODO is
-- STALE, not open -- it was resolved by the migration above, six hours later.
-- It survives only because applied migrations are never edited retroactively.
-- Anyone auditing SMU's status by grepping for TODO will reach the wrong
-- conclusion; this comment exists so the next person doesn't re-open a closed
-- question or, worse, flip this seed to false and silently disable
-- confirmation for every SMU student.

alter table institutions
  add column grade_scale_verified boolean not null default false;

comment on column institutions.grade_scale_verified is
  'True when this institution''s grade_point_map point values have been '
  'checked against the registrar''s published grading policy. Checked at '
  'CONFIRM time only -- transcript upload, parse, and review are open '
  'regardless. False means parsed course records can be reviewed but not '
  'promoted to GPA-eligible. Defaults false so a newly added institution is '
  'unverified until someone verifies it. This column is NOT read by '
  'academics/gpa.py: it gates whether rows may become confirmed, not how '
  'confirmed rows are scored.';

-- TAMU: see the header block. Source is data/reference/tamu_gpa_rules.md.
update institutions
set grade_scale_verified = true,
    updated_at = now()
where name = 'Texas A&M University';

-- SMU: see the header block. Verified 2026-07-28, per migration
-- 20260728035418. The stale TODO in 20260728000103 does not apply.
update institutions
set grade_scale_verified = true,
    updated_at = now()
where name = 'Southern Methodist University';
