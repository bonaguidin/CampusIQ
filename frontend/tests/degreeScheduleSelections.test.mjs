import assert from 'node:assert/strict'
import test from 'node:test'
import {
  choiceConflictMessage,
  isCurrentRequirementCandidate,
  removeRequirementSelection,
  replaceRequirementSelection,
} from '../src/lib/degreeScheduleSelections.mjs'

const candidate = (id, codes) => ({ candidate_id: id, course_codes: codes })
const selected = (requirement, id, codes) => ({
  requirement_group_id: requirement, candidate_id: id, course_codes: codes,
})

test('backend conflict codes map to safe actionable student copy', () => {
  assert.match(choiceConflictMessage('SCHEDULE_VERSION_CONFLICT'), /degree plan changed/)
  assert.match(choiceConflictMessage('ACADEMIC_REVISION_CONFLICT'), /academic information changed/)
  assert.match(choiceConflictMessage('LOCK_CANDIDATE_EXCLUDED'), /no longer academically available/)
  assert.match(choiceConflictMessage('LOCK_CANDIDATE_NOT_FOUND'), /option changed/)
  assert.match(choiceConflictMessage('LOCK_PATH_MISMATCH'), /option changed/)
  assert.match(choiceConflictMessage('LOCK_CHOICE_NO_LONGER_REQUIRED'), /no longer needs/)
  assert.match(choiceConflictMessage('LOCK_INCOMPATIBLE'), /cannot all be used together/)
  assert.match(choiceConflictMessage('RESELECTION_REQUIRED'), /needs attention/)
  assert.doesNotMatch(choiceConflictMessage('LOCK_INCOMPATIBLE'), /LOCK_/)
})

test('complete-set helpers add, replace, and remove while preserving unrelated choices', () => {
  const first = replaceRequirementSelection([], 'R1', candidate('C1', ['A']))
  assert.deepEqual(first, [selected('R1', 'C1', ['A'])])
  const second = replaceRequirementSelection(first, 'R2', candidate('C2', ['B']))
  assert.deepEqual(second, [selected('R1', 'C1', ['A']), selected('R2', 'C2', ['B'])])
  const changed = replaceRequirementSelection(second, 'R1', candidate('C3', ['C']))
  assert.deepEqual(changed, [selected('R2', 'C2', ['B']), selected('R1', 'C3', ['C'])])
  assert.deepEqual(removeRequirementSelection(changed, 'R1'), [selected('R2', 'C2', ['B'])])
  assert.deepEqual(removeRequirementSelection(first, 'R1'), [])
})

test('multi-course selection preserves authoritative path ordering and current identity', () => {
  const result = replaceRequirementSelection([], 'R1', candidate('bundle', ['CEE 2302', 'CS 3377']))
  assert.deepEqual(result[0].course_codes, ['CEE 2302', 'CS 3377'])
  assert.equal(isCurrentRequirementCandidate(result, 'R1', 'bundle'), true)
  assert.equal(isCurrentRequirementCandidate(result, 'R1', 'other'), false)
})
