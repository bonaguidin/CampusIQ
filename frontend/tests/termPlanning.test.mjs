import test from 'node:test'
import assert from 'node:assert/strict'

import {
  MIN_SEARCH_LENGTH,
  SEASON_ORDER,
  catalogSearchUrl,
  formatCredits,
  formatTermDates,
  normalizePlannedPayload,
  normalizeSearchPayload,
  normalizeTermsPayload,
  parseDate,
  pickDefaultTermKey,
  plannedCodes,
  plannedListUrl,
  plannedRemoveUrl,
  seasonOrdinal,
  sortTerms,
  termCourseGroups,
  termStatus,
} from '../src/lib/termPlanning.mjs'

const term = (over) => ({
  key: `${over.year}-${over.season}`,
  id: null,
  label: `${over.season} ${over.year}`,
  sequence: null,
  start_date: null,
  end_date: null,
  enrolled: false,
  is_upcoming: false,
  ...over,
})

const SUMMER_2026 = term({ year: 2026, season: 'Summer', start_date: '2026-05-26', end_date: '2026-08-06' })
const FALL_2026 = term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' })
const SPRING_2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })

// ── season ordering ─────────────────────────────────────────────────────────

test('season ordinals mirror SEASON_ORDER in transcript/terms.py', () => {
  assert.deepEqual(SEASON_ORDER, {
    Winter: 0, Spring: 1, May: 2, Summer: 3, August: 4, Fall: 5,
  })
})

test('SMU intersessions sort between the terms they fall between', () => {
  const ordered = sortTerms([
    term({ year: 2026, season: 'Fall' }),
    term({ year: 2026, season: 'August' }),
    term({ year: 2026, season: 'May' }),
    term({ year: 2026, season: 'Spring' }),
    term({ year: 2026, season: 'Summer' }),
    term({ year: 2026, season: 'Winter' }),
  ])
  assert.deepEqual(ordered.map((t) => t.season), [
    'Winter', 'Spring', 'May', 'Summer', 'August', 'Fall',
  ])
})

test('an unrecognized season sorts last within its own year', () => {
  const ordered = sortTerms([
    term({ year: 2027, season: 'Spring' }),
    term({ year: 2026, season: 'current', label: 'Current Term' }),
    term({ year: 2026, season: 'Fall' }),
  ])
  assert.deepEqual(ordered.map((t) => t.label), ['Fall 2026', 'Current Term', 'Spring 2027'])
})

test('seasonOrdinal does not resolve inherited object properties', () => {
  // A season literally named "constructor" must not sort as a number.
  assert.equal(seasonOrdinal('constructor'), 99)
  assert.equal(seasonOrdinal('toString'), 99)
})

// ── default term selection ──────────────────────────────────────────────────

test('the dropdown opens on the term the backend named', () => {
  const key = pickDefaultTermKey({
    terms: [SUMMER_2026, FALL_2026, SPRING_2027],
    upcoming_term_key: '2026-Fall',
  })
  assert.equal(key, '2026-Fall')
})

test('falls back to the is_upcoming flag when no key is named', () => {
  const key = pickDefaultTermKey({
    terms: [SUMMER_2026, { ...FALL_2026, is_upcoming: true }],
    upcoming_term_key: null,
  })
  assert.equal(key, '2026-Fall')
})

test('with no future term, falls back to the latest enrolled term', () => {
  const key = pickDefaultTermKey({
    terms: [
      { ...SUMMER_2026, enrolled: true },
      { ...FALL_2026, enrolled: true },
      SPRING_2027,
    ],
    upcoming_term_key: null,
  })
  assert.equal(key, '2026-Fall')
})

test('an unknown upcoming key does not select a term that is not there', () => {
  const key = pickDefaultTermKey({
    terms: [SUMMER_2026, FALL_2026],
    upcoming_term_key: '2099-Fall',
  })
  assert.equal(key, '2026-Fall')
})

test('no terms means no selection', () => {
  assert.equal(pickDefaultTermKey({ terms: [], upcoming_term_key: null }), null)
  assert.equal(pickDefaultTermKey(null), null)
})

// ── term status ─────────────────────────────────────────────────────────────

test('term status is relative to the given day', () => {
  assert.equal(termStatus(FALL_2026, new Date(2026, 7, 11)), 'upcoming')
  assert.equal(termStatus(FALL_2026, new Date(2026, 9, 1)), 'in_progress')
  assert.equal(termStatus(FALL_2026, new Date(2027, 0, 5)), 'past')
})

test('a term boundary day is inside the term, not outside it', () => {
  assert.equal(termStatus(FALL_2026, new Date(2026, 7, 24)), 'in_progress')
  assert.equal(termStatus(FALL_2026, new Date(2026, 11, 10)), 'in_progress')
})

test('a term with no calendar row reports unknown, not an error', () => {
  const seeded = term({ year: 2026, season: 'current', label: 'Current Term' })
  assert.equal(termStatus(seeded, new Date(2026, 7, 11)), 'unknown')
})

// ── date parsing ────────────────────────────────────────────────────────────

test('dates parse in local time, not UTC', () => {
  // new Date('2026-08-24') is UTC midnight, which is Aug 23 locally anywhere
  // west of Greenwich -- a term starting tomorrow would compare as started.
  const parsed = parseDate('2026-08-24')
  assert.equal(parsed.getFullYear(), 2026)
  assert.equal(parsed.getMonth(), 7)
  assert.equal(parsed.getDate(), 24)
})

test('malformed dates return null rather than an Invalid Date', () => {
  assert.equal(parseDate(''), null)
  assert.equal(parseDate(null), null)
  assert.equal(parseDate('not-a-date'), null)
})

test('formatTermDates returns null when the term has no calendar row', () => {
  assert.equal(formatTermDates(term({ year: 2026, season: 'current' })), null)
  assert.match(formatTermDates(FALL_2026), /Aug 24, 2026/)
})

// ── course grouping ─────────────────────────────────────────────────────────

test('planned courses are returned separately from course records', () => {
  const records = [
    { id: 'c1', term_id: 't1', course_code: 'CSCE 121' },
    { id: 'c2', term_id: 't2', course_code: 'MATH 251' },
  ]
  const planned = [
    { id: 'p1', term_id: 't1', course_code: 'CSCE 221' },
    { id: 'p2', term_id: 't2', course_code: 'STAT 211' },
  ]
  const groups = termCourseGroups('t1', records, planned)

  assert.deepEqual(groups.records.map((r) => r.id), ['c1'])
  assert.deepEqual(groups.planned.map((r) => r.id), ['p1'])
})

test('a term with no id groups the rows that also have no term', () => {
  const groups = termCourseGroups(null, [{ id: 'c1', term_id: null }], [{ id: 'p1', term_id: null }])
  assert.equal(groups.records.length, 1)
  assert.equal(groups.planned.length, 1)
})

test('plannedCodes is case-insensitive', () => {
  const codes = plannedCodes([{ course_code: 'csce 121' }])
  assert.ok(codes.has('CSCE 121'))
})

// ── formatting ──────────────────────────────────────────────────────────────

test('credits render singular, plural, and as a range', () => {
  assert.equal(formatCredits(1, 1), '1 credit')
  assert.equal(formatCredits(3, 3), '3 credits')
  assert.equal(formatCredits(1, 4), '1-4 credits')
  assert.equal(formatCredits(null, null), null)
  // 0 is a real credit value in this catalog (variable-credit research and
  // internship courses), so it must not be treated as missing.
  assert.equal(formatCredits(0, 0), '0 credits')
  assert.equal(formatCredits(0, 23), '0-23 credits')
})

// ── urls ────────────────────────────────────────────────────────────────────

test('urls encode their parameters', () => {
  assert.equal(plannedRemoveUrl('a b'), '/api/v2/student/me/planned-courses/a%20b')
  assert.equal(catalogSearchUrl('MATH 251'), '/api/v2/student/me/catalog/search?q=MATH%20251')
  assert.equal(plannedListUrl(null), '/api/v2/student/me/planned-courses')
  assert.equal(plannedListUrl('t1'), '/api/v2/student/me/planned-courses?term_id=t1')
})

test('search does not fire on a single character', () => {
  assert.ok(MIN_SEARCH_LENGTH > 1)
})

// ── payload normalizers ─────────────────────────────────────────────────────

test('normalizers reject non-200 and malformed bodies without throwing', () => {
  for (const [status, body] of [[500, null], [200, null], [401, {}], [200, 'nope']]) {
    assert.equal(normalizeTermsPayload(status, body).ok, status === 200 && body === undefined)
    assert.deepEqual(normalizePlannedPayload(status, body).plannedCourses, [])
    assert.deepEqual(normalizeSearchPayload(status, body).results, [])
  }
})

test('a valid terms payload comes back sorted', () => {
  const result = normalizeTermsPayload(200, {
    terms: [SPRING_2027, SUMMER_2026, FALL_2026],
    upcoming_term_key: '2026-Fall',
  })
  assert.equal(result.ok, true)
  assert.deepEqual(result.terms.map((t) => t.key), ['2026-Summer', '2026-Fall', '2027-Spring'])
  assert.equal(result.upcomingTermKey, '2026-Fall')
})

test('a missing planned_courses array normalizes to empty, not undefined', () => {
  assert.deepEqual(normalizePlannedPayload(200, {}).plannedCourses, [])
  assert.deepEqual(normalizeSearchPayload(200, {}).results, [])
})
