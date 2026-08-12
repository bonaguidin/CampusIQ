export const TERMS_URL = '/api/v2/student/me/terms'
export const PLANNED_COURSES_URL = '/api/v2/student/me/planned-courses'
export const CATALOG_SEARCH_URL = '/api/v2/student/me/catalog/search'

/**
 * Season ordinals, mirroring SEASON_ORDER in
 * GradusIQ_career/transcript/terms.py. Duplicated rather than fetched because
 * it is a sort key, not data: the dropdown must order terms it has already
 * received, and a round trip to learn "May comes before Summer" would be a
 * request to answer a question that is a constant.
 *
 * May and August are SMU intersession terms and sort where SMU's own calendar
 * puts them (May 16-Jun 2, Summer Jun 3-Aug 4, August Aug 6-20, Fall Aug 24).
 * If terms.py's ordering changes, this must change with it -- the backend
 * already sorts the payload, so a drift here shows up as a list that reorders
 * itself, not as a wrong answer.
 */
export const SEASON_ORDER = {
  Winter: 0,
  Spring: 1,
  May: 2,
  Summer: 3,
  August: 4,
  Fall: 5,
}

/** Sorts an unrecognized season last, matching the backend's fallback. */
export const UNKNOWN_SEASON_ORDINAL = 99

export function seasonOrdinal(season) {
  return Object.prototype.hasOwnProperty.call(SEASON_ORDER, season)
    ? SEASON_ORDER[season]
    : UNKNOWN_SEASON_ORDINAL
}

export function plannedRemoveUrl(id) {
  return `${PLANNED_COURSES_URL}/${encodeURIComponent(id)}`
}

export function plannedListUrl(termId) {
  return termId ? `${PLANNED_COURSES_URL}?term_id=${encodeURIComponent(termId)}` : PLANNED_COURSES_URL
}

export function catalogSearchUrl(query) {
  return `${CATALOG_SEARCH_URL}?q=${encodeURIComponent(query)}`
}

/**
 * Minimum characters before a search fires. Below this, a prefix search over
 * 4,623 catalog rows returns a page of near-arbitrary matches -- "C" matches
 * every CSCE, CHEM and COMM course -- which reads as noise rather than as
 * results, and spends a request per keystroke to produce it.
 */
export const MIN_SEARCH_LENGTH = 2

/** Debounce for search-as-you-type. One request per pause, not per keystroke. */
export const SEARCH_DEBOUNCE_MS = 250

export function sortTerms(terms) {
  return [...terms].sort((a, b) => {
    if (a.year !== b.year) return a.year - b.year
    const seasonDelta = seasonOrdinal(a.season) - seasonOrdinal(b.season)
    if (seasonDelta !== 0) return seasonDelta
    return String(a.label).localeCompare(String(b.label))
  })
}

/**
 * The term the dropdown should open on.
 *
 * Prefers the backend's own answer (`upcoming_term_key`), which is computed
 * against the server's date. The client-side fallback exists for the case
 * where every term predates today and the backend returned null -- then the
 * most recent term is a better landing place than an empty selection.
 *
 * "Upcoming" is the next term that has NOT started, not the one containing
 * today: mid-semester, a student planning courses is planning the next term,
 * and opening on the current one would put the search box on a term whose
 * registration has closed. term_view.py carries the same reasoning.
 */
export function pickDefaultTermKey(payload) {
  const terms = Array.isArray(payload?.terms) ? payload.terms : []
  if (terms.length === 0) return null

  if (payload?.upcoming_term_key) {
    const named = terms.find((term) => term.key === payload.upcoming_term_key)
    if (named) return named.key
  }

  const sorted = sortTerms(terms)
  const flagged = sorted.find((term) => term.is_upcoming)
  if (flagged) return flagged.key

  // No future term has dates. Fall back to the latest term the student
  // actually has coursework in, then to the latest term of any kind.
  const enrolled = sorted.filter((term) => term.enrolled)
  const pool = enrolled.length > 0 ? enrolled : sorted
  return pool[pool.length - 1].key
}

/**
 * Term status relative to `today`, for the badge beside the dropdown label.
 * 'unknown' covers a term with no calendar row -- the five seeded
 * 'Current Term' rows, and terms predating the seeded window. It is not an
 * error state and must not read as one.
 */
export function termStatus(term, today) {
  const start = parseDate(term?.start_date)
  const end = parseDate(term?.end_date)
  if (!start || !end) return 'unknown'
  const day = startOfDay(today)
  if (day < start) return 'upcoming'
  if (day > end) return 'past'
  return 'in_progress'
}

export const TERM_STATUS_LABELS = {
  upcoming: 'Upcoming',
  in_progress: 'In progress',
  past: 'Completed',
  unknown: '',
}

function startOfDay(value) {
  const date = value instanceof Date ? value : new Date(value)
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

/**
 * 'YYYY-MM-DD' -> Date in LOCAL time.
 *
 * new Date('2026-08-24') parses as UTC midnight, which in any timezone west of
 * Greenwich is the evening of the 23rd locally -- so a term starting tomorrow
 * can compare as having started today. Splitting the parts and using the
 * numeric Date constructor keeps the comparison in the same calendar the
 * student is reading.
 */
export function parseDate(value) {
  if (!value || typeof value !== 'string') return null
  const parts = value.slice(0, 10).split('-')
  if (parts.length !== 3) return null
  const [year, month, day] = parts.map(Number)
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null
  const date = new Date(year, month - 1, day)
  return Number.isNaN(date.getTime()) ? null : date
}

const DATE_FORMAT = { month: 'short', day: 'numeric', year: 'numeric' }

/** "Aug 24, 2026 – Dec 10, 2026", or null when the term has no calendar row. */
export function formatTermDates(term) {
  const start = parseDate(term?.start_date)
  const end = parseDate(term?.end_date)
  if (!start || !end) return null
  const fmt = (date) => date.toLocaleDateString('en-US', DATE_FORMAT)
  return `${fmt(start)} – ${fmt(end)}`
}

/**
 * Course rows for one term, tagged by origin.
 *
 * Planned courses are NOT merged into the completed/in-progress list. They come
 * from a different table, they mean something different, and nothing about a
 * planned row has been verified against a transcript. Returning two arrays
 * rather than one flagged array makes it awkward for a caller to render them
 * identically by accident.
 */
export function termCourseGroups(termId, courseRecords, plannedCourses) {
  const records = (Array.isArray(courseRecords) ? courseRecords : []).filter(
    (row) => (row.term_id ?? null) === (termId ?? null),
  )
  const planned = (Array.isArray(plannedCourses) ? plannedCourses : []).filter(
    (row) => (row.term_id ?? null) === (termId ?? null),
  )
  return { records, planned }
}

/**
 * Course codes already planned in a term, for disabling the add control.
 *
 * A UI affordance only: planned_courses carries no unique constraint, and the
 * backend accepts a duplicate add. Nothing downstream depends on this holding,
 * which is why it is a Set built at render time rather than a guard.
 */
export function plannedCodes(plannedCourses) {
  return new Set(
    (Array.isArray(plannedCourses) ? plannedCourses : []).map((row) =>
      String(row.course_code ?? '').toUpperCase(),
    ),
  )
}

/**
 * "3 credits" / "1 credit" / "1-4 credits" for a variable-credit course, or
 * null when the course carries no credit data at all.
 *
 * The null check is explicit rather than leaning on Number(): Number(null) is
 * 0, not NaN, so a missing value would otherwise render as "0 credits" -- and
 * 0 is a real value here (105 catalog rows have credit_min = 0, the lower
 * bound on variable-credit research and internship courses), so it must stay
 * distinguishable from absent.
 */
export function formatCredits(min, max) {
  if (min === null || min === undefined) return null
  const low = Number(min)
  if (!Number.isFinite(low)) return null
  const high = max === null || max === undefined ? low : Number(max)
  if (Number.isFinite(high) && high !== low) return `${low}-${high} credits`
  return low === 1 ? '1 credit' : `${low} credits`
}

export function normalizeTermsPayload(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return { ok: false, terms: [], upcomingTermKey: null }
  }
  const terms = Array.isArray(body.terms) ? body.terms : []
  return {
    ok: true,
    terms: sortTerms(terms),
    upcomingTermKey: body.upcoming_term_key ?? null,
  }
}

export function normalizePlannedPayload(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return { ok: false, plannedCourses: [] }
  }
  return {
    ok: true,
    plannedCourses: Array.isArray(body.planned_courses) ? body.planned_courses : [],
  }
}

export function normalizeSearchPayload(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return { ok: false, results: [] }
  }
  return { ok: true, results: Array.isArray(body.results) ? body.results : [] }
}
