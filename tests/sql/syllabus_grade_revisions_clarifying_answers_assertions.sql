\set ON_ERROR_STOP on

insert into students(id, auth_user_id, name) values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'Student A');

insert into syllabus_grade_profiles(id, student_id, institution, course_code, term, section) values
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'tamu', 'PHYS 207', 'Fall 2026', '529');

insert into syllabus_grade_revisions(
  id, profile_id, student_id, source_content_hash, grade_model_schema_version,
  extracted_grade_model, reconciliation_status
) values (
  '40000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'sha256:0000000000000000000000000000000000000000000000000000000000000001',
  '1', '{"schema_version": "1"}', 'needs_student_review'
);

-- Column presence + default: a freshly inserted revision has an empty
-- object, never null.
do $$
begin
  if (select clarifying_answers from syllabus_grade_revisions
      where id = '40000000-0000-0000-0000-000000000001') <> '{}'::jsonb then
    raise exception 'clarifying_answers did not default to an empty object';
  end if;
end $$;

-- jsonb_typeof check: a non-object value is rejected.
do $$
begin
  begin
    insert into syllabus_grade_revisions(
      profile_id, student_id, source_content_hash, grade_model_schema_version,
      extracted_grade_model, reconciliation_status, clarifying_answers
    ) values (
      '30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
      'sha256:0000000000000000000000000000000000000000000000000000000000000002',
      '1', '{}', 'accepted', '"not an object"'
    );
    raise exception 'non-object clarifying_answers accepted';
  exception when check_violation then null; end;
end $$;

-- NOT NULL: an explicit null is rejected.
do $$
begin
  begin
    update syllabus_grade_revisions set clarifying_answers = null
    where id = '40000000-0000-0000-0000-000000000001';
    raise exception 'null clarifying_answers accepted';
  exception when not_null_violation then null; end;
end $$;

-- Allowed-mutable: clarifying_answers is NOT covered by
-- syllabus_grade_revisions_protect_extraction(), so a student-facing
-- answer flow can write it after insert -- exactly like corrections /
-- confirmed_grade_model.
update syllabus_grade_revisions
set clarifying_answers = '{"cutoff_overlap:B,C": {"answer": "confirm_default", "boundary": 80, "winner": "B"}}'::jsonb
where id = '40000000-0000-0000-0000-000000000001';

do $$
begin
  if (select clarifying_answers -> 'cutoff_overlap:B,C' ->> 'winner'
      from syllabus_grade_revisions
      where id = '40000000-0000-0000-0000-000000000001') <> 'B' then
    raise exception 'clarifying_answers was not writable after insert';
  end if;
end $$;

-- Regression: the immutability guard still fires for a real
-- extraction-identity column, and clarifying_answers riding along in the
-- same UPDATE does not change that.
do $$
begin
  begin
    update syllabus_grade_revisions
    set extracted_grade_model = '{"tampered": true}',
        clarifying_answers = '{"x": 1}'::jsonb
    where id = '40000000-0000-0000-0000-000000000001';
    raise exception 'extracted_grade_model was mutable';
  exception when raise_exception then
    if sqlerrm <> 'syllabus_grade_revisions: extraction fields are immutable after insert' then raise; end if;
  end;
end $$;
