-- Syllabus review redesign (spec §2A / §5): persist the answers a student
-- gives to the clarifying questions shown before the grade calculator --
-- cutoff-overlap confirmations, missing assessment counts, low-confidence
-- extraction confirmations. One keyed JSON log per ingested revision,
-- following the same shape/posture as this table's existing `corrections`
-- column (added in 20260826120000_syllabus_grade_profiles.sql): a jsonb
-- container, defaulted, never populated at insert time, only ever written
-- by the student-facing answer flow.
--
-- Deliberately a single column, not several narrow ones -- the set of
-- question kinds is expected to grow as the flow is built out, and a keyed
-- log absorbs that without further migrations.
--
-- NOT added to syllabus_grade_revisions_protect_extraction(): that trigger
-- is a blocklist of extraction-identity columns (extracted_grade_model,
-- relevant_content, source_content_hash, reconciliation_status,
-- profile_id, student_id) that must never change after insert.
-- clarifying_answers is not one of those -- it is student-mutable
-- post-insert exactly like `corrections` / `confirmed_grade_model`, so it
-- simply stays out of the guard. The trigger function is intentionally
-- left untouched by this migration.

alter table syllabus_grade_revisions
  add column clarifying_answers jsonb not null default '{}'::jsonb
    check (jsonb_typeof(clarifying_answers) = 'object');
