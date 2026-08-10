import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ALL_SECTIONS,
  CHILD_TABLES,
  CONFIRM_TIMEOUT_MS,
  REQUEST_TIMEOUT_STATUS,
  REVIEW_SECTIONS,
  changedFields,
  confirmedToSingular,
  countPending,
  detailExtractionStatus,
  detailToText,
  editableFieldNames,
  formatListInput,
  normalizeConfirmResponse,
  normalizeFieldValue,
  normalizePatchResponse,
  normalizeReviewResponse,
  normalizeUploadResponse,
  normalizeWritten,
  parseListInput,
  reviewEditUrl,
  writtenTotals,
} from '../src/lib/resumeApi.mjs'

// ── field metadata must mirror the backend's EDITABLE_FIELDS ────────────────

test('REVIEW_SECTIONS matches the backend EDITABLE_FIELDS lists exactly', () => {
  // Mirrors GradusIQ_career/resume/review.py. If the backend list changes and
  // this does not, edits to the new field would be silently stripped.
  assert.deepEqual(editableFieldNames('career_profile'), [
    'target_roles',
    'interests',
    'career_goals',
    'geographic_preference',
    'ai_anxiety_level',
    'skills_technical',
    'skills_soft',
    'ai_exposure',
  ])
  assert.deepEqual(editableFieldNames('certifications'), ['name', 'issuer', 'status', 'date'])
  assert.deepEqual(editableFieldNames('work_experience'), [
    'employer',
    'role',
    'duration',
    'location',
    'description',
    'skills_gained',
  ])
  assert.deepEqual(editableFieldNames('projects'), ['name', 'timeframe', 'description', 'tools'])

  // No system-managed column may appear in any editable list.
  const systemManaged = [
    'id',
    'student_id',
    'career_profile_id',
    'source',
    'confirmed_at',
    'created_at',
    'updated_at',
  ]
  for (const key of ALL_SECTIONS) {
    for (const field of editableFieldNames(key)) {
      assert.equal(systemManaged.includes(field), false, `${key}.${field} is system-managed`)
    }
  }
})

test('section keys are the PATCH url segments', () => {
  assert.deepEqual(Object.keys(REVIEW_SECTIONS), [
    'career_profile',
    'certifications',
    'work_experience',
    'projects',
  ])
  assert.equal(
    reviewEditUrl('certifications', 'abc-123'),
    '/api/v2/student/me/career/review/certifications/abc-123',
  )
  // The singular segment, not the real table name.
  assert.equal(
    reviewEditUrl('career_profile', 'x'),
    '/api/v2/student/me/career/review/career_profile/x',
  )
  assert.equal(reviewEditUrl('projects', 'a/b'), '/api/v2/student/me/career/review/projects/a%2Fb')
})

// ── detail: object vs string (disagreement #2) ──────────────────────────────

test('detailToText reads a string detail, an object detail, and neither', () => {
  assert.equal(detailToText('Resume exceeds the 10 MB limit.'), 'Resume exceeds the 10 MB limit.')
  assert.equal(
    detailToText({
      error: 'extraction_failed',
      extraction_status: 'empty',
      message: 'No readable text was found in the file.',
    }),
    'No readable text was found in the file.',
  )
  // Neither shape -> the caller's fallback, never "[object Object]".
  assert.equal(detailToText(undefined, 'fallback'), 'fallback')
  assert.equal(detailToText(null, 'fallback'), 'fallback')
  assert.equal(detailToText({}, 'fallback'), 'fallback')
  assert.equal(detailToText({ message: '   ' }, 'fallback'), 'fallback')
  assert.equal(detailToText('   ', 'fallback'), 'fallback')
  assert.equal(detailToText(42, 'fallback'), 'fallback')
  assert.equal(detailToText([], 'fallback'), 'fallback')
  // And never stringifies an object blindly.
  assert.equal(detailToText({ error: 'x' }, 'fallback').includes('[object'), false)
})

test('detailExtractionStatus reads the object form only', () => {
  assert.equal(detailExtractionStatus({ extraction_status: 'empty' }), 'empty')
  assert.equal(detailExtractionStatus({ extraction_status: 'unsupported_format' }), 'unsupported_format')
  assert.equal(detailExtractionStatus('a string detail'), null)
  assert.equal(detailExtractionStatus(undefined), null)
  assert.equal(detailExtractionStatus({ message: 'no status here' }), null)
})

// ── written: null vs populated (disagreement #1) ────────────────────────────

test('normalizeWritten fills all three tables whatever it is given', () => {
  const fromNull = normalizeWritten(null)
  assert.deepEqual(Object.keys(fromNull), CHILD_TABLES.slice())
  for (const table of CHILD_TABLES) {
    assert.deepEqual(fromNull[table], { inserted: 0, skipped_duplicate: 0 })
  }

  assert.deepEqual(normalizeWritten(undefined), fromNull)
  assert.deepEqual(normalizeWritten('nonsense'), fromNull)
  assert.deepEqual(normalizeWritten({}), fromNull)

  const populated = normalizeWritten({
    certifications: { inserted: 2, skipped_duplicate: 1 },
    work_experience: { inserted: 0, skipped_duplicate: 3 },
    projects: { inserted: 1, skipped_duplicate: 0 },
  })
  assert.deepEqual(populated.certifications, { inserted: 2, skipped_duplicate: 1 })
  assert.deepEqual(populated.work_experience, { inserted: 0, skipped_duplicate: 3 })
  assert.deepEqual(populated.projects, { inserted: 1, skipped_duplicate: 0 })

  // A partial or malformed table entry degrades to zeros rather than NaN.
  const partial = normalizeWritten({ certifications: { inserted: 5 } })
  assert.deepEqual(partial.certifications, { inserted: 5, skipped_duplicate: 0 })
  assert.deepEqual(partial.projects, { inserted: 0, skipped_duplicate: 0 })
})

test('writtenTotals sums inserted and skipped across tables', () => {
  assert.deepEqual(writtenTotals(null), { inserted: 0, skipped_duplicate: 0, total: 0 })
  assert.deepEqual(
    writtenTotals({
      certifications: { inserted: 2, skipped_duplicate: 1 },
      work_experience: { inserted: 0, skipped_duplicate: 3 },
      projects: { inserted: 1, skipped_duplicate: 0 },
    }),
    { inserted: 3, skipped_duplicate: 4, total: 7 },
  )
})

// ── upload: all four status values ──────────────────────────────────────────

const OK_BODY = {
  status: 'ok',
  extraction: { status: 'ok', page_count: 2 },
  model: 'deepseek/deepseek-v4-flash',
  warnings: ['certifications[0]: status coerced'],
  career_profile: { outcome: 'created', id: 'cp-1' },
  written: {
    certifications: { inserted: 1, skipped_duplicate: 0 },
    work_experience: { inserted: 2, skipped_duplicate: 1 },
    projects: { inserted: 0, skipped_duplicate: 0 },
  },
}

test('upload ok carries counts, warnings, model and the bootstrap outcome', () => {
  const result = normalizeUploadResponse(200, OK_BODY)

  assert.equal(result.ok, true)
  assert.equal(result.kind, 'ok')
  assert.equal(result.httpStatus, 200)
  assert.deepEqual(result.extraction, { status: 'ok', page_count: 2 })
  assert.equal(result.model, 'deepseek/deepseek-v4-flash')
  assert.deepEqual(result.warnings, ['certifications[0]: status coerced'])
  assert.deepEqual(result.careerProfile, { outcome: 'created', id: 'cp-1' })
  assert.deepEqual(result.totals, { inserted: 3, skipped_duplicate: 1, total: 4 })
  assert.deepEqual(result.errors, [])
})

test('upload already_existed_untouched is still ok', () => {
  const result = normalizeUploadResponse(200, {
    ...OK_BODY,
    career_profile: { outcome: 'already_existed_untouched', id: 'cp-1' },
  })
  assert.equal(result.ok, true)
  assert.equal(result.careerProfile.outcome, 'already_existed_untouched')
})

test('upload not_a_resume and unparseable have written null and no career_profile key', () => {
  for (const status of ['not_a_resume', 'unparseable']) {
    const result = normalizeUploadResponse(200, {
      status,
      extraction: { status: 'ok', page_count: 1 },
      model: 'm',
      warnings: [],
      written: null,
    })

    assert.equal(result.ok, false, status)
    assert.equal(result.kind, status)
    assert.ok(result.message.length > 20, 'needs a real, differentiated message')
    // written is null on the wire but an object here.
    assert.deepEqual(result.written, normalizeWritten(null))
    assert.deepEqual(result.totals, { inserted: 0, skipped_duplicate: 0, total: 0 })
    assert.equal(result.careerProfile, null)
  }

  // The two messages must actually differ from each other.
  const a = normalizeUploadResponse(200, { status: 'not_a_resume', written: null })
  const b = normalizeUploadResponse(200, { status: 'unparseable', written: null })
  assert.notEqual(a.message, b.message)
})

test('upload parse_failed carries errors but neither model nor warnings', () => {
  const result = normalizeUploadResponse(200, {
    status: 'parse_failed',
    extraction: { status: 'ok', page_count: 1 },
    errors: ['Malformed AI JSON response: Expecting value'],
    written: null,
  })

  assert.equal(result.ok, false)
  assert.equal(result.kind, 'parse_failed')
  assert.deepEqual(result.errors, ['Malformed AI JSON response: Expecting value'])
  // Absent on the wire -> safe defaults, never undefined.
  assert.deepEqual(result.warnings, [])
  assert.equal(result.model, null)
  assert.deepEqual(result.written, normalizeWritten(null))
})

test('every upload branch returns the same key set', () => {
  const bodies = [
    [200, OK_BODY],
    [200, { status: 'not_a_resume', written: null }],
    [200, { status: 'unparseable', written: null }],
    [200, { status: 'parse_failed', errors: [], written: null }],
    [413, { detail: 'Resume exceeds the 10 MB limit.' }],
    [415, { detail: { error: 'extraction_failed', extraction_status: 'unsupported_format', message: 'x' } }],
    [422, { detail: { error: 'extraction_failed', extraction_status: 'empty', message: 'x' } }],
    [429, { detail: 'Request rate limit exceeded.' }],
    [502, { detail: 'Could not save the parsed resume.' }],
    [418, {}],
  ]
  const expected = Object.keys(normalizeUploadResponse(200, OK_BODY)).sort()

  for (const [status, body] of bodies) {
    const keys = Object.keys(normalizeUploadResponse(status, body)).sort()
    assert.deepEqual(keys, expected, `status ${status} has a different key set`)
  }
})

test('upload 415 and 422 read the detail OBJECT, not [object Object]', () => {
  const unsupported = normalizeUploadResponse(415, {
    detail: {
      error: 'extraction_failed',
      extraction_status: 'unsupported_format',
      message: 'Legacy Word .doc files are not supported. Re-save as .docx or PDF.',
    },
  })
  assert.equal(unsupported.ok, false)
  assert.equal(unsupported.kind, 'unsupported_format')
  assert.match(unsupported.message, /\.docx/)
  assert.equal(unsupported.message.includes('[object'), false)

  const empty = normalizeUploadResponse(422, {
    detail: {
      error: 'extraction_failed',
      extraction_status: 'empty',
      message: 'No readable text was found in the file.',
    },
  })
  assert.equal(empty.kind, 'empty')
  assert.match(empty.message, /readable text/)
  assert.deepEqual(empty.extraction, { status: 'empty', page_count: null })

  const failed = normalizeUploadResponse(422, {
    detail: { error: 'extraction_failed', extraction_status: 'extraction_failed', message: 'Could not read the PDF file.' },
  })
  assert.equal(failed.kind, 'extraction_failed')
})

test('upload maps the remaining status codes distinctly', () => {
  assert.equal(normalizeUploadResponse(413, { detail: 'too big' }).kind, 'file_too_large')
  assert.equal(normalizeUploadResponse(400, { detail: 'bad' }).kind, 'bad_upload')
  assert.equal(normalizeUploadResponse(401, {}).kind, 'unauthenticated')
  assert.equal(normalizeUploadResponse(404, {}).kind, 'no_student_profile')
  assert.equal(normalizeUploadResponse(502, { detail: 'x' }).kind, 'backend_unavailable')
  assert.equal(normalizeUploadResponse(503, { detail: 'x' }).kind, 'not_configured')
  assert.equal(normalizeUploadResponse(418, {}).kind, 'unknown')
})

test('the two different 429s are separate kinds with different remedies', () => {
  const rate = normalizeUploadResponse(429, { detail: 'Request rate limit exceeded.' })
  const busy = normalizeUploadResponse(429, { detail: 'AI service is busy; retry later.' })

  assert.equal(rate.kind, 'rate_limited')
  assert.equal(busy.kind, 'ai_busy')
  assert.notEqual(rate.message, busy.message)
})

test('upload tolerates a missing or non-object body', () => {
  for (const body of [null, undefined, 'text', 0]) {
    const result = normalizeUploadResponse(200, body)
    assert.equal(result.ok, false)
    assert.equal(typeof result.message, 'string')
  }
  const unknownStatus = normalizeUploadResponse(200, { status: 'something_new' })
  assert.equal(unknownStatus.ok, false)
  assert.equal(unknownStatus.kind, 'unknown')
})

// ── review GET ──────────────────────────────────────────────────────────────

test('review normalizes a full payload and counts what is pending', () => {
  const result = normalizeReviewResponse(200, {
    career_profile: { id: 'cp-1', target_roles: ['SWE'], source: 'resume_parse' },
    certifications: [{ id: 'c1', name: 'AWS' }],
    work_experience: [{ id: 'w1', employer: 'Acme' }, { id: 'w2', employer: 'Globex' }],
    projects: [],
  })

  assert.equal(result.ok, true)
  assert.equal(result.sections.career_profile.id, 'cp-1')
  assert.equal(result.sections.work_experience.length, 2)
  assert.deepEqual(result.sections.projects, [])
  assert.equal(result.pendingCount, 4)
})

test('review handles career_profile null with children still present', () => {
  const result = normalizeReviewResponse(200, {
    career_profile: null,
    certifications: [{ id: 'c1', name: 'New' }],
    work_experience: [],
    projects: [],
  })

  assert.equal(result.ok, true)
  assert.equal(result.sections.career_profile, null)
  assert.equal(result.sections.certifications.length, 1)
  assert.equal(result.pendingCount, 1)
})

test('review with nothing pending counts zero', () => {
  const result = normalizeReviewResponse(200, {
    career_profile: null,
    certifications: [],
    work_experience: [],
    projects: [],
  })
  assert.equal(result.pendingCount, 0)
  assert.equal(result.ok, true)
})

test('review coerces malformed arrays rather than throwing', () => {
  const result = normalizeReviewResponse(200, {
    career_profile: 'not an object',
    certifications: null,
    work_experience: 'nope',
  })
  assert.equal(result.sections.career_profile, null)
  assert.deepEqual(result.sections.certifications, [])
  assert.deepEqual(result.sections.work_experience, [])
  assert.deepEqual(result.sections.projects, [])
})

test('review failures still return an empty section shape', () => {
  for (const status of [401, 404, 429, 502, 503, 418]) {
    const result = normalizeReviewResponse(status, { detail: 'x' })
    assert.equal(result.ok, false, `status ${status}`)
    assert.deepEqual(Object.keys(result.sections).sort(), [
      'career_profile',
      'certifications',
      'projects',
      'work_experience',
    ])
    assert.equal(result.pendingCount, 0)
    assert.ok(result.message.length > 0)
  }
  assert.equal(normalizeReviewResponse(404, {}).kind, 'no_student_profile')
})

test('countPending handles partial and null input', () => {
  assert.equal(countPending(null), 0)
  assert.equal(countPending({}), 0)
  assert.equal(countPending({ career_profile: { id: 'x' } }), 1)
  assert.equal(countPending({ certifications: [{ id: 'a' }, { id: 'b' }] }), 2)
})

// ── review PATCH: the two different 409s ────────────────────────────────────

test('patch ok returns the updated row', () => {
  const row = { id: 'c1', name: 'AWS', issuer: 'Amazon', status: 'completed', date: null, source: 'resume_parse' }
  const result = normalizePatchResponse(200, row)

  assert.equal(result.ok, true)
  assert.equal(result.kind, 'ok')
  assert.deepEqual(result.row, row)
})

test('patch distinguishes already-confirmed from a natural-key collision', () => {
  const confirmed = normalizePatchResponse(409, {
    detail: 'This record has already been confirmed and can no longer be edited.',
  })
  const collision = normalizePatchResponse(409, {
    detail: 'Another certifications record already uses that name. Choose a different value.',
  })

  assert.equal(confirmed.kind, 'already_confirmed')
  assert.equal(collision.kind, 'conflict')
  assert.notEqual(confirmed.message, collision.message)
  // The collision message names the colliding field, so it is surfaced as-is.
  assert.match(collision.message, /name/)
  assert.equal(confirmed.row, null)
  assert.equal(collision.row, null)
})

test('patch 404 does not disclose why the row is unavailable', () => {
  const result = normalizePatchResponse(404, {
    detail: 'No editable certifications record with that id.',
  })

  assert.equal(result.kind, 'not_found')
  // The backend collapses absent and cross-student into one 404 on purpose.
  // The UI must not reintroduce the distinction.
  for (const leak of ['another student', 'permission', 'forbidden', 'belongs']) {
    assert.equal(result.message.toLowerCase().includes(leak), false)
  }
})

test('patch 422 surfaces the validation message verbatim', () => {
  const result = normalizePatchResponse(422, {
    detail: "certifications.status must be null, 'completed', or 'in_progress'; got 'expired'.",
  })
  assert.equal(result.kind, 'invalid')
  assert.match(result.message, /in_progress/)
})

test('patch maps shared failures and unknown statuses', () => {
  assert.equal(normalizePatchResponse(401, {}).kind, 'unauthenticated')
  assert.equal(normalizePatchResponse(429, { detail: 'Request rate limit exceeded.' }).kind, 'rate_limited')
  assert.equal(normalizePatchResponse(502, { detail: 'x' }).kind, 'backend_unavailable')
  assert.equal(normalizePatchResponse(418, {}).kind, 'unknown')
  assert.equal(normalizePatchResponse(409, { detail: undefined }).kind, 'conflict')
})

// ── confirm: singular request key vs plural response key ────────────────────

test('confirm rekeys career_profiles (plural) to career_profile (singular)', () => {
  const result = normalizeConfirmResponse(200, {
    status: 'ok',
    scope: 'all_unconfirmed',
    confirmed: { career_profiles: 1, certifications: 3, work_experience: 2, projects: 1 },
    total_confirmed: 7,
  })

  assert.equal(result.ok, true)
  assert.equal(result.scope, 'all_unconfirmed')
  assert.equal(result.confirmed.career_profile, 1)
  // The plural response key must NOT survive into the internal shape.
  assert.equal('career_profiles' in result.confirmed, false)
  assert.deepEqual(Object.keys(result.confirmed).sort(), [
    'career_profile',
    'certifications',
    'projects',
    'work_experience',
  ])
  assert.equal(result.totalConfirmed, 7)
})

test('confirmedToSingular tolerates missing and malformed counts', () => {
  assert.deepEqual(confirmedToSingular(null), {
    career_profile: 0,
    certifications: 0,
    work_experience: 0,
    projects: 0,
  })
  assert.deepEqual(confirmedToSingular({ career_profiles: 2 }), {
    career_profile: 2,
    certifications: 0,
    work_experience: 0,
    projects: 0,
  })
  // A singular key in the RESPONSE is not what the backend sends and is ignored.
  assert.equal(confirmedToSingular({ career_profile: 9 }).career_profile, 0)
  assert.equal(confirmedToSingular({ certifications: 'three' }).certifications, 0)
})

test('confirm falls back to summing when total_confirmed is absent', () => {
  const result = normalizeConfirmResponse(200, {
    confirmed: { career_profiles: 1, certifications: 2, work_experience: 0, projects: 1 },
  })
  assert.equal(result.totalConfirmed, 4)
})

test('confirm failures return zeroed counts and a message', () => {
  for (const status of [401, 404, 429, 502, 418]) {
    const result = normalizeConfirmResponse(status, { detail: 'x' })
    assert.equal(result.ok, false, `status ${status}`)
    assert.equal(result.totalConfirmed, 0)
    assert.equal(result.confirmed.career_profile, 0)
    assert.ok(result.message.length > 0)
  }
})

test('a client timeout on confirm is its own kind with cold-start copy', () => {
  const timedOut = normalizeConfirmResponse(REQUEST_TIMEOUT_STATUS, null)
  assert.equal(timedOut.ok, false)
  assert.equal(timedOut.kind, 'timeout')
  assert.equal(timedOut.totalConfirmed, 0)
  assert.equal(timedOut.confirmed.career_profile, 0)

  // Same wording as the transcript flow's timeout: one incident, one sentence,
  // whichever surface the student happens to be on.
  assert.match(timedOut.message, /taking longer than expected/)
  assert.match(timedOut.message, /still be starting up/)

  // Must not be swallowed by the generic unknown-status branch, which would
  // print "Could not confirm your records (status -1)".
  assert.doesNotMatch(timedOut.message, /status -1/)

  assert.ok(REQUEST_TIMEOUT_STATUS < 0)
  assert.ok(CONFIRM_TIMEOUT_MS >= 60_000)
})

// ── edit diffing ────────────────────────────────────────────────────────────

test('changedFields returns only genuinely changed editable fields', () => {
  const original = { id: 'c1', name: 'AWS', issuer: 'Amazon', status: 'completed', date: '2024' }
  const draft = { ...original, issuer: 'Amazon Web Services' }

  assert.deepEqual(changedFields('certifications', original, draft), {
    issuer: 'Amazon Web Services',
  })
  assert.deepEqual(changedFields('certifications', original, { ...original }), {})
})

test('changedFields never includes system-managed or foreign fields', () => {
  const original = { id: 'c1', name: 'AWS' }
  const draft = {
    id: 'hijacked',
    name: 'AWS',
    student_id: 'someone-else',
    confirmed_at: '2026-01-01',
    source: 'manual',
    employer: 'wrong table',
  }

  assert.deepEqual(changedFields('certifications', original, draft), {})
})

test('changedFields treats blank text as null and compares lists by value', () => {
  assert.deepEqual(changedFields('certifications', { issuer: 'Amazon' }, { issuer: '   ' }), {
    issuer: null,
  })
  assert.deepEqual(changedFields('certifications', { issuer: null }, { issuer: '' }), {})
  assert.deepEqual(
    changedFields('projects', { tools: ['React', 'Vite'] }, { tools: ['React', 'Vite'] }),
    {},
  )
  assert.deepEqual(
    changedFields('projects', { tools: ['React'] }, { tools: ['React', 'Vite'] }),
    { tools: ['React', 'Vite'] },
  )
  // Order matters -- a reorder is a real change.
  assert.deepEqual(
    changedFields('projects', { tools: ['A', 'B'] }, { tools: ['B', 'A'] }),
    { tools: ['B', 'A'] },
  )
})

test('normalizeFieldValue trims, nulls blanks, and cleans lists', () => {
  assert.equal(normalizeFieldValue('  hello  '), 'hello')
  assert.equal(normalizeFieldValue('   '), null)
  assert.equal(normalizeFieldValue(''), null)
  assert.equal(normalizeFieldValue(undefined), null)
  assert.equal(normalizeFieldValue(null), null)
  assert.deepEqual(normalizeFieldValue([' a ', '', 'b']), ['a', 'b'])
})

test('list inputs round-trip through the comma-separated editor form', () => {
  assert.deepEqual(parseListInput('React, Vite ,  TypeScript'), ['React', 'Vite', 'TypeScript'])
  assert.deepEqual(parseListInput(''), [])
  assert.deepEqual(parseListInput('  ,  , '), [])
  assert.deepEqual(parseListInput(null), [])
  assert.equal(formatListInput(['React', 'Vite']), 'React, Vite')
  assert.equal(formatListInput(null), '')
  assert.equal(formatListInput('not a list'), '')
  assert.deepEqual(parseListInput(formatListInput(['A', 'B'])), ['A', 'B'])
})
