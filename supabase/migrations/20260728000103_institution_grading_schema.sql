-- Stage 1 of 2: reference tables, student tables, RLS, and grading seeds.
-- DDL and seeds only. Not applied. Student JSON data is NOT migrated by this file.

-- =========================================================================
-- EXTENSIONS
-- =========================================================================

create extension if not exists "pgcrypto";

-- =========================================================================
-- REFERENCE TABLES (public-read, no per-user RLS)
-- =========================================================================

create table institutions (
  id uuid primary key default gen_random_uuid(),
  unitid int null,                          -- IPEDS UnitID; null for exam boards and high schools
  source_system text not null check (source_system in ('ipeds', 'nces', 'exam_board', 'manual')),
  name text not null,
  canvas_host text null,
  catalog_base_url text null,
  uses_plus_minus boolean not null default true,
  transfer_grades_count_toward_gpa boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table grade_point_map (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references institutions (id),
  letter text not null,
  points numeric(3, 2) null,                -- null for non-scoring grades (W, I, P)
  counts_toward_gpa boolean not null,
  counts_toward_credit boolean not null,
  unique (institution_id, letter)
);

-- =========================================================================
-- STUDENT TABLES (RLS: a student reads and writes only their own rows)
-- =========================================================================

create table students (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid not null,               -- links to auth.users
  name text not null,
  classification text null,
  major_current text null,
  major_intended text null,
  expected_graduation text null,
  onboarding_stage int null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
  -- NOTE: no gpa column. GPA is always derived.
);

create table student_institutions (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students (id),
  institution_id uuid not null references institutions (id),
  relationship text not null check (relationship in ('home', 'transfer', 'dual_enrollment', 'prior')),
  created_at timestamptz not null default now()
);

-- Exactly one 'home' institution per student.
create unique index student_institutions_one_home_per_student
  on student_institutions (student_id)
  where relationship = 'home';

create table academic_terms (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students (id),
  institution_id uuid not null references institutions (id),
  label text not null,
  year int not null,
  season text not null,
  sequence int not null,
  created_at timestamptz not null default now()
);

create table course_records (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students (id),
  term_id uuid null references academic_terms (id),
  institution_id uuid null references institutions (id),   -- where earned
  course_code text not null,
  title text null,
  credit_hours numeric(4, 2) not null,
  letter_grade text null,                                  -- null for exam credit
  credit_type text not null check (credit_type in ('resident', 'transfer', 'exam', 'dual_enrollment')),
  counts_toward_credit boolean not null,
  counts_toward_gpa boolean not null,
  status text not null check (status in ('completed', 'in_progress')),
  source text not null check (source in ('transcript_parse', 'manual', 'canvas')),
  exam_source text null,
  exam_score int null,
  confirmed_at timestamptz null,                           -- unconfirmed rows excluded from GPA
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table career_profiles (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null unique references students (id),
  target_roles text[] null,
  interests text[] null,
  career_goals text null,
  geographic_preference text null,
  ai_anxiety_level text null,
  skills_technical text[] null,
  skills_soft text[] null,
  ai_exposure text null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, student_id)
);

-- Child tables of career_profiles.
-- skills_technical, skills_soft, and ai_exposure are flattened from the
-- nested career.skills_self_reported object in the source JSON
-- (skills_self_reported.technical, .soft, .ai_exposure). The API
-- serialization layer is responsible for re-nesting these into
-- skills_self_reported when building prompt payloads, so the
-- FIT/GAP/SHIFT prompt files require no changes. All other career
-- column names do match the source JSON exactly.

create table certifications (
  id uuid primary key default gen_random_uuid(),
  career_profile_id uuid not null,
  student_id uuid not null,
  name text not null,
  issuer text null,
  status text null,
  date text null,
  created_at timestamptz not null default now(),
  foreign key (career_profile_id, student_id)
    references career_profiles (id, student_id) on delete cascade
);

create table work_experience (
  id uuid primary key default gen_random_uuid(),
  career_profile_id uuid not null,
  student_id uuid not null,
  employer text not null,
  role text null,
  duration text null,
  location text null,
  description text null,
  skills_gained text[] null,
  created_at timestamptz not null default now(),
  foreign key (career_profile_id, student_id)
    references career_profiles (id, student_id) on delete cascade
);

create table projects (
  id uuid primary key default gen_random_uuid(),
  career_profile_id uuid not null,
  student_id uuid not null,
  name text not null,
  timeframe text null,
  description text null,
  tools text[] null,
  created_at timestamptz not null default now(),
  foreign key (career_profile_id, student_id)
    references career_profiles (id, student_id) on delete cascade
);

-- =========================================================================
-- ROW LEVEL SECURITY
-- =========================================================================

-- Reference tables: public read for authenticated users, no per-user RLS.
alter table institutions enable row level security;
alter table grade_point_map enable row level security;

create policy institutions_read_authenticated
  on institutions for select
  to authenticated
  using (true);

create policy grade_point_map_read_authenticated
  on grade_point_map for select
  to authenticated
  using (true);

-- Student tables: a student reads and writes only their own rows.
alter table students enable row level security;
alter table student_institutions enable row level security;
alter table academic_terms enable row level security;
alter table course_records enable row level security;
alter table career_profiles enable row level security;
alter table certifications enable row level security;
alter table work_experience enable row level security;
alter table projects enable row level security;

create policy students_owner_all
  on students for all
  to authenticated
  using (auth.uid() = auth_user_id)
  with check (auth.uid() = auth_user_id);

create policy student_institutions_owner_all
  on student_institutions for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = student_institutions.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = student_institutions.student_id
        and students.auth_user_id = auth.uid()
    )
  );

create policy academic_terms_owner_all
  on academic_terms for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = academic_terms.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = academic_terms.student_id
        and students.auth_user_id = auth.uid()
    )
  );

create policy course_records_owner_all
  on course_records for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = course_records.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = course_records.student_id
        and students.auth_user_id = auth.uid()
    )
  );

create policy career_profiles_owner_all
  on career_profiles for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = career_profiles.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = career_profiles.student_id
        and students.auth_user_id = auth.uid()
    )
  );

create policy certifications_owner_all
  on certifications for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = certifications.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = certifications.student_id
        and students.auth_user_id = auth.uid()
    )
  );

create policy work_experience_owner_all
  on work_experience for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = work_experience.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = work_experience.student_id
        and students.auth_user_id = auth.uid()
    )
  );

create policy projects_owner_all
  on projects for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = projects.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = projects.student_id
        and students.auth_user_id = auth.uid()
    )
  );

-- =========================================================================
-- SEEDS
-- =========================================================================

-- IPEDS UnitIDs verified against NCES IPEDS institution profile pages
-- (nces.ed.gov/ipeds/institution-profile/228723 and
-- nces.ed.gov/ipeds/datacenter/institutionprofile.aspx?unitId=228246).
insert into institutions (unitid, source_system, name, canvas_host, catalog_base_url, uses_plus_minus, transfer_grades_count_toward_gpa)
values
  (228723, 'ipeds', 'Texas A&M University', 'canvas.tamu.edu', 'https://catalog.tamu.edu/undergraduate/course-descriptions/', false, false),
  (228246, 'ipeds', 'Southern Methodist University', null, null, true, false);

-- TAMU grade points: no plus/minus, per data/reference/tamu_gpa_rules.md.
insert into grade_point_map (institution_id, letter, points, counts_toward_gpa, counts_toward_credit)
select id, letter, points, counts_toward_gpa, counts_toward_credit
from institutions
cross join (values
  ('A', 4.00::numeric(3,2), true, true),
  ('B', 3.00::numeric(3,2), true, true),
  ('C', 2.00::numeric(3,2), true, true),
  ('D', 1.00::numeric(3,2), true, true),
  ('F', 0.00::numeric(3,2), true, true)
) as g(letter, points, counts_toward_gpa, counts_toward_credit)
where institutions.name = 'Texas A&M University';

-- SMU grade points: full plus/minus 4.0 scale.
-- TODO: verify these point values against SMU's official undergraduate
-- catalog / registrar grading policy before production use.
insert into grade_point_map (institution_id, letter, points, counts_toward_gpa, counts_toward_credit)
select id, letter, points, counts_toward_gpa, counts_toward_credit
from institutions
cross join (values
  ('A',  4.00::numeric(3,2), true, true),
  ('A-', 3.70::numeric(3,2), true, true),
  ('B+', 3.30::numeric(3,2), true, true),
  ('B',  3.00::numeric(3,2), true, true),
  ('B-', 2.70::numeric(3,2), true, true),
  ('C+', 2.30::numeric(3,2), true, true),
  ('C',  2.00::numeric(3,2), true, true),
  ('C-', 1.70::numeric(3,2), true, true),
  ('D+', 1.30::numeric(3,2), true, true),
  ('D',  1.00::numeric(3,2), true, true),
  ('D-', 0.70::numeric(3,2), true, true),
  ('F',  0.00::numeric(3,2), true, true)
) as g(letter, points, counts_toward_gpa, counts_toward_credit)
where institutions.name = 'Southern Methodist University';

-- W (withdrawal) and I (incomplete): non-scoring for both institutions.
-- 'I' is a non-terminal placeholder expected to be updated to a real
-- letter grade once the course resolves; transcript parsing must not
-- treat an 'I' row as a final grade.
insert into grade_point_map (institution_id, letter, points, counts_toward_gpa, counts_toward_credit)
select id, letter, null, false, false
from institutions
cross join (values ('W'), ('I')) as g(letter)
where institutions.name in ('Texas A&M University', 'Southern Methodist University');
