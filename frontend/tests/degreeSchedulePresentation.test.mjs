import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildDegreeScheduleDecisions,
  degreeScheduleContentState,
  adviserReviewCount,
  displayTermKey,
  formatCredits,
  nextPlannedTerm,
  termPresentation,
} from '../src/lib/degreeSchedulePresentation.mjs'

test('term presentation preserves backend order, courses, totals, and limitations', () => {
  const terms = [
    {
      term_key: '2027-Spring',
      total_credit_hours: 6,
      courses: [{ course_code: 'CS 3341', credit_hours: 3, requirement_group_id: 'g1', limitations: ['First limitation', 'Second limitation'] }],
    },
    {
      term_key: '2026-Fall',
      total_credit_hours: 12,
      courses: [{ course_code: 'CS 2341', credit_hours: 3, requirement_group_id: 'g1', limitations: [] }],
    },
  ]

  const result = termPresentation(terms)

  assert.deepEqual(result.map((term) => term.term_key), ['2027-Spring', '2026-Fall'])
  assert.equal(result[0].displayName, 'Spring 2027')
  assert.equal(result[0].totalLabel, '6 credits')
  assert.equal(result[0].courses[0].course_code, 'CS 3341')
  assert.deepEqual(result[0].courses[0].limitations, ['First limitation', 'Second limitation'])
})

test('term and credit labels handle known, unknown, singular, and fractional values', () => {
  assert.equal(displayTermKey('2028-Fall'), 'Fall 2028')
  assert.equal(displayTermKey('Summer-Session-A'), 'Summer-Session-A')
  assert.equal(formatCredits(1), '1 credit')
  assert.equal(formatCredits(1.5), '1.5 credits')
})

const candidate = (id, codes) => ({
  candidate_id: id,
  requirement_group_id: 'choice',
  requirement_name: 'Statistical Methods',
  course_codes: codes,
  unresolved_course_codes: [],
  candidate_courses: codes.map((code) => ({ course_code: code, title: `${code} title`, credits: 3 })),
  existing_contribution: 0,
  additional_course_count: codes.length,
  additional_credits: codes.length * 3,
  academic_feasibility: 'FEASIBLE',
  completion_term_index: 1,
  limitations: [], source_order: [], exclusion_reasons: [], exclusion_details: [],
})

test('decision presentation joins feasible candidates in API order and suppresses duplicate legacy rows', () => {
  const candidates = [candidate('third', ['CS 3333']), candidate('first', ['CS 1111']), candidate('second', ['CS 2222'])]
  const schedule = {
    student_id: 'sid', program_id: 'pid', status: 'SCHEDULED', failure: null, terms: [],
    decisions: [{
      requirement_group_id: 'choice', requirement_name: 'Statistical Methods', state: 'CHOICE_REQUIRED',
      feasible_candidate_ids: ['first', 'second', 'third'], excluded_candidate_ids: [], selected_candidate_id: null,
    }],
    candidate_sets: [{ requirement_group_id: 'choice', requirement_name: 'Statistical Methods', feasible_candidates: candidates, excluded_candidates: [] }],
    unscheduled: [
      { requirement_group_id: 'choice', name: 'Statistical Methods', reason: 'SELECTION_DEFERRED' },
      { requirement_group_id: 'ucc', name: 'University Core Curriculum', reason: 'FREEFORM_MANUAL_REVIEW' },
    ],
  }

  const result = buildDegreeScheduleDecisions(schedule)
  assert.equal(result.decisions[0].validOptionLabel, '3 valid options')
  assert.deepEqual(result.decisions[0].candidates.map((item) => item.candidate_id), ['first', 'second', 'third'])
  assert.deepEqual(result.legacyRequirements.map((item) => item.requirement_group_id), ['ucc'])
})

test('decision presentation orders action states, hides auto-selected cards, and preserves multi-course paths', () => {
  const multi = candidate('multi', ['CEE 2302', 'CS 3377'])
  const schedule = {
    student_id: 'sid', program_id: 'pid', status: 'SCHEDULED', failure: null, terms: [], unscheduled: [],
    decisions: [
      { requirement_group_id: 'data', requirement_name: 'Unknown', state: 'DATA_UNRESOLVED', feasible_candidate_ids: [], excluded_candidate_ids: ['x'], selected_candidate_id: null },
      { requirement_group_id: 'auto', requirement_name: 'Automatic', state: 'AUTO_SELECTED', feasible_candidate_ids: ['a'], excluded_candidate_ids: [], selected_candidate_id: 'a' },
      { requirement_group_id: 'review', requirement_name: 'Review', state: 'ADVISER_REVIEW', feasible_candidate_ids: [], excluded_candidate_ids: ['r'], selected_candidate_id: null },
      { requirement_group_id: 'choice', requirement_name: 'Leadership', state: 'CHOICE_REQUIRED', feasible_candidate_ids: ['multi'], excluded_candidate_ids: [], selected_candidate_id: null },
    ],
    candidate_sets: [{ requirement_group_id: 'choice', requirement_name: 'Leadership', feasible_candidates: [multi], excluded_candidates: [] }],
  }

  const result = buildDegreeScheduleDecisions(schedule)
  assert.deepEqual(result.decisions.map((item) => item.state), ['CHOICE_REQUIRED', 'ADVISER_REVIEW', 'DATA_UNRESOLVED'])
  assert.equal(result.decisions[0].candidates.length, 1)
  assert.deepEqual(result.decisions[0].candidates[0].course_codes, ['CEE 2302', 'CS 3377'])
})

test('planner summary derives next term and adviser-review count from the existing schedule', () => {
  const result = {
    student_id: 'sid', program_id: 'pid', status: 'SCHEDULED', failure: null,
    terms: [{ term_key: '2026-Fall', courses: [], total_credit_hours: 15 }],
    unscheduled: [
      { requirement_group_id: 'g1', name: 'Technical Electives', reason: 'FREEFORM_MANUAL_REVIEW' },
      { requirement_group_id: 'g2', name: 'Other', reason: 'SELECTION_DEFERRED' },
    ],
  }
  assert.equal(nextPlannedTerm(result).displayName, 'Fall 2026')
  assert.equal(nextPlannedTerm(result).totalLabel, '15 credits')
  assert.equal(adviserReviewCount(result), 1)
  assert.equal(nextPlannedTerm(null), null)
})

test('empty schedule presentation remains empty', () => {
  assert.deepEqual(termPresentation([]), [])
})

test('schedule content states distinguish scheduled, empty, skipped, and infeasible results', () => {
  const base = { student_id: 'sid', program_id: 'pid', unscheduled: [], failure: null }
  assert.equal(degreeScheduleContentState({ ...base, status: 'SCHEDULED', terms: [{ term_key: '2026-Fall', courses: [], total_credit_hours: 0 }] }), 'scheduled')
  assert.equal(degreeScheduleContentState({ ...base, status: 'SCHEDULED', terms: [] }), 'empty')
  assert.equal(degreeScheduleContentState({ ...base, status: 'ERROR', terms: [], failure: { error_class: 'OverConstrained', safe_message: 'No room.' } }), 'infeasible')
  assert.equal(degreeScheduleContentState({ feature: 'SCHEDULE', status: 'skipped', summary: 'Not supported.', data: {}, errors: [] }), 'skipped')
})
