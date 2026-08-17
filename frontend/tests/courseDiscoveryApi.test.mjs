import assert from 'node:assert/strict'
import test from 'node:test'

import { analyzeCourseDiscovery } from '../src/api/analysisApi.mjs'

function fakeFetch(calls, body = { feature: 'COURSE_DISCOVERY', status: 'success', summary: '', data: {}, errors: [] }) {
  return async (url, init) => {
    calls.push({ url, init })
    return {
      ok: true,
      status: 200,
      json: async () => body,
    }
  }
}

test('analyzeCourseDiscovery calls the authenticated route with only target_role', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls))

  await analyzeCourseDiscovery({ slug: null, accessToken: 'session-token' }, 'Software Engineer')

  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/v2/student/me/analyze/course-discovery')
  assert.equal(calls[0].init.method, 'POST')
  assert.equal(calls[0].init.headers.Authorization, 'Bearer session-token')
  assert.deepEqual(JSON.parse(calls[0].init.body), { target_role: 'Software Engineer' })
})

test('analyzeCourseDiscovery omits the body entirely when no role is given (single-role auto-select)', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls))

  await analyzeCourseDiscovery({ slug: null, accessToken: 'session-token' })

  assert.equal(calls[0].init.body, undefined)
  assert.equal(calls[0].init.headers['Content-Type'], undefined)
})

test('analyzeCourseDiscovery request never carries a student id, need objects, or a course-discovery result', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls))

  await analyzeCourseDiscovery({ slug: null, accessToken: 'session-token' }, 'Data Scientist')

  const sent = JSON.parse(calls[0].init.body)
  assert.deepEqual(Object.keys(sent), ['target_role'])
  assert.equal('student_id' in sent, false)
  assert.equal('career_needs' in sent, false)
  assert.equal('course_discovery_result' in sent, false)
})

test('analyzeCourseDiscovery uses the demo route when a slug identity is supplied, matching FIT/GAP/SHIFT', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls))

  await analyzeCourseDiscovery({ slug: 'demo-student', accessToken: null })

  assert.equal(calls[0].url, '/api/students/demo-student/analyze/course-discovery')
  assert.equal(calls[0].init.headers.Authorization, undefined)
})

test('analyzeCourseDiscovery requires a session for the authenticated path', () => {
  assert.throws(
    () => analyzeCourseDiscovery({ slug: null, accessToken: null }),
    /Authenticated analysis requires a session\./,
  )
})
