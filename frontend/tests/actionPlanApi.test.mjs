import assert from 'node:assert/strict'
import test from 'node:test'

import { analyzeActionPlan } from '../src/api/analysisApi.mjs'

function fakeFetch(calls, body = { feature: 'ACTION_PLAN', status: 'success', summary: '', action_plan: {}, dependency_order: {} }) {
  return async (url, init) => {
    calls.push({ url, init })
    return {
      ok: true,
      status: 200,
      json: async () => body,
    }
  }
}

test('analyzeActionPlan calls the action-plan route with only target_role', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls))

  await analyzeActionPlan({ slug: null, accessToken: 'session-token' }, 'Robotics Engineer')

  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/v2/student/me/action-plan')
  assert.equal(calls[0].init.method, 'POST')
  assert.equal(calls[0].init.headers.Authorization, 'Bearer session-token')
  assert.deepEqual(JSON.parse(calls[0].init.body), { target_role: 'Robotics Engineer' })
})

test('analyzeActionPlan omits the body entirely when no role is given', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls))

  await analyzeActionPlan({ slug: null, accessToken: 'session-token' })

  assert.equal(calls[0].init.body, undefined)
  assert.equal(calls[0].init.headers['Content-Type'], undefined)
})

test('analyzeActionPlan request never carries a student id, need objects, plan nodes, or graph edges', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls))

  await analyzeActionPlan({ slug: null, accessToken: 'session-token' }, 'Data Scientist')

  const sent = JSON.parse(calls[0].init.body)
  assert.deepEqual(Object.keys(sent), ['target_role'])
  assert.equal('student_id' in sent, false)
  assert.equal('career_needs' in sent, false)
  assert.equal('course_discovery_result' in sent, false)
  assert.equal('nodes' in sent, false)
  assert.equal('edges' in sent, false)
})

test('analyzeActionPlan has no demo/slug route -- it is authenticated only', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls))

  await analyzeActionPlan({ slug: 'demo-student', accessToken: 'session-token' })

  assert.equal(calls[0].url, '/api/v2/student/me/action-plan')
})

test('analyzeActionPlan requires a session', () => {
  assert.throws(
    () => analyzeActionPlan({ slug: null, accessToken: null }),
    /Authenticated analysis requires a session\./,
  )
})
