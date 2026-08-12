/**
 * Stub handlers for the three term-planning routes the Academic Record tab
 * calls on render.
 *
 * Shared between authenticatedDashboard and transcriptFlow because both drive
 * the real AuthenticatedDashboard, and since the term view replaced the flat
 * course list, neither can reach a course row without these answering. Kept as
 * a fixture rather than copied into both files so the payload shape is stated
 * once -- it mirrors the FastAPI routes in GradusIQ_career/api.py, and a drift
 * between them should be one edit, not two.
 *
 * Terms default to the same shape the TAMU seed produces, with a `today`
 * caller-controlled so "upcoming" is deterministic rather than dependent on
 * when the suite runs.
 */

export const DEFAULT_TERMS = [
  {
    key: '2025-Fall',
    id: 'term-1',
    label: 'Fall 2025',
    year: 2025,
    season: 'Fall',
    sequence: 1,
    start_date: null,
    end_date: null,
    enrolled: true,
    is_upcoming: false,
  },
  {
    key: '2026-Fall',
    id: null,
    label: 'Fall 2026',
    year: 2026,
    season: 'Fall',
    sequence: null,
    start_date: '2026-08-24',
    end_date: '2026-12-10',
    enrolled: false,
    is_upcoming: true,
  },
]

export const DEFAULT_CATALOG = [
  {
    id: 'catalog-1',
    code: 'CSCE 221',
    title: 'Data Structures and Algorithms',
    department: 'Computer Science',
    course_level: 200,
    credit_min: 4,
    credit_max: 4,
  },
  {
    id: 'catalog-2',
    code: 'CSCE 222',
    title: 'Discrete Structures',
    department: 'Computer Science',
    course_level: 200,
    credit_min: 3,
    credit_max: 3,
  },
]

/**
 * Returns a handler(path, method, request, response) -> boolean. True means it
 * answered; false means the caller's own middleware should carry on.
 *
 * `state.planned` is mutated by add/remove so a test can drive the whole
 * add-then-see-it-listed loop without stubbing each step separately.
 */
export function planningRoutes({
  terms = DEFAULT_TERMS,
  catalog = DEFAULT_CATALOG,
  upcomingTermKey = '2026-Fall',
  state = { planned: [] },
} = {}) {
  let nextId = 1
  // Terms are mutable here for one reason, and it is the behaviour that
  // matters most in this flow: planning a course for a term the student has
  // never enrolled in CREATES that term's academic_terms row, so the term
  // gains an id it did not have a moment ago. The component refetches terms
  // after adding to a term whose id was null, and a static fixture would leave
  // the new planned row filed under an id no term in the list carries -- which
  // renders as nothing at all. See ensure_term_row in planning/planned.py.
  let termsState = terms.map((term) => ({ ...term }))

  function respond(response, body, status = 200) {
    response.statusCode = status
    response.setHeader('content-type', 'application/json')
    response.end(JSON.stringify(body))
  }

  function resolveTermId(year, season) {
    const match = termsState.find((term) => term.year === year && term.season === season)
    if (!match) return null
    if (match.id === null) {
      match.id = `term-created-${String(nextId++)}`
      match.enrolled = true
    }
    return match.id
  }

  return {
    state,
    get terms() {
      return termsState
    },
    handle(path, method, request, response) {
      if (path === '/api/v2/student/me/terms' && method === 'GET') {
        respond(response, { terms: termsState, upcoming_term_key: upcomingTermKey })
        return true
      }

      if (path === '/api/v2/student/me/planned-courses' && method === 'GET') {
        respond(response, { planned_courses: state.planned })
        return true
      }

      if (path === '/api/v2/student/me/planned-courses' && method === 'POST') {
        let body = ''
        request.on('data', (chunk) => { body += chunk })
        request.on('end', () => {
          const parsed = JSON.parse(body || '{}')
          const row = {
            id: `planned-${String(nextId++)}`,
            // The real route resolves (year, season) to a term row, creating
            // it when the student has never enrolled in that term.
            term_id: resolveTermId(parsed.year, parsed.season),
            course_code: parsed.course_code,
            title: parsed.title ?? null,
            credit_hours: parsed.credit_hours ?? null,
            catalog_course_id: parsed.catalog_course_id ?? null,
            created_at: new Date().toISOString(),
            kind: 'planned',
          }
          state.planned.push(row)
          respond(response, { planned_course: row })
        })
        return true
      }

      if (path.startsWith('/api/v2/student/me/planned-courses/') && method === 'DELETE') {
        const id = path.split('/').pop()
        state.planned = state.planned.filter((row) => row.id !== id)
        respond(response, { removed: id })
        return true
      }

      if (path === '/api/v2/student/me/catalog/search' && method === 'GET') {
        respond(response, { results: catalog, query: '' })
        return true
      }

      return false
    },
  }
}
