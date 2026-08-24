/**
 * "What is the student taking right now" -- shared by Academic Overview's
 * existing "Current coursework" section and Overview's current-term card.
 *
 * Not a single-term pick: a student can have course_records in more than one
 * term simultaneously marked in_progress (e.g. a summer term overlapping a
 * fall add/drop window), so this takes the union of every in_progress course
 * regardless of term, and joins every distinct term's label with ", " --
 * exactly Academic Overview's pre-existing behavior (AuthenticatedDashboard.tsx),
 * reused here rather than reinvented as a single-term selection.
 */
export function currentTermSnapshot({ courses, terms }) {
  const inProgress = (Array.isArray(courses) ? courses : []).filter((course) => course.status === 'in_progress')
  if (inProgress.length === 0) return null

  const termIds = new Set(inProgress.map((course) => course.term_id).filter(Boolean))
  const termLabel = (Array.isArray(terms) ? terms : [])
    .filter((term) => termIds.has(term.id))
    .map((term) => term.label)
    .join(', ') || null

  const totalCredits = inProgress.reduce((sum, course) => sum + (Number(course.credit_hours) || 0), 0)

  return { termLabel, courses: inProgress, totalCredits }
}
