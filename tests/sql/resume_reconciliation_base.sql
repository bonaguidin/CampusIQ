create extension if not exists pgcrypto;
create schema auth;
create role authenticated;
create role anon;

-- Supabase's hosted bootstrap grants EXECUTE on newly created functions
-- directly to anon and authenticated, in addition to the PUBLIC grant Postgres
-- gives by default. Reproduce it here or this harness cannot observe the very
-- posture 20260812180000 exists to correct: a SECURITY DEFINER function that
-- revokes PUBLIC still leaves anon holding a direct grant, and every guard
-- asserting otherwise passes trivially against a vanilla cluster.
alter default privileges in schema public
  grant execute on functions to anon, authenticated;

create function auth.uid() returns uuid
language sql stable
as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;

create table students (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid not null unique,
  name text not null,
  major_current text,
  major_intended text,
  expected_graduation text
    check (expected_graduation is null or expected_graduation ~ '^(Spring|Fall) 20[0-9]{2}$'),
  updated_at timestamptz not null default now()
);

create table career_profiles (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null unique references students(id),
  target_roles text[], interests text[], ai_anxiety_level text,
  skills_technical text[], skills_soft text[],
  source text check (source in ('manual', 'resume_parse', 'transcript_parse')),
  confirmed_at timestamptz,
  updated_at timestamptz not null default now(),
  unique (id, student_id)
);

create table work_experience (
  id uuid primary key default gen_random_uuid(), career_profile_id uuid not null,
  student_id uuid not null, employer text not null, role text, duration text,
  location text, description text, skills_gained text[],
  source text, confirmed_at timestamptz, created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (career_profile_id, student_id) references career_profiles(id, student_id)
);
create unique index work_experience_student_employer_role_key
  on work_experience(student_id, employer, role) nulls not distinct;

create table projects (
  id uuid primary key default gen_random_uuid(), career_profile_id uuid not null,
  student_id uuid not null, name text not null, timeframe text, description text,
  tools text[], source text, confirmed_at timestamptz,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  foreign key (career_profile_id, student_id) references career_profiles(id, student_id),
  unique(student_id, name)
);

create table certifications (
  id uuid primary key default gen_random_uuid(), career_profile_id uuid not null,
  student_id uuid not null, name text not null, issuer text,
  status text check (status is null or status in ('completed', 'in_progress')),
  date text, source text, confirmed_at timestamptz,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  foreign key (career_profile_id, student_id) references career_profiles(id, student_id),
  unique(student_id, name)
);

alter table students enable row level security;
create policy students_owner_all on students for all to authenticated
using (auth.uid() = auth_user_id) with check (auth.uid() = auth_user_id);
grant usage on schema public, auth to authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;
