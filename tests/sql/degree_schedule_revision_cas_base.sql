create extension if not exists pgcrypto;
create schema auth;
create role authenticated;
create role anon;
create role service_role bypassrls;

create function auth.uid() returns uuid language sql stable
as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;

create table institutions (
  id uuid primary key,
  name text not null
);
create table students (
  id uuid primary key,
  auth_user_id uuid not null unique,
  name text not null,
  expected_graduation text,
  updated_at timestamptz not null default now()
);
create table student_institutions (
  id uuid primary key,
  student_id uuid not null references students(id),
  institution_id uuid not null references institutions(id),
  relationship text not null,
  catalog_year text
);
create table programs (
  id uuid primary key,
  institution_id uuid not null references institutions(id),
  catalog_year text not null
);
create table requirement_groups (
  id uuid primary key,
  program_id uuid not null references programs(id),
  coursedog_rule_id text not null,
  name text not null,
  unique(program_id, coursedog_rule_id)
);
create table requirement_group_options (
  id uuid primary key,
  requirement_group_id uuid not null references requirement_groups(id) on delete cascade,
  option_index int not null,
  logic text not null
);
create table requirement_group_option_courses (
  id uuid primary key,
  requirement_group_option_id uuid not null references requirement_group_options(id) on delete cascade,
  coursedog_group_id text,
  unresolved_course_ref text,
  course_code text
);
create table academic_terms (
  id uuid primary key,
  student_id uuid not null references students(id),
  institution_id uuid not null references institutions(id),
  year int not null,
  season text not null
);
create table course_catalog (
  id uuid primary key,
  institution_id uuid not null references institutions(id),
  code text not null,
  title text not null,
  credit_min int not null,
  coursedog_group_id text
);
create table course_records (
  id uuid primary key,
  student_id uuid not null references students(id),
  term_id uuid references academic_terms(id),
  institution_id uuid references institutions(id),
  course_code text not null,
  title text,
  credit_hours numeric not null,
  counts_toward_credit boolean not null,
  status text not null,
  catalog_course_id uuid references course_catalog(id)
);
create table academic_term_dates (
  id uuid primary key,
  institution_id uuid not null references institutions(id),
  year int not null,
  season text not null,
  label text not null,
  start_date date not null,
  end_date date not null
);

grant usage on schema public, auth to authenticated, anon, service_role;
grant select on students, programs, requirement_groups to authenticated;
grant all on all tables in schema public to service_role;
