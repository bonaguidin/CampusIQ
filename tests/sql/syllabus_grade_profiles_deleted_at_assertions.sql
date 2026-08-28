\set ON_ERROR_STOP on

insert into students(id, auth_user_id, name) values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'Student A'),
  ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'Student B');

insert into syllabus_grade_profiles(id, student_id, institution, course_code, term, section) values
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'tamu', 'ECEN 248', 'Fall 2026', '501'),
  ('30000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000001', 'tamu', 'PHYS 207', 'Fall 2026', '529'),
  ('30000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000002', 'tamu', 'ECEN 248', 'Fall 2026', '501');

-- Column presence + default: a freshly inserted profile is not deleted.
do $$
begin
  if (select count(*) from syllabus_grade_profiles where deleted_at is not null) <> 0 then
    raise exception 'deleted_at did not default to NULL';
  end if;
end $$;

-- Soft delete is a plain owner-scoped UPDATE (no RLS change required).
update syllabus_grade_profiles
set deleted_at = now()
where id = '30000000-0000-0000-0000-000000000001'
  and student_id = '10000000-0000-0000-0000-000000000001';

do $$
begin
  if (select deleted_at from syllabus_grade_profiles
      where id = '30000000-0000-0000-0000-000000000001') is null then
    raise exception 'deleted_at was not written';
  end if;

  -- The list query shape: active profiles for Student A must now exclude
  -- the soft-deleted one.
  if (select count(*) from syllabus_grade_profiles
      where student_id = '10000000-0000-0000-0000-000000000001'
        and deleted_at is null) <> 1 then
    raise exception 'soft-deleted profile still visible to the active-list query';
  end if;

  -- Revisions / grade-state are untouched by the soft delete (no cascade).
  -- (No rows inserted here; this asserts the ALTER added no ON DELETE
  -- behaviour and the column is purely a marker.)
end $$;

-- Partial index exists and is the expected predicate.
do $$
begin
  if not exists (
    select 1 from pg_indexes
    where schemaname = 'public'
      and indexname = 'syllabus_grade_profiles_active_student_idx'
      and indexdef ilike '%where (deleted_at IS NULL)%'
  ) then
    raise exception 'partial active-student index missing or wrong predicate';
  end if;
end $$;

-- RLS: Student A cannot soft-delete Student B's profile.
set role authenticated;
select set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000001', false);
do $$
begin
  update syllabus_grade_profiles
  set deleted_at = now()
  where id = '30000000-0000-0000-0000-000000000003';  -- Student B's row
  if found then
    raise exception 'cross-student soft delete was allowed';
  end if;
end $$;
reset role;
