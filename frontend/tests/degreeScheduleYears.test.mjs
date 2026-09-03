import test from 'node:test'
import assert from 'node:assert/strict'

import {
  academicYearKey,
  academicYearLabel,
  buildDegreeScheduleYears,
  formatGradeBadge,
  semesterState,
} from '../src/lib/degreeScheduleYears.mjs'

const TODAY = new Date(2026, 7, 24) // 2026-08-24, matches currentDate in this session

const term = (over) => ({
  key: `${over.year}-${over.season}`,
  id: `${over.year}-${over.season}-id`,
  label: `${over.season} ${over.year}`,
  sequence: null,
  start_date: null,
  end_date: null,
  enrolled: false,
  is_upcoming: false,
  ...over,
})

const record = (over) => ({
  id: `rec-${over.course_code}`,
  term_id: null,
  course_code: 'XXXX 000',
  title: null,
  credit_hours: 3,
  letter_grade: null,
  status: 'completed',
  ...over,
})

const plannedRow = (over) => ({
  id: `plan-${over.course_code}`,
  term_id: null,
  course_code: 'XXXX 000',
  title: null,
  credit_hours: 3,
  catalog_course_id: null,
  created_at: '2026-09-01T00:00:00Z',
  kind: 'planned',
  ...over,
})

const GRADING_SCHEMA = {
  institutionId: 'inst-1',
  usesPlusMinus: true,
  grades: [
    { letter: 'A', points: 4.0, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'B+', points: 3.3, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'P', points: null, counts_toward_gpa: false, counts_toward_credit: true },
  ],
}

// ── academicYearKey / academicYearLabel ─────────────────────────────────────

test('Fall pairs with the following Spring under the Fall calendar year', () => {
  assert.equal(academicYearKey(2026, 'Fall'), 2026)
  assert.equal(academicYearKey(2027, 'Spring'), 2026)
})

test('an intersession season is out of scope for year bucketing', () => {
  assert.equal(academicYearKey(2026, 'Summer'), null)
})

test('ordinal labels count up, falling back past the named words', () => {
  assert.equal(academicYearLabel(0), 'First year')
  assert.equal(academicYearLabel(3), 'Fourth year')
  assert.equal(academicYearLabel(6), 'Year 7')
})

// ── formatGradeBadge ─────────────────────────────────────────────────────────

test('formats a mapped grade with its GPA points', () => {
  assert.equal(formatGradeBadge('B+', GRADING_SCHEMA), 'B+ (3.3)')
})

test('falls back to the bare letter when the grade has no points', () => {
  assert.equal(formatGradeBadge('P', GRADING_SCHEMA), 'P')
})

test('falls back to the bare letter when the grade is unmapped entirely', () => {
  assert.equal(formatGradeBadge('W', GRADING_SCHEMA), 'W')
})

test('returns null for no grade', () => {
  assert.equal(formatGradeBadge(null, GRADING_SCHEMA), null)
})

// ── semesterState ────────────────────────────────────────────────────────────

test('a term with no calendar row at all is future', () => {
  assert.equal(semesterState(null, TODAY), 'future')
})

test('a term whose dates have passed is past', () => {
  const t = term({ year: 2025, season: 'Fall', start_date: '2025-08-25', end_date: '2025-12-10' })
  assert.equal(semesterState(t, TODAY), 'past')
})

test('a term underway today is in_progress', () => {
  const t = term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' })
  assert.equal(semesterState(t, TODAY), 'in_progress')
})

test('a term that has not started yet is future', () => {
  const t = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  assert.equal(semesterState(t, TODAY), 'future')
})

// ── buildDegreeScheduleYears ─────────────────────────────────────────────────

test('groups Fall/Spring terms into one academic year each, ordered ascending', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [
      term({ year: 2025, season: 'Fall', start_date: '2025-08-25', end_date: '2025-12-10' }),
      term({ year: 2026, season: 'Spring', start_date: '2026-01-20', end_date: '2026-05-10' }),
      term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' }),
    ],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  })
  assert.deepEqual(years.map((y) => y.label), ['First year', 'Second year'])
  assert.deepEqual(years.map((y) => y.semesters.map((s) => s.termKey)), [
    ['2025-Fall', '2026-Spring'],
    ['2026-Fall', '2027-Spring'],
  ])
})

test('a past semester carries real coursework with grade+GPA badges, dropped courses excluded', () => {
  const fall2025 = term({ year: 2025, season: 'Fall', start_date: '2025-08-25', end_date: '2025-12-10' })
  const years = buildDegreeScheduleYears({
    realTerms: [fall2025],
    scheduleTerms: [],
    courseRecords: [
      record({ course_code: 'CSCE 121', term_id: fall2025.id, letter_grade: 'A', status: 'completed', credit_hours: 4 }),
      record({ course_code: 'MATH 151', term_id: fall2025.id, letter_grade: 'B+', status: 'completed', credit_hours: 3 }),
      record({ course_code: 'PHYS 218', term_id: fall2025.id, letter_grade: 'A', status: 'dropped', credit_hours: 4 }),
    ],
    gradingSchema: GRADING_SCHEMA,
    today: TODAY,
  })
  const fall = years[0].semesters[0]
  assert.equal(fall.state, 'past')
  assert.equal(fall.totalCreditsLabel, '7 credits')
  assert.deepEqual(fall.courses.map((c) => c.course_code), ['CSCE 121', 'MATH 151'])
  assert.deepEqual(fall.courses.map((c) => c.gradeBadge), ['A (4.0)', 'B+ (3.3)'])
})

test('an in-progress semester never carries a grade badge, even with a current letter_grade entered', () => {
  const fall2026 = term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' })
  const years = buildDegreeScheduleYears({
    realTerms: [fall2026],
    scheduleTerms: [],
    courseRecords: [
      record({ course_code: 'CSCE 221', term_id: fall2026.id, letter_grade: 'A', status: 'in_progress', credit_hours: 3 }),
    ],
    gradingSchema: GRADING_SCHEMA,
    today: TODAY,
  })
  const fall = years[0].semesters[0]
  assert.equal(fall.state, 'in_progress')
  assert.equal(fall.courses[0].gradeBadge, null)
})

test('a future semester has no confirmed courses; the scheduler plan becomes suggestions', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [],
    scheduleTerms: [
      {
        term_key: '2027-Spring',
        total_credit_hours: 6,
        courses: [
          { course_code: 'CSCE 314', credit_hours: 3, requirement_group_id: 'g1', limitations: [] },
          { course_code: 'CSCE 331', credit_hours: 3, requirement_group_id: 'g2', limitations: [] },
        ],
      },
    ],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.equal(spring.state, 'future')
  assert.equal(spring.totalCreditsLabel, 'Not scheduled')
  assert.deepEqual(spring.courses, [])
  assert.deepEqual(spring.suggestedCourses.map((c) => c.course_code), ['CSCE 314', 'CSCE 331'])
})

test('a year appears from scheduler output alone, with no real academic_terms row yet', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [],
    scheduleTerms: [
      { term_key: '2029-Fall', total_credit_hours: 3, courses: [{ course_code: 'CSCE 482', credit_hours: 3, requirement_group_id: 'g1', limitations: [] }] },
    ],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  })
  assert.equal(years.length, 1)
  assert.equal(years[0].yearKey, 2029)
})

test('no data at all yields no years, not a crash', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  })
  assert.deepEqual(years, [])
})

test('a real term with no materialized id (never enrolled) matches no course_records, even ones with null term_id', () => {
  const fall2026 = term({ year: 2026, season: 'Fall', id: null, start_date: '2025-01-01', end_date: '2025-05-01' })
  const years = buildDegreeScheduleYears({
    realTerms: [fall2026],
    scheduleTerms: [],
    courseRecords: [
      record({ course_code: 'STRAY 101', term_id: null, status: 'completed' }),
    ],
    gradingSchema: null,
    today: TODAY,
  })
  const fall = years[0].semesters[0]
  assert.equal(fall.state, 'past')
  assert.deepEqual(fall.courses, [])
})

// ── plannedCourses (student-added, future terms only) ───────────────────────

test('plannedCourses is optional: absent input yields an empty planned array on every semester', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  })
  for (const year of years) {
    for (const semester of year.semesters) assert.deepEqual(semester.planned, [])
  }
})

test('a student-added course for a future term appears in semester.planned with id/code/title/credits', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: [
      plannedRow({ id: 'p1', course_code: 'CSCE 469', title: 'Special Topics', credit_hours: 3, term_id: spring2027.id }),
    ],
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.equal(spring.state, 'future')
  assert.deepEqual(spring.planned, [
    { id: 'p1', course_code: 'CSCE 469', title: 'Special Topics', credit_hours: 3 },
  ])
})

test('a course in BOTH the scheduler plan and the student plan for one term appears once, under planned, not suggested (case-insensitive)', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [
      {
        term_key: '2027-Spring',
        total_credit_hours: 6,
        courses: [
          { course_code: 'CSCE 314', credit_hours: 3, requirement_group_id: 'g1', limitations: [] },
          { course_code: 'CSCE 331', credit_hours: 3, requirement_group_id: 'g2', limitations: [] },
        ],
      },
    ],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: [
      // lower-case on purpose -- the reconciliation is case-insensitive
      plannedRow({ id: 'p1', course_code: 'csce 314', title: null, credit_hours: 3, term_id: spring2027.id }),
    ],
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.deepEqual(spring.planned.map((c) => c.course_code), ['csce 314'])
  assert.deepEqual(spring.suggestedCourses.map((c) => c.course_code), ['CSCE 331'])
})

test('a planned row is not shown against a future term with no materialized academic_terms id', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', id: null, start_date: '2027-01-19', end_date: '2027-05-11' })
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: [plannedRow({ id: 'p1', course_code: 'CSCE 469', term_id: null })],
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.deepEqual(spring.planned, [])
})

test('removing a planned row from the input removes it from the term card (disappears on next load)', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const args = {
    realTerms: [spring2027],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  }
  const withRow = buildDegreeScheduleYears({
    ...args,
    plannedCourses: [plannedRow({ id: 'p1', course_code: 'CSCE 469', term_id: spring2027.id })],
  })
  assert.equal(withRow[0].semesters.find((s) => s.termKey === '2027-Spring').planned.length, 1)

  const afterRemoval = buildDegreeScheduleYears({ ...args, plannedCourses: [] })
  assert.deepEqual(afterRemoval[0].semesters.find((s) => s.termKey === '2027-Spring').planned, [])
})

test('planned rows never appear on a past or in-progress term card', () => {
  const fall2025 = term({ year: 2025, season: 'Fall', start_date: '2025-08-25', end_date: '2025-12-10' })
  const years = buildDegreeScheduleYears({
    realTerms: [fall2025],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    // A stray planned row pointing at a past term must not surface here.
    plannedCourses: [plannedRow({ id: 'p1', course_code: 'HIST 101', term_id: fall2025.id })],
  })
  const fall = years[0].semesters[0]
  assert.equal(fall.state, 'past')
  assert.deepEqual(fall.planned, [])
})
