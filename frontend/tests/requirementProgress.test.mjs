import test from 'node:test'
import assert from 'node:assert/strict'

import { countSatisfiedLeafGroups } from '../src/lib/requirementProgress.mjs'

const leaf = (status, over = {}) => ({
  id: `leaf-${status}-${Math.random()}`,
  coursedog_rule_id: 'rule-1',
  name: 'A leaf requirement',
  group_type: 'enumerated_courses',
  status,
  detail: null,
  matched_course_codes: [],
  children: [],
  ...over,
})

const parent = (children, over = {}) => ({
  id: 'parent-1',
  coursedog_rule_id: 'rule-parent',
  name: 'A compound requirement',
  group_type: 'compound_all',
  status: 'IN_PROGRESS',
  detail: null,
  matched_course_codes: [],
  children,
  ...over,
})

test('counts only leaf nodes, ignoring compound parents', () => {
  const groups = [
    leaf('SATISFIED'),
    parent([leaf('SATISFIED'), leaf('NOT_STARTED')]),
    parent([parent([leaf('SATISFIED'), leaf('IN_PROGRESS')])]),
  ]
  // Leaves: SATISFIED, SATISFIED, NOT_STARTED, SATISFIED, IN_PROGRESS = 5 total, 3 satisfied
  assert.deepEqual(countSatisfiedLeafGroups(groups), { satisfied: 3, total: 5 })
})

test('MANUAL_REVIEW and IN_PROGRESS leaves count toward total but not satisfied', () => {
  const groups = [leaf('SATISFIED'), leaf('MANUAL_REVIEW'), leaf('IN_PROGRESS'), leaf('NOT_STARTED')]
  assert.deepEqual(countSatisfiedLeafGroups(groups), { satisfied: 1, total: 4 })
})

test('empty tree returns zero/zero, not a divide-by-zero blowup', () => {
  assert.deepEqual(countSatisfiedLeafGroups([]), { satisfied: 0, total: 0 })
  assert.deepEqual(countSatisfiedLeafGroups(undefined), { satisfied: 0, total: 0 })
})

test('a compound node with no children at all is treated as its own leaf', () => {
  // Degenerate but real: a group_type of compound_* whose children array
  // happens to be empty still has to count as something, not vanish.
  const groups = [parent([], { status: 'NOT_STARTED' })]
  assert.deepEqual(countSatisfiedLeafGroups(groups), { satisfied: 0, total: 1 })
})
