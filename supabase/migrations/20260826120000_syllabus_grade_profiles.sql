-- Phase 7: persistent syllabus grade profiles, immutable extraction
-- revisions, and saved StudentGradeState.
--
-- Course identity: (student_id, institution, course_code, term, section)
-- as free text, matching GradeModel.course's own shape (all nullable,
-- LLM-extracted strings -- there is no validated catalog course row this
-- data naturally maps to). No uniqueness constraint on that tuple, the
-- same "scratchpad" posture planned_courses already takes for
-- not-yet-completed coursework: a profile's own id is its stable identity;
-- the backend service layer decides whether to reuse or create one.
--
-- syllabus_grade_revisions is the immutable extraction/audit history: one
-- row per distinct ingested source per profile (unique on
-- (profile_id, source_content_hash), giving idempotent re-upload of the
-- same syllabus), never overwritten after insert except for the
-- correction/confirmation columns -- enforced by application code AND by
-- the trigger below, so a stray UPDATE anywhere cannot silently rewrite
-- extraction history.

create table syllabus_grade_profiles (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(id) on delete cascade,
  institution text,
  course_code text,
  term text,
  section text,
  current_revision_id uuid,
  review_state text not null default 'needs_review'
    check (review_state in ('needs_review', 'confirmed', 'reconfirm_required')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index syllabus_grade_profiles_student_idx on syllabus_grade_profiles (student_id);
create index syllabus_grade_profiles_course_idx
  on syllabus_grade_profiles (student_id, institution, course_code, term);

create table syllabus_grade_revisions (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references syllabus_grade_profiles(id) on delete cascade,
  student_id uuid not null references students(id) on delete cascade,

  source_filename text,
  source_content_hash text not null check (source_content_hash ~ '^sha256:[0-9a-f]{64}$'),
  source_page_count integer check (source_page_count is null or source_page_count >= 0),

  -- Contract versions in effect when this revision was produced -- see
  -- GradusIQ_career/syllabus/models.py's PARSED_SYLLABUS_DOCUMENT_SCHEMA_VERSION/
  -- GRADE_MODEL_SCHEMA_VERSION, relevance.py's RELEVANT_SYLLABUS_CONTENT_SCHEMA_VERSION,
  -- and extraction.py's SYLLABUS_EXTRACTION_PROMPT_VERSION. Nullable: a
  -- manually authored GradeModel (no PDF/LLM pipeline at all, per Phase 6's
  -- "must also work with a future manually authored GradeModel") has no
  -- parsing/relevance/prompt version to record.
  parsed_document_schema_version text,
  relevant_content_schema_version text,
  extraction_prompt_version text,
  grade_model_schema_version text not null,

  extracted_grade_model jsonb not null check (jsonb_typeof(extracted_grade_model) = 'object'),
  -- The RelevantSyllabusContent Phase 4 extracted from -- persisted (not
  -- just referenced) because re-reconciling a corrected candidate model
  -- (see corrections.py / service.py:apply_student_corrections) needs the
  -- same source pages Phase 5's evidence-coverage checks read against.
  -- Bounded to the pages Phase 3 already selected as relevant, never the
  -- full syllabus.
  relevant_content jsonb not null default '{}'::jsonb check (jsonb_typeof(relevant_content) = 'object'),
  reconciliation_status text not null check (reconciliation_status in ('accepted', 'needs_student_review')),
  reconciliation_findings jsonb not null default '[]'::jsonb
    check (jsonb_typeof(reconciliation_findings) = 'array'),
  evidence_coverage jsonb not null default '{}'::jsonb check (jsonb_typeof(evidence_coverage) = 'object'),

  -- Student correction / confirmation layer -- see corrections.py. Never
  -- populated at insert time; only ever touched by
  -- update_revision_confirmation (store.py).
  corrections jsonb not null default '[]'::jsonb check (jsonb_typeof(corrections) = 'array'),
  confirmed_grade_model jsonb check (confirmed_grade_model is null or jsonb_typeof(confirmed_grade_model) = 'object'),
  confirmed_reconciliation_status text
    check (confirmed_reconciliation_status is null or confirmed_reconciliation_status in ('accepted', 'needs_student_review')),
  confirmed_at timestamptz,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  unique (profile_id, source_content_hash)
);

create index syllabus_grade_revisions_profile_idx on syllabus_grade_revisions (profile_id);
create index syllabus_grade_revisions_student_idx on syllabus_grade_revisions (student_id);

alter table syllabus_grade_profiles
  add constraint syllabus_grade_profiles_current_revision_fkey
  foreign key (current_revision_id) references syllabus_grade_revisions(id);

-- Extraction history is immutable: a row's extracted_grade_model,
-- source_content_hash, reconciliation_status, and profile_id can never
-- change after insert. Only the correction/confirmation columns are
-- writable via UPDATE.
create function syllabus_grade_revisions_protect_extraction() returns trigger
language plpgsql as $$
begin
  if new.extracted_grade_model is distinct from old.extracted_grade_model
     or new.relevant_content is distinct from old.relevant_content
     or new.source_content_hash is distinct from old.source_content_hash
     or new.reconciliation_status is distinct from old.reconciliation_status
     or new.profile_id is distinct from old.profile_id
     or new.student_id is distinct from old.student_id
  then
    raise exception 'syllabus_grade_revisions: extraction fields are immutable after insert';
  end if;
  return new;
end;
$$;

create trigger syllabus_grade_revisions_immutable_extraction
  before update on syllabus_grade_revisions
  for each row execute function syllabus_grade_revisions_protect_extraction();

-- StudentGradeState -- one saved row per profile. `revision` is a simple
-- optimistic-concurrency counter (see store.py:save_grade_state): the
-- application reads it, sends it back as the expected value on write, and
-- a mismatch means someone else saved in between. This is the "simpler
-- operation" alternative to a full CAS RPC (degree_schedule's
-- revision-CAS precedent), appropriate here since only one row is ever
-- written per profile -- no multi-table atomicity is needed.
create table syllabus_grade_states (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null unique references syllabus_grade_profiles(id) on delete cascade,
  student_id uuid not null references students(id) on delete cascade,
  category_scores jsonb not null default '[]'::jsonb check (jsonb_typeof(category_scores) = 'array'),
  assessment_scores jsonb not null default '[]'::jsonb check (jsonb_typeof(assessment_scores) = 'array'),
  revision bigint not null default 1 check (revision >= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index syllabus_grade_states_student_idx on syllabus_grade_states (student_id);

-- Row level security: a student may only see/write their own rows,
-- resolved through students.auth_user_id exactly like every other
-- student-owned table (planned_courses, degree_requirement_selections, ...).

grant select, insert, update, delete on syllabus_grade_profiles to authenticated;
grant select, insert, update, delete on syllabus_grade_revisions to authenticated;
grant select, insert, update, delete on syllabus_grade_states to authenticated;

alter table syllabus_grade_profiles enable row level security;
create policy syllabus_grade_profiles_owner_all
  on syllabus_grade_profiles for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = syllabus_grade_profiles.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = syllabus_grade_profiles.student_id
        and students.auth_user_id = auth.uid()
    )
  );
revoke all on syllabus_grade_profiles from anon;

alter table syllabus_grade_revisions enable row level security;
create policy syllabus_grade_revisions_owner_all
  on syllabus_grade_revisions for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = syllabus_grade_revisions.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = syllabus_grade_revisions.student_id
        and students.auth_user_id = auth.uid()
    )
  );
revoke all on syllabus_grade_revisions from anon;

alter table syllabus_grade_states enable row level security;
create policy syllabus_grade_states_owner_all
  on syllabus_grade_states for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = syllabus_grade_states.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = syllabus_grade_states.student_id
        and students.auth_user_id = auth.uid()
    )
  );
revoke all on syllabus_grade_states from anon;
