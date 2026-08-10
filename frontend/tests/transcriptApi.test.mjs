import assert from 'node:assert/strict'
import test from 'node:test'
import { CONFIRM_TIMEOUT_MS, REQUEST_TIMEOUT_STATUS, canonicalTranscriptValue, formatCreditHours, normalizeTranscriptConfirm, normalizeTranscriptPatch, normalizeTranscriptReview, normalizeTranscriptUpload, parseCreditHours, transcriptChangedFields } from '../src/lib/transcriptApi.mjs'

test('transcript API normalizers follow the backend response shapes', () => {
  const review = normalizeTranscriptReview(200, { course_records: [{ id: '1' }], terms: [{ id: 't' }], institutions: [{ id: 'i' }], excluded_by_repeat: [], pending_catalog_review: 1 })
  assert.equal(review.ok, true); assert.equal(review.records.length, 1); assert.equal(review.pendingCatalogReview, 1)
  assert.equal(normalizeTranscriptUpload(200, { status: 'ok', written: { course_records: { inserted: 2 } } }).inserted, 2)
  assert.equal(normalizeTranscriptPatch(422, { detail: 'bad credits' }).message, 'bad credits')
  assert.equal(normalizeTranscriptConfirm(409, { detail: { message: 'scale pending' } }).message, 'scale pending')
})

test('transcript recovery failure never normalizes as an empty success', () => {
  const result = normalizeTranscriptReview(502, { detail: 'database unavailable' })
  assert.equal(result.ok, false); assert.equal(result.records.length, 0); assert.equal(result.message, 'database unavailable')
})

// ── error-kind discrimination ───────────────────────────────────────────────
// Each of these statuses carries more than one backend meaning, and the remedy
// differs per meaning. Collapsing them loses the only actionable part.

test('the two 413s are told apart: file size vs. content length', () => {
  // MAX_TRANSCRIPT_BYTES raises a plain-string detail.
  const oversize = normalizeTranscriptUpload(413, { detail: 'Transcript exceeds the 10 MB limit.' })
  assert.equal(oversize.kind, 'file_too_large')

  // TranscriptTooLongError raises a structured detail. A smaller file is NOT
  // the fix here, so it must not share the oversize kind.
  const tooLong = normalizeTranscriptUpload(413, { detail: { error: 'transcript_too_long', message: 'Transcript text is too long to parse.' } })
  assert.equal(tooLong.kind, 'transcript_too_long')
  assert.equal(tooLong.message, 'Transcript text is too long to parse.')
})

test('an encrypted PDF is its own kind, not a generic 422', () => {
  const encrypted = normalizeTranscriptUpload(422, { detail: { error: 'extraction_failed', extraction_status: 'encrypted', message: 'The file is password protected.' } })
  assert.equal(encrypted.kind, 'encrypted')

  const otherwise = normalizeTranscriptUpload(422, { detail: { error: 'extraction_failed', extraction_status: 'empty', message: 'No text found.' } })
  assert.equal(otherwise.kind, 'invalid')
})

test('grade_scale_unverified is distinguished from ordinary 409 conflicts', () => {
  const blocked = normalizeTranscriptConfirm(409, { detail: { error: 'grade_scale_unverified', message: 'Verification is pending.' } })
  assert.equal(blocked.kind, 'grade_scale_unverified')

  // The other three 409s (no home institution, no grading scale, already
  // confirmed) carry no error code and stay ordinary conflicts.
  assert.equal(normalizeTranscriptConfirm(409, { detail: 'Student has no home institution on record.' }).kind, 'conflict')
})

test('a client timeout is its own kind, never a network failure', () => {
  const timedOut = normalizeTranscriptConfirm(REQUEST_TIMEOUT_STATUS, null)
  assert.equal(timedOut.ok, false)
  assert.equal(timedOut.kind, 'timeout')

  // The remedy differs from a network failure -- wait, rather than assume the
  // app is broken -- so the copy must differ too. A cold start is the likeliest
  // cause and the student can only make it worse by hammering the button.
  assert.match(timedOut.message, /taking longer than expected/)
  assert.match(timedOut.message, /still be starting up/)
  assert.notEqual(timedOut.message, normalizeTranscriptConfirm(0, null).message)
  assert.equal(normalizeTranscriptConfirm(0, null).kind, 'network')

  // The sentinel must never be mistakable for a real HTTP status.
  assert.ok(REQUEST_TIMEOUT_STATUS < 0)
  // Long enough to outlast the measured 20-50s cold-start range.
  assert.ok(CONFIRM_TIMEOUT_MS >= 60_000)
})

test('a PATCH 404 removes the row rather than reading as a server error', () => {
  const gone = normalizeTranscriptPatch(404, { detail: 'No editable course record with that id.' })
  assert.equal(gone.kind, 'not_found')
  assert.equal(gone.record, null)
})

test('a PATCH 409 separates already-confirmed from a natural-key collision', () => {
  assert.equal(normalizeTranscriptPatch(409, { detail: 'This record has already been confirmed and can no longer be edited.' }).kind, 'already_confirmed')
  assert.equal(normalizeTranscriptPatch(409, { detail: 'Another course record already uses that term_id + course_code.' }).kind, 'conflict')
})

// ── cross_check / catalog threading ─────────────────────────────────────────

test('cross_check and catalog survive upload normalization', () => {
  const result = normalizeTranscriptUpload(200, {
    status: 'ok',
    written: { course_records: { inserted: 3 } },
    catalog: { matched: 2, unmatched: 1, misses: ['MATH 251'] },
    cross_check: { ok: false, terms_checked: 2, terms_skipped: 1, mismatches: [{ term_label: 'Fall 2025', field: 'gpa', printed: 3.5, computed: 3.0, difference: 0.5 }] },
  })
  assert.equal(result.crossCheck.ok, false)
  assert.equal(result.crossCheck.termsChecked, 2)
  assert.equal(result.crossCheck.termsSkipped, 1)
  assert.equal(result.crossCheck.mismatches[0].printed, 3.5)
  assert.equal(result.catalog.matched, 2)
  assert.deepEqual(result.catalog.misses, ['MATH 251'])
})

test('a missing cross_check is a well-formed empty one, never undefined', () => {
  const ok = normalizeTranscriptUpload(200, { status: 'ok', written: { course_records: { inserted: 1 } } })
  assert.equal(ok.crossCheck.ok, true)
  assert.deepEqual(ok.crossCheck.mismatches, [])

  // Failure paths never reach the cross-check step, but callers must not have
  // to branch on which path produced the result.
  for (const result of [normalizeTranscriptUpload(200, { status: 'parse_failed' }), normalizeTranscriptUpload(502, { detail: 'boom' })]) {
    assert.deepEqual(result.crossCheck.mismatches, [])
    assert.equal(result.catalog.matched, 0)
  }
})

// ── credit_hours boundary ───────────────────────────────────────────────────

test('credit_hours parses from the backend string and formats back to 2dp', () => {
  assert.equal(parseCreditHours('3.00'), 3)
  assert.equal(parseCreditHours(3), 3)
  assert.equal(parseCreditHours('3 hours'), null)
  assert.equal(parseCreditHours(''), null)
  assert.equal(formatCreditHours(3), '3.00')
  assert.equal(formatCreditHours('3.5'), '3.50')
  assert.equal(formatCreditHours('nonsense'), null)
})

test('a pure reformat is not a change', () => {
  // The row arrives as "3.00"; the editor hands back the number 3. A strict
  // === would call that an edit and PATCH a value identical to the stored one.
  assert.equal(canonicalTranscriptValue('credit_hours', '3.00'), canonicalTranscriptValue('credit_hours', 3))
  assert.deepEqual(transcriptChangedFields({ credit_hours: '3.00' }, { credit_hours: 3 }), {})
})

test('a real credit change is sent as the backend 2dp string', () => {
  assert.deepEqual(transcriptChangedFields({ credit_hours: '3.00' }, { credit_hours: 4 }), { credit_hours: '4.00' })
})

test('only changed transcript fields are sent', () => {
  const original = { course_code: 'MATH 251', title: 'Calc', credit_hours: '3.00', letter_grade: 'B', status: 'completed' }
  const draft = { ...original, credit_hours: 3, letter_grade: 'A' }
  assert.deepEqual(transcriptChangedFields(original, draft), { letter_grade: 'A' })
})
