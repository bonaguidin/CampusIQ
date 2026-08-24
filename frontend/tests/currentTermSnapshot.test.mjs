import test from 'node:test'
import assert from 'node:assert/strict'

import { currentTermSnapshot } from '../src/lib/currentTermSnapshot.mjs'

const term = (over) => ({ id: 'term-1', institution_id: 'inst-1', label: 'Fall 2026', year: 2026, season: 'fall', sequence: 1, ...over })

const course = (over) => ({
  id: `course-${Math.random()}`,
  term_id: 'term-1',
  institution_id: 'inst-1',
  course_code: 'CS 101',
  title: 'Intro to Computing',
  credit_hours: 3,
  letter_grade: null,
  credit_type: 'resident',
  status: 'in_progress',
  source: 'transcript_parse',
  ...over,
})

test('returns null when there is no in-progress coursework', () => {
  const courses = [course({ status: 'completed' }), course({ status: 'planned' })]
  assert.equal(currentTermSnapshot({ courses, terms: [term()] }), null)
})

test('returns null for an empty or missing course list', () => {
  assert.equal(currentTermSnapshot({ courses: [], terms: [term()] }), null)
  assert.equal(currentTermSnapshot({ courses: undefined, terms: [term()] }), null)
})

test('a single in-progress term returns its label, courses, and summed credits', () => {
  const courses = [
    course({ course_code: 'CS 101', credit_hours: 3 }),
    course({ course_code: 'MATH 251', credit_hours: 4 }),
    course({ course_code: 'CS 100', credit_hours: 1, status: 'completed' }),
  ]
  const result = currentTermSnapshot({ courses, terms: [term()] })
  assert.equal(result.termLabel, 'Fall 2026')
  assert.equal(result.totalCredits, 7)
  assert.equal(result.courses.length, 2)
})

test('multiple simultaneous in-progress terms union their courses and join their labels', () => {
  const terms = [term({ id: 'term-1', label: 'Fall 2026' }), term({ id: 'term-2', label: 'Summer 2026' })]
  const courses = [
    course({ term_id: 'term-1', course_code: 'CS 101', credit_hours: 3 }),
    course({ term_id: 'term-2', course_code: 'CS 200', credit_hours: 2 }),
  ]
  const result = currentTermSnapshot({ courses, terms })
  assert.equal(result.termLabel, 'Fall 2026, Summer 2026')
  assert.equal(result.totalCredits, 5)
  assert.equal(result.courses.length, 2)
})

test('an in-progress course with no term_id still counts toward courses/credits but not the label', () => {
  const courses = [course({ term_id: null, course_code: 'CS 101', credit_hours: 3 })]
  const result = currentTermSnapshot({ courses, terms: [term()] })
  assert.equal(result.termLabel, null)
  assert.equal(result.totalCredits, 3)
  assert.equal(result.courses.length, 1)
})
