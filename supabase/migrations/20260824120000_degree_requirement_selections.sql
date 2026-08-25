-- Active student choices for structured Degree Schedule requirements.
--
-- This table stores student intent and reconstruction provenance only. A row
-- is never proof that its candidate remains academically valid: every future
-- write/read integration must reconstruct the current candidate evidence and
-- validate the complete cross-requirement combination before applying it.
-- It is deliberately separate from planned_courses, which owns real-term
-- planning intent rather than requirement-choice ownership.

-- PostgreSQL requires a matching unique key for the composite foreign key
-- below. The primary key already makes id unique; this additional key lets the
-- database prove that a requirement_group_id belongs to the stored program_id
-- without duplicating any degree-program structure.
alter table requirement_groups
  add constraint requirement_groups_id_program_id_key unique (id, program_id);

create table degree_requirement_selections (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students (id) on delete cascade,
  program_id uuid not null references programs (id) on delete cascade,
  requirement_group_id uuid not null,
  candidate_id text not null check (btrim(candidate_id) <> ''),
  course_codes text[] not null,
  decision_version text not null
    check (decision_version ~ '^sha256:[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (requirement_group_id, program_id)
    references requirement_groups (id, program_id) on delete cascade,
  unique (student_id, program_id, requirement_group_id),
  check (cardinality(course_codes) > 0),
  check (array_position(course_codes, null) is null),
  check (array_position(course_codes, '') is null)
);

comment on table degree_requirement_selections is
  'One active student choice per structured requirement. candidate_id and '
  'course_codes preserve intent/provenance; current reconstructed candidate '
  'evidence remains the authority for academic validity.';

comment on column degree_requirement_selections.course_codes is
  'Ordered, atomic snapshot of the complete candidate path. A multi-course '
  'candidate is one row with multiple array elements, never one row per course.';

comment on column degree_requirement_selections.decision_version is
  'The Degree Schedule schedule_version accepted when the choice was written. '
  'Historical stale-state provenance, not proof of continuing validity.';

create index degree_requirement_selections_student_program_idx
  on degree_requirement_selections (student_id, program_id);

alter table degree_requirement_selections enable row level security;

-- Students may inspect their own persisted intent, but cannot bypass the
-- future backend's candidate, global-combination, and stale-version checks.
create policy degree_requirement_selections_owner_select
  on degree_requirement_selections for select
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = degree_requirement_selections.student_id
        and students.auth_user_id = auth.uid()
    )
  );

revoke all on degree_requirement_selections from anon;
revoke insert, update, delete, truncate on degree_requirement_selections from authenticated;
grant select on degree_requirement_selections to authenticated;
grant all on degree_requirement_selections to service_role;

