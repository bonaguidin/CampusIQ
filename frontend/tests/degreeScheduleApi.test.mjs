import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DegreeScheduleChoiceError,
  fetchDegreeSchedule,
  isSkippedDegreeSchedule,
  updateDegreeScheduleChoices,
} from '../src/api/degreeSchedule.mjs'

function fakeFetch(calls, status, body) {
  return async (url, init) => {
    calls.push({ url, init })
    return { status, json: async () => body }
  }
}

test('fetchDegreeSchedule calls the authenticated GET route', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls, 200, {
    student_id: 'sid', program_id: 'pid', terms: [], unscheduled: [], status: 'SCHEDULED', failure: null,
    schedule_version: `sha256:${'a'.repeat(64)}`,
  }))

  await fetchDegreeSchedule({ slug: null, accessToken: 'session-token' })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/v2/student/me/schedule')
  assert.equal(calls[0].init.method, 'GET')
  assert.equal(calls[0].init.headers.Authorization, 'Bearer session-token')
})

test('updateDegreeScheduleChoices sends the authoritative complete set', async (t) => {
  const calls = []
  const selections = [{
    requirement_group_id: 'R1', candidate_id: 'C1', course_codes: ['CEE 2302', 'CS 3377'],
  }]
  t.mock.method(globalThis, 'fetch', fakeFetch(calls, 200, {
    status: 'APPLIED', schedule_version: `sha256:${'d'.repeat(64)}`, selections,
  }))
  const result = await updateDegreeScheduleChoices('token', {
    scheduleVersion: `sha256:${'a'.repeat(64)}`, selections,
  })
  assert.equal(calls[0].url, '/api/v2/student/me/schedule/choices')
  assert.equal(calls[0].init.method, 'PUT')
  assert.equal(calls[0].init.headers.Authorization, 'Bearer token')
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    schedule_version: `sha256:${'a'.repeat(64)}`, selections,
  })
  assert.equal(result.status, 'APPLIED')
})

test('updateDegreeScheduleChoices preserves structured conflict codes', async (t) => {
  t.mock.method(globalThis, 'fetch', fakeFetch([], 409, {
    detail: { code: 'LOCK_INCOMPATIBLE' },
  }))
  await assert.rejects(
    () => updateDegreeScheduleChoices('token', { scheduleVersion: 'version', selections: [] }),
    (error) => error instanceof DegreeScheduleChoiceError && error.code === 'LOCK_INCOMPATIBLE',
  )
})

test('fetchDegreeSchedule preserves the complete schedule response', async (t) => {
  const payload = {
    student_id: 'sid',
    program_id: 'pid',
    status: 'SCHEDULED',
    failure: null,
    schedule_version: `sha256:${'b'.repeat(64)}`,
    terms: [{
      term_key: '2026-Fall',
      total_credit_hours: 6,
      courses: [{ course_code: 'CS 2341', credit_hours: 3, requirement_group_id: 'g1', limitations: ['Review external prerequisite.'] }],
    }],
    unscheduled: [{ requirement_group_id: 'g2', name: 'Technical Electives', reason: 'FREEFORM_MANUAL_REVIEW' }],
    decisions: [{
      requirement_group_id: 'g1', requirement_name: 'Leadership', state: 'AUTO_SELECTED',
      feasible_candidate_ids: ['candidate-1'], excluded_candidate_ids: ['candidate-2'],
      selected_candidate_id: 'candidate-1',
    }],
    candidate_sets: [{
      requirement_group_id: 'g1', requirement_name: 'Leadership',
      feasible_candidates: [{
        candidate_id: 'candidate-1', requirement_group_id: 'g1', requirement_name: 'Leadership',
        course_codes: ['CEE 2302', 'CS 3377'], unresolved_course_codes: [],
        candidate_courses: [
          { course_code: 'CEE 2302', title: 'Authentic Leadership', credits: 3 },
          { course_code: 'CS 3377', title: 'Ethical Issues in Computing', credits: 3 },
        ],
        existing_contribution: 0,
        additional_course_count: 2, additional_credits: 6, academic_feasibility: 'FEASIBLE',
        completion_term_index: 1, limitations: [], source_order: [0, 1],
        exclusion_reasons: [], exclusion_details: [],
      }],
      excluded_candidates: [],
    }],
  }
  t.mock.method(globalThis, 'fetch', fakeFetch([], 200, payload))

  const result = await fetchDegreeSchedule({ slug: null, accessToken: 'session-token' })

  assert.deepEqual(result, payload)
  assert.equal(result.schedule_version, `sha256:${'b'.repeat(64)}`)
  assert.deepEqual(result.candidate_sets[0].feasible_candidates[0].course_codes, ['CEE 2302', 'CS 3377'])
  assert.equal(result.candidate_sets[0].feasible_candidates[0].candidate_courses[0].title, 'Authentic Leadership')
  assert.equal(isSkippedDegreeSchedule(result), false)
})

test('fetchDegreeSchedule returns a skipped FeatureResult', async (t) => {
  const skipped = {
    feature: 'SCHEDULE', status: 'skipped', summary: 'No supported program.', data: {}, errors: [], missing_fields: [],
  }
  t.mock.method(globalThis, 'fetch', fakeFetch([], 200, skipped))

  const result = await fetchDegreeSchedule({ slug: null, accessToken: 'session-token' })

  assert.equal(isSkippedDegreeSchedule(result), true)
  assert.equal(result.summary, skipped.summary)
})

test('fetchDegreeSchedule throws with backend detail on HTTP error', async (t) => {
  t.mock.method(globalThis, 'fetch', fakeFetch([], 502, { detail: 'Schedule is unavailable.' }))

  await assert.rejects(
    () => fetchDegreeSchedule({ slug: null, accessToken: 'session-token' }),
    /Schedule is unavailable\./,
  )
})

test('fetchDegreeSchedule uses the demo route when a slug identity is supplied, with no Authorization header', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls, 200, {
    student_id: 'demo:ethanBrooks', program_id: 'local:smu-cs-bs', terms: [], unscheduled: [], status: 'SCHEDULED', failure: null,
    schedule_version: `sha256:${'c'.repeat(64)}`,
  }))

  await fetchDegreeSchedule({ slug: 'ethanBrooks', accessToken: null })

  assert.equal(calls[0].url, '/api/students/ethanBrooks/schedule')
  assert.equal(calls[0].init.headers.Authorization, undefined)
})
