import { termStatus } from './termPlanning.mjs'
import { formatCredits } from './degreeSchedulePresentation.mjs'

/**
 * Seasons this view renders as columns. A student's real term list (and,
 * less often, course_records) can include intersession terms (Winter, May,
 * Summer, August -- see SEASON_ORDER in termPlanning.mjs), but the approved
 * two-column mockup is Fall | Spring only. Intersession terms are out of
 * scope for this view, not silently lost -- they still render in
 * TermPlanner, which is term-by-term rather than year-by-year.
 */
export const YEAR_SEMESTER_SEASONS = ['Fall', 'Spring']

const ORDINAL_WORDS = ['First', 'Second', 'Third', 'Fourth', 'Fifth', 'Sixth']

/**
 * Ordinal label for the Nth academic year (0-indexed), e.g. 0 -> 'First
 * year'. Falls back to 'Year N' past the words list rather than assuming
 * every student graduates in four years -- a fifth-year or transfer
 * student's schedule can run longer.
 */
export function academicYearLabel(index) {
  const word = ORDINAL_WORDS[index]
  return word ? `${word} year` : `Year ${index + 1}`
}

/**
 * The academic-year bucket a Fall/Spring term belongs to, keyed by the
 * Fall term's calendar year (US convention: Fall Y pairs with Spring Y+1).
 * Any other season is out of scope here -- see YEAR_SEMESTER_SEASONS.
 */
export function academicYearKey(year, season) {
  if (season === 'Fall') return year
  if (season === 'Spring') return year - 1
  return null
}

/**
 * Formats a letter grade with its GPA points, e.g. "B+ (3.3)". Falls back
 * to the bare letter when the institution's grade map has no points for it
 * (an unmapped or non-GPA letter like "P" or "W" still needs to display).
 */
export function formatGradeBadge(letterGrade, gradingSchema) {
  if (!letterGrade) return null
  const grades = Array.isArray(gradingSchema?.grades) ? gradingSchema.grades : []
  const row = grades.find((grade) => grade.letter === letterGrade)
  if (row && typeof row.points === 'number') {
    return `${letterGrade} (${row.points.toFixed(1)})`
  }
  return letterGrade
}

/**
 * One semester slot's state, collapsed from TermPlanner's vocabulary
 * (termStatus in termPlanning.mjs) to the three this view renders
 * differently: 'past' and 'in_progress' show real coursework from
 * course_records; everything else -- 'upcoming', 'unknown', or no calendar
 * row at all (a term this far out has no academic_terms row yet) --
 * collapses to 'future', which shows the empty-state + suggestions.
 */
export function semesterState(realTerm, today) {
  if (!realTerm) return 'future'
  const status = termStatus(realTerm, today)
  if (status === 'past') return 'past'
  if (status === 'in_progress') return 'in_progress'
  return 'future'
}

function sumCredits(courses) {
  return courses.reduce((total, course) => total + (Number(course.credit_hours) || 0), 0)
}

/**
 * Builds the year-tabbed, two-column data this view renders, merging four
 * sources that otherwise never meet:
 *  - realTerms (GET /terms): calendar terms, used for status + real dates
 *  - courseRecords (GET /course-records, passed down from the dashboard's
 *    own profile fetch): past/in-progress coursework with grades
 *  - scheduleTerms (GET /schedule's terms[]): the scheduler's forward plan,
 *    used both as the future column's "confirmed" list (there is none --
 *    nothing is confirmed until enrollment) and, per product decision, as
 *    the "Suggested courses" section, since it is the only real
 *    recommendation data currently exposed by any endpoint.
 *  - plannedCourses (GET /planned-courses): courses the student added to a
 *    future term themselves. Rendered only in the 'future' branch, in their
 *    own `planned` array with the "Added" treatment. A planned code also
 *    present in the scheduler's plan for that term is shown once, here --
 *    the suggestion is dropped (see below), matching the plannedCodes
 *    (case-insensitive) convention.
 *
 * plannedCourses defaults to [] so callers that predate it (and tests) keep
 * working unchanged.
 */
export function buildDegreeScheduleYears({ realTerms, scheduleTerms, courseRecords, gradingSchema, today, plannedCourses }) {
  const terms = Array.isArray(realTerms) ? realTerms : []
  const schedule = Array.isArray(scheduleTerms) ? scheduleTerms : []
  const records = Array.isArray(courseRecords) ? courseRecords : []
  const planned = Array.isArray(plannedCourses) ? plannedCourses : []

  const termsByKey = new Map(terms.map((term) => [term.key, term]))
  const scheduleByKey = new Map(schedule.map((term) => [term.term_key, term]))

  const yearKeys = new Set()
  for (const term of terms) {
    if (!YEAR_SEMESTER_SEASONS.includes(term.season)) continue
    const yearKey = academicYearKey(term.year, term.season)
    if (yearKey !== null) yearKeys.add(yearKey)
  }
  for (const termKey of scheduleByKey.keys()) {
    const match = /^(\d{4})-(Fall|Spring)$/.exec(termKey)
    if (!match) continue
    yearKeys.add(academicYearKey(Number(match[1]), match[2]))
  }

  const sortedYearKeys = [...yearKeys].sort((a, b) => a - b)

  return sortedYearKeys.map((yearKey, index) => ({
    yearKey,
    label: academicYearLabel(index),
    semesters: YEAR_SEMESTER_SEASONS.map((season) => {
      const calendarYear = season === 'Fall' ? yearKey : yearKey + 1
      const termKey = `${calendarYear}-${season}`
      const realTerm = termsByKey.get(termKey) ?? null
      const state = semesterState(realTerm, today)

      if (state === 'past' || state === 'in_progress') {
        // realTerm.id can still be null for a term with calendar dates the
        // student has never enrolled in (no academic_terms row materialized
        // yet) -- that has no course_records to match, by construction, so
        // it must not fall through to matching other records' null term_id.
        const semesterCourses = realTerm.id === null
          ? []
          : records
              .filter((record) => record.term_id === realTerm.id)
              .filter((record) => record.status !== 'dropped')
        return {
          season,
          termKey,
          state,
          totalCreditsLabel: formatCredits(sumCredits(semesterCourses)),
          courses: semesterCourses.map((record) => ({
            course_code: record.course_code,
            title: record.title ?? null,
            credit_hours: record.credit_hours,
            gradeBadge: state === 'past' ? formatGradeBadge(record.letter_grade, gradingSchema) : null,
          })),
          suggestedCourses: [],
          planned: [],
        }
      }

      const scheduled = scheduleByKey.get(termKey) ?? null

      // A planned row always carries a real term_id (ensure_term_row makes one
      // on add); a term with no materialized id therefore has none, by
      // construction -- same guard the past/in_progress branch applies to
      // course_records.
      const plannedForTerm = realTerm?.id == null
        ? []
        : planned
            .filter((row) => row.term_id === realTerm.id)
            .map((row) => ({
              id: row.id,
              course_code: row.course_code,
              title: row.title ?? null,
              credit_hours: row.credit_hours,
            }))

      // Reconcile against the scheduler's plan: a course the student already
      // added is shown once, under the added treatment -- drop the matching
      // suggestion. Case-insensitive, matching plannedCodes (termPlanning.mjs).
      const plannedCodeSet = new Set(
        plannedForTerm.map((row) => String(row.course_code ?? '').toUpperCase()),
      )

      return {
        season,
        termKey,
        state,
        totalCreditsLabel: 'Not scheduled',
        courses: [],
        suggestedCourses: (scheduled?.courses ?? [])
          .filter((course) => !plannedCodeSet.has(String(course.course_code ?? '').toUpperCase()))
          .map((course) => ({
            course_code: course.course_code,
            credit_hours: course.credit_hours,
          })),
        planned: plannedForTerm,
      }
    }),
  }))
}
