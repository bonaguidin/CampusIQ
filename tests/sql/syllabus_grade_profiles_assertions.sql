\set ON_ERROR_STOP on

insert into students(id, auth_user_id, name) values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'Student A'),
  ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'Student B');

insert into syllabus_grade_profiles(id, student_id, institution, course_code, term, section) values
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'tamu', 'PHYS 207', 'Fall 2026', '529'),
  ('30000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', 'tamu', 'PHYS 207', 'Fall 2026', '529');

insert into syllabus_grade_revisions(
  id, profile_id, student_id, source_content_hash, grade_model_schema_version,
  extracted_grade_model, reconciliation_status
) values (
  '40000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'sha256:0000000000000000000000000000000000000000000000000000000000000001',
  '1', '{"schema_version": "1"}', 'accepted'
);

-- Constraint checks.
do $$
begin
  begin
    insert into syllabus_grade_revisions(
      profile_id, student_id, source_content_hash, grade_model_schema_version,
      extracted_grade_model, reconciliation_status
    ) values (
      '30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
      'not-a-hash', '1', '{}', 'accepted'
    );
    raise exception 'malformed content hash accepted';
  exception when check_violation then null; end;

  begin
    insert into syllabus_grade_revisions(
      profile_id, student_id, source_content_hash, grade_model_schema_version,
      extracted_grade_model, reconciliation_status
    ) values (
      '30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
      'sha256:0000000000000000000000000000000000000000000000000000000000000002',
      '1', '{}', 'bogus_status'
    );
    raise exception 'invalid reconciliation_status accepted';
  exception when check_violation then null; end;

  begin
    insert into syllabus_grade_revisions(
      profile_id, student_id, source_content_hash, grade_model_schema_version,
      extracted_grade_model, reconciliation_status
    ) values (
      '30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
      'sha256:0000000000000000000000000000000000000000000000000000000000000003',
      '1', '"not an object"', 'accepted'
    );
    raise exception 'non-object extracted_grade_model accepted';
  exception when check_violation then null; end;

  begin
    insert into syllabus_grade_revisions(
      profile_id, student_id, source_content_hash, grade_model_schema_version,
      extracted_grade_model, reconciliation_status
    ) values (
      -- duplicate (profile_id, source_content_hash)
      '30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
      'sha256:0000000000000000000000000000000000000000000000000000000000000001',
      '1', '{}', 'accepted'
    );
    raise exception 'duplicate source hash for same profile accepted';
  exception when unique_violation then null; end;

  begin
    insert into syllabus_grade_profiles(student_id, review_state)
    values ('10000000-0000-0000-0000-000000000001', 'bogus');
    raise exception 'invalid review_state accepted';
  exception when check_violation then null; end;

  begin
    insert into syllabus_grade_states(profile_id, student_id, category_scores)
    values ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '"not an array"');
    raise exception 'non-array category_scores accepted';
  exception when check_violation then null; end;
end $$;

-- Immutability: extracted_grade_model/source_content_hash/reconciliation_status
-- cannot change after insert; the correction/confirmation columns can.
do $$
begin
  begin
    update syllabus_grade_revisions
    set extracted_grade_model = '{"tampered": true}'
    where id = '40000000-0000-0000-0000-000000000001';
    raise exception 'extracted_grade_model was mutable';
  exception when raise_exception then
    if sqlerrm <> 'syllabus_grade_revisions: extraction fields are immutable after insert' then raise; end if;
  end;

  update syllabus_grade_revisions
  set confirmed_grade_model = '{"schema_version": "1"}',
      confirmed_reconciliation_status = 'accepted',
      confirmed_at = now(),
      corrections = '[{"target_type": "category", "operation": "set_weight"}]'::jsonb
  where id = '40000000-0000-0000-0000-000000000001';

  if (select confirmed_reconciliation_status from syllabus_grade_revisions
      where id = '40000000-0000-0000-0000-000000000001') <> 'accepted' then
    raise exception 'confirmation columns were not writable';
  end if;
end $$;

-- syllabus_grade_states.revision is a plain optimistic-concurrency counter;
-- a stale expected value must not silently be honored by application code
-- (that check lives in Python), but the column itself must persist as
-- written.
insert into syllabus_grade_states(profile_id, student_id, category_scores, revision)
values ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '[{"category_name": "Midterm", "actual_score": 78}]', 1);

do $$
begin
  begin
    insert into syllabus_grade_states(profile_id, student_id)
    values ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001');
    raise exception 'second grade state for same profile accepted';
  exception when unique_violation then null; end;
end $$;

-- RLS: student A can see only their own profile/revision/state; cannot
-- insert a row owned by student B.
set role authenticated;
select set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000001', false);
do $$
begin
  if (select count(*) from syllabus_grade_profiles) <> 1 then
    raise exception 'own profile not visible or foreign profile leaked';
  end if;
  if (select count(*) from syllabus_grade_revisions) <> 1 then
    raise exception 'own revision not visible or foreign revision leaked';
  end if;
  if (select count(*) from syllabus_grade_states) <> 1 then
    raise exception 'own grade state not visible or foreign grade state leaked';
  end if;

  begin
    insert into syllabus_grade_profiles(student_id, course_code)
    values ('10000000-0000-0000-0000-000000000002', 'HACK 101');
    raise exception 'cross-student profile insert accepted';
  exception when insufficient_privilege then null; end;

  begin
    update syllabus_grade_profiles
    set review_state = 'confirmed'
    where student_id = '10000000-0000-0000-0000-000000000002';
    if found then raise exception 'cross-student profile update accepted'; end if;
  end;
end $$;
reset role;
