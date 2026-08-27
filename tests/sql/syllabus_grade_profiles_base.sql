create extension if not exists pgcrypto;
create schema auth;
create role authenticated;
create role anon;

alter default privileges in schema public
  grant execute on functions to anon, authenticated;

create function auth.uid() returns uuid
language sql stable
as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;

create table students (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid not null unique,
  name text not null,
  updated_at timestamptz not null default now()
);

alter table students enable row level security;
create policy students_owner_all on students for all to authenticated
using (auth.uid() = auth_user_id) with check (auth.uid() = auth_user_id);

grant usage on schema public, auth to authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;
