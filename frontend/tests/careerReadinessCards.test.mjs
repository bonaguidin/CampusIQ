import test from 'node:test'
import assert from 'node:assert/strict'

import { pickTopRole, pickBiggestGap } from '../src/lib/careerReadinessCards.mjs'

test('pickTopRole returns the first role_matches entry', () => {
  const fitData = {
    role_matches: [
      { role: 'Software Engineer', fit_level: 'high', rationale: '', supporting_signals: [], missing_signals: [] },
      { role: 'Data Analyst', fit_level: 'medium', rationale: '', supporting_signals: [], missing_signals: [] },
    ],
    overall_fit_summary: '',
  }
  assert.equal(pickTopRole(fitData)?.role, 'Software Engineer')
})

test('pickTopRole handles no matches or missing data', () => {
  assert.equal(pickTopRole({ role_matches: [], overall_fit_summary: '' }), null)
  assert.equal(pickTopRole(null), null)
  assert.equal(pickTopRole(undefined), null)
})

test('pickBiggestGap prefers the first must-have gap', () => {
  const gapData = {
    readiness_score: 5,
    strengths: [],
    must_have_gaps: [
      { gap: 'System design', why_it_matters: 'x', how_to_close: 'y' },
      { gap: 'SQL', why_it_matters: 'x', how_to_close: 'y' },
    ],
    nice_to_have_gaps: [{ gap: 'GraphQL', why_it_helps: 'x', how_to_close: 'y' }],
    recommended_next_steps: [],
  }
  const result = pickBiggestGap(gapData)
  assert.equal(result?.gap, 'System design')
  assert.equal(result?.priority, 'must')
})

test('pickBiggestGap falls back to nice-to-have when there are no must-haves', () => {
  const gapData = {
    readiness_score: 8,
    strengths: [],
    must_have_gaps: [],
    nice_to_have_gaps: [{ gap: 'GraphQL', why_it_helps: 'x', how_to_close: 'y' }],
    recommended_next_steps: [],
  }
  const result = pickBiggestGap(gapData)
  assert.equal(result?.gap, 'GraphQL')
  assert.equal(result?.priority, 'nice')
})

test('pickBiggestGap returns null when both lists are empty or data is missing', () => {
  assert.equal(pickBiggestGap({ readiness_score: 10, strengths: [], must_have_gaps: [], nice_to_have_gaps: [], recommended_next_steps: [] }), null)
  assert.equal(pickBiggestGap(null), null)
  assert.equal(pickBiggestGap(undefined), null)
})
