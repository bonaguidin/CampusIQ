-- Adds institutions.repeat_replacement_max_points, the eligibility gate for
-- grade-replacement repeats.
--
-- Not applied. DDL and seeds only.
--
-- ============================================================================
-- WHY A THRESHOLD COLUMN, WHEN repeat_policy ALREADY EXISTS
-- ============================================================================
--
-- 20260729193925 added institutions.repeat_policy with two values,
-- 'all_attempts_count' and 'latest_replaces', and seeded SMU as
-- 'latest_replaces'. The comment directly above that seed reads:
--
--     "SMU: per SMU registrar, a repeat of a D+ or lower taken Fall 2017 or
--      later replaces the original in the SMU GPA."
--
-- The enum carries neither of the two conditions that sentence states. Read
-- literally, 'latest_replaces' means "the latest attempt always wins", which is
-- NOT SMU's policy: a student who earned a B and retook the course anyway --
-- routine for a prerequisite taken for schedule or interest reasons -- has BOTH
-- attempts count. Applying unconditional latest-wins would silently delete a
-- legitimately-counting grade from their GPA, and nothing downstream would
-- catch it.
--
-- So the gap was in the ENCODING, not in the research: the author of
-- 20260729193925 knew the full rule and wrote it down in the same breath as the
-- seed that omits it. This column closes that gap.
--
-- ============================================================================
-- WHY POINTS RATHER THAN A LETTER
-- ============================================================================
--
-- The obvious alternative is a letter column seeded 'D+'. Points are better for
-- two reasons:
--
--   1. Letters are not comparable. Deciding whether 'C-' is "lower than" 'D+'
--      requires an ordering that exists nowhere in the schema; points are
--      already the canonical ordering and are already stored per institution.
--   2. It stays institution-agnostic. An institution on a different scale
--      (percentage, 5.0, pass/fail-heavy) needs no special-casing -- the
--      comparison is always against its OWN grade_point_map.
--
-- Verified against the live seed (20260728000103:363-369): SMU's D+ is exactly
-- 1.30, and the next grade up, C-, is 1.70. A `points <= 1.30` test therefore
-- captures exactly {D+ 1.30, D 1.00, D- 0.70, F 0.00} and nothing else. The
-- 0.40 gap to C- means small future point corrections cannot silently widen the
-- eligible set.
--
-- ============================================================================
-- THE FALL 2017 CUTOFF IS DELIBERATELY NOT A COLUMN
-- ============================================================================
--
-- SMU's policy also requires the repeat be taken Fall 2017 or later. That is
-- not modeled, on purpose: every current undergraduate's coursework postdates
-- it by years, so a column would add a join condition and a migration for a
-- predicate that is true for every row it would ever evaluate. Recorded here so
-- the omission is a decision rather than an oversight. If Campus IQ ever
-- ingests genuinely historical transcripts -- a returning adult learner, a
-- decades-old transfer record -- this becomes real and needs its own column.

alter table institutions
  add column repeat_replacement_max_points numeric(3, 2) null;

comment on column institutions.repeat_replacement_max_points is
  'If set, a repeat under this institution''s repeat_policy only replaces the '
  'earlier attempt when the earlier attempt''s grade_point_map points are <= '
  'this threshold; null means no threshold gating (replace unconditionally, or '
  'not applicable for all_attempts_count). Compared against this institution''s '
  'OWN grade_point_map, never a shared scale. Read by the transcript parser''s '
  'repeat reconciliation, not by academics/gpa.py -- gpa.py honors '
  'course_records.excluded_from_gpa_by regardless of institution, so policy '
  'enforcement stays with whoever sets that column.';

-- SMU: D+ = 1.30 (20260728000103:366). Eligible earlier attempts are therefore
-- D+, D, D-, F.
update institutions
set repeat_replacement_max_points = 1.30,
    updated_at = now()
where name = 'Southern Methodist University';

-- TAMU: left NULL, and it must stay NULL.
--
-- Not an oversight and not "to be filled in later". TAMU's repeat_policy is
-- 'all_attempts_count' (Student Rule 10.21: the cumulative GPA includes every
-- graded attempt), so no replacement ever happens and a threshold has nothing
-- to gate.
--
-- THE TRAP, recorded because the schema actively invites it: the comment on
-- course_records.excluded_from_gpa_by cites "TAMU Rule 10.22 (a repeat of a
-- B-or-better course excluded by the original)" as a motivating case for that
-- column's direction-neutral design. Rule 10.22 excludes such a repeat from the
-- DEGREE AUDIT, not from the cumulative GPA -- as the header of
-- 20260729193925 itself says: "though NOT from the cumulative GPA". Since
-- excluded_from_gpa_by feeds GPA and nothing else, using it to model Rule 10.22
-- would remove a graded attempt that Rule 10.21 requires be counted, i.e. it
-- would corrupt every affected TAMU student's GPA in the name of implementing a
-- TAMU rule. Repeat reconciliation therefore sets NOTHING for
-- 'all_attempts_count', regardless of grades.
