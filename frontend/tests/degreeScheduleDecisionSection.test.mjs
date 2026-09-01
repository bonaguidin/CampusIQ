import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(
  new URL('../src/components/DegreeScheduleDecisionSection.tsx', import.meta.url),
  'utf8',
)

test('decision section exposes the required student-readable states', () => {
  assert.match(source, /Decisions needed to complete your plan/)
  assert.match(source, /Choice required/)
  assert.match(source, /Can't auto-verify/)
  assert.match(source, /Course data unavailable/)
  assert.match(source, /can't automatically verify this requirement is satisfied/)
})

test('candidate paths render course metadata as one grouped option', () => {
  assert.match(source, /Option \{optionNumber\}/)
  assert.match(source, /candidate\.candidate_courses\.map/)
  assert.match(source, /course\.course_code/)
  assert.match(source, /course\.title !== null/)
  assert.match(source, /course\.credits !== null/)
  assert.match(source, /candidate\.additional_credits/)
  assert.match(source, /Courses included in option/)
})

test('decision section exposes semantic choice controls without recommendation or availability claims', () => {
  assert.match(source, /Choose.*option/)
  assert.match(source, /Change choice/)
  assert.match(source, /Clear choice/)
  assert.match(source, /Clear saved choice/)
  assert.match(source, /Selected/)
  assert.doesNotMatch(source, /Recommended|Best option|Preferred|Top choice/)
  assert.doesNotMatch(source, /Offered Spring|Offered Fall|Available next semester/)
  assert.doesNotMatch(source, /existing_contribution|required_credits|remaining_credits/)
})
