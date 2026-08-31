-- Soft delete for syllabus grade profiles: a student can remove a
-- syllabus/calculator from their list without destroying the immutable
-- extraction history (syllabus_grade_revisions) or their saved
-- StudentGradeState.
--
-- `deleted_at` is a SEPARATE column, not an overload of review_state --
-- review_state stays purely about extraction/confirmation trust
-- ('needs_review' / 'confirmed' / 'reconfirm_required'), and a profile in
-- any of those states can be soft-deleted.
--
-- No RLS change needed: syllabus_grade_profiles_owner_all is FOR ALL, so
-- the owner-scoped UPDATE that sets deleted_at is already permitted and a
-- non-owner is already blocked.

alter table syllabus_grade_profiles
  add column deleted_at timestamptz;

-- The list screen's only query is
--   select * from syllabus_grade_profiles where student_id = $1
-- and (after this change) `and deleted_at is null`. A partial index keeps
-- that hot path off the soft-deleted rows.
create index syllabus_grade_profiles_active_student_idx
  on syllabus_grade_profiles (student_id)
  where deleted_at is null;
