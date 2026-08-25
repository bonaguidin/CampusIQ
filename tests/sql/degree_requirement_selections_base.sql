create extension if not exists pgcrypto;
create schema auth;
create role authenticated;
create role anon;
create role service_role bypassrls;

create function auth.uid() returns uuid
language sql stable
as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;

create table students (
  id uuid primary key,
  auth_user_id uuid not null unique
);

create table programs (
  id uuid primary key
);

create table requirement_groups (
  id uuid primary key,
  program_id uuid not null references programs(id),
  coursedog_rule_id text not null,
  unique(program_id, coursedog_rule_id)
);

grant usage on schema public, auth to authenticated, anon, service_role;
grant select on students, programs, requirement_groups to authenticated;

