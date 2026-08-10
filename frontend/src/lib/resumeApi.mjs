// Normalizes the four resume-flow backend endpoints into one internal shape.
//
// WHY THIS EXISTS: the four endpoints disagree with each other in four
// documented ways, and every one of them would otherwise be re-derived inside
// a .tsx component where it cannot be tested (node --test cannot load .tsx --
// see the Stage 3 audit). Written as a plain .mjs with a .d.mts companion,
// mirroring lib/signupRules.mjs, so the logic is covered by the existing
// runner.
//
// The four disagreements:
//
//   1. Upload returns FOUR status values with DIFFERENT key sets. `ok` carries
//      career_profile + written; not_a_resume/unparseable carry written: null
//      and no career_profile key at all; parse_failed carries `errors` but
//      neither `model` nor `warnings`. Components must not have to remember
//      which keys exist on which branch.
//
//   2. `detail` is an OBJECT for 415/422 on upload
//      ({error, extraction_status, message}) and a plain STRING for every
//      other error on every endpoint. Rendering it directly would print
//      "[object Object]" on exactly the two cases a student is most likely to
//      hit (wrong file type, scanned PDF).
//
//   3. Confirm takes `career_profile` (singular) in the request body but
//      reports `career_profiles` (plural, the table name) in the response
//      counts. Normalized to the singular request-side vocabulary throughout.
//
//   4. PATCH returns 409 for two unrelated situations -- already-confirmed and
//      natural-key collision -- distinguishable only by the message text.

export const UPLOAD_URL = '/api/v2/student/me/resume/upload'
export const REVIEW_URL = '/api/v2/student/me/career/review'
export const CONFIRM_URL = '/api/v2/student/me/career/confirm'

/** URL segments, which are also the PATCH path's {table} values. */
export const CHILD_TABLES = ['certifications', 'work_experience', 'projects']
export const ALL_SECTIONS = ['career_profile', ...CHILD_TABLES]

export function reviewEditUrl(table, id) {
  return `${REVIEW_URL}/${encodeURIComponent(table)}/${encodeURIComponent(id)}`
}

// Field metadata, mirroring the backend's EDITABLE_FIELDS exactly (see
// GradusIQ_career/resume/review.py). Nothing outside these lists is editable,
// and the backend silently strips anything else -- so sending more would fail
// quietly rather than loudly. Kept here as data so the review screen renders
// from one source and the set stays assertable in tests.
export const REVIEW_SECTIONS = {
  career_profile: {
    label: 'Career profile',
    singular: 'career profile',
    fields: [
      { name: 'target_roles', label: 'Target roles', type: 'list' },
      { name: 'interests', label: 'Interests', type: 'list' },
      { name: 'career_goals', label: 'Career goals', type: 'textarea' },
      { name: 'geographic_preference', label: 'Location preference', type: 'text' },
      { name: 'ai_anxiety_level', label: 'AI anxiety level', type: 'text' },
      { name: 'skills_technical', label: 'Technical skills', type: 'list' },
      { name: 'skills_soft', label: 'Soft skills', type: 'list' },
      { name: 'ai_exposure', label: 'AI exposure', type: 'text' },
    ],
  },
  certifications: {
    label: 'Certifications',
    singular: 'certification',
    titleField: 'name',
    fields: [
      { name: 'name', label: 'Name', type: 'text' },
      { name: 'issuer', label: 'Issuer', type: 'text' },
      { name: 'status', label: 'Status', type: 'status' },
      { name: 'date', label: 'Date', type: 'text' },
    ],
  },
  work_experience: {
    label: 'Work experience',
    singular: 'role',
    titleField: 'employer',
    fields: [
      { name: 'employer', label: 'Employer', type: 'text' },
      { name: 'role', label: 'Role', type: 'text' },
      { name: 'duration', label: 'Duration', type: 'text' },
      { name: 'location', label: 'Location', type: 'text' },
      { name: 'description', label: 'Description', type: 'textarea' },
      { name: 'skills_gained', label: 'Skills gained', type: 'list' },
    ],
  },
  projects: {
    label: 'Projects',
    singular: 'project',
    titleField: 'name',
    fields: [
      { name: 'name', label: 'Name', type: 'text' },
      { name: 'timeframe', label: 'Timeframe', type: 'text' },
      { name: 'description', label: 'Description', type: 'textarea' },
      { name: 'tools', label: 'Tools', type: 'list' },
    ],
  },
}

/** The only values certifications.status may take (a live CHECK constraint). */
export const CERT_STATUS_VALUES = ['completed', 'in_progress']

export function editableFieldNames(table) {
  const section = REVIEW_SECTIONS[table]
  return section ? section.fields.map((f) => f.name) : []
}

// ── error detail ────────────────────────────────────────────────────────────

/**
 * Read a human-readable message out of a `detail` that may be a string, an
 * object ({error, extraction_status, message}), or absent.
 *
 * Disagreement #2. FastAPI wraps HTTPException detail as-is, so the shape
 * depends entirely on which raise site fired.
 */
export function detailToText(detail, fallback = 'Something went wrong.') {
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (detail && typeof detail === 'object') {
    const { message } = detail
    if (typeof message === 'string' && message.trim()) return message.trim()
  }
  return fallback
}

/** The extraction_status carried on 415/422 upload errors, else null. */
export function detailExtractionStatus(detail) {
  if (detail && typeof detail === 'object' && typeof detail.extraction_status === 'string') {
    return detail.extraction_status
  }
  return null
}

function bodyDetail(body) {
  return body && typeof body === 'object' ? body.detail : undefined
}

/**
 * Error kinds shared by every endpoint. Returns null when the status is not
 * one of the shared cases, letting each endpoint add its own.
 */
function sharedHttpFailure(httpStatus, body) {
  const detail = bodyDetail(body)
  const text = (t) => detailToText(detail, t)

  switch (httpStatus) {
    case 401:
      return {
        ok: false,
        kind: 'unauthenticated',
        message: 'Your session has expired. Sign in again.',
      }
    case 403:
      return { ok: false, kind: 'forbidden', message: text('You do not have access to this.') }
    case 429:
      // Two unrelated 429s share this status: the shared request rate limit,
      // and the AI concurrency gate. The remedy differs (wait vs retry now),
      // so they are separate kinds.
      if (typeof detail === 'string' && detail.toLowerCase().includes('busy')) {
        return {
          ok: false,
          kind: 'ai_busy',
          message: 'The analysis service is busy right now. Try again in a moment.',
        }
      }
      return {
        ok: false,
        kind: 'rate_limited',
        message: 'Too many requests. Wait a minute and try again.',
      }
    case 502:
      return { ok: false, kind: 'backend_unavailable', message: text('The server is unavailable.') }
    case 503:
      return { ok: false, kind: 'not_configured', message: text('The server is not configured.') }
    default:
      return null
  }
}

// ── upload ──────────────────────────────────────────────────────────────────

export const EMPTY_WRITTEN = Object.freeze({
  certifications: { inserted: 0, skipped_duplicate: 0 },
  work_experience: { inserted: 0, skipped_duplicate: 0 },
  projects: { inserted: 0, skipped_duplicate: 0 },
})

/**
 * Always an object with all three tables, whatever `written` was.
 *
 * Disagreement #1: `written` is null on not_a_resume/unparseable/parse_failed
 * and populated only on ok. Callers should read counts, not check for null.
 */
export function normalizeWritten(written) {
  const result = {}
  for (const table of CHILD_TABLES) {
    const entry = written && typeof written === 'object' ? written[table] : null
    const inserted = entry && Number.isFinite(entry.inserted) ? entry.inserted : 0
    const skipped =
      entry && Number.isFinite(entry.skipped_duplicate) ? entry.skipped_duplicate : 0
    result[table] = { inserted, skipped_duplicate: skipped }
  }
  return result
}

export function writtenTotals(written) {
  const normalized = normalizeWritten(written)
  let inserted = 0
  let skipped = 0
  for (const table of CHILD_TABLES) {
    inserted += normalized[table].inserted
    skipped += normalized[table].skipped_duplicate
  }
  return { inserted, skipped_duplicate: skipped, total: inserted + skipped }
}

const UPLOAD_STATUS_MESSAGES = {
  not_a_resume:
    "That file does not look like a resume. Upload the document you send to employers, " +
    'not a cover letter, transcript, or syllabus.',
  unparseable:
    'The text in that file was too garbled to read reliably. If it is a scan, try exporting ' +
    'a text-based PDF from the original document.',
  parse_failed:
    'We read your file but could not turn it into profile data. This is usually temporary — ' +
    'try uploading again.',
}

/**
 * Normalize any upload response into one shape.
 *
 * Always returns: { ok, kind, message, extraction, warnings, model, written,
 * totals, careerProfile, errors, httpStatus }. Keys absent from a given
 * backend branch are filled with safe defaults, never left undefined.
 */
export function normalizeUploadResponse(httpStatus, body) {
  const base = {
    httpStatus,
    extraction: null,
    warnings: [],
    model: null,
    written: normalizeWritten(null),
    totals: writtenTotals(null),
    careerProfile: null,
    errors: [],
  }

  if (httpStatus === 200 && body && typeof body === 'object') {
    const extraction = body.extraction ?? null
    const warnings = Array.isArray(body.warnings) ? body.warnings : []
    const model = typeof body.model === 'string' ? body.model : null

    if (body.status === 'ok') {
      return {
        ...base,
        ok: true,
        kind: 'ok',
        message: 'Resume read successfully.',
        extraction,
        warnings,
        model,
        written: normalizeWritten(body.written),
        totals: writtenTotals(body.written),
        careerProfile: body.career_profile ?? null,
      }
    }

    if (body.status === 'not_a_resume' || body.status === 'unparseable') {
      return {
        ...base,
        ok: false,
        kind: body.status,
        message: UPLOAD_STATUS_MESSAGES[body.status],
        extraction,
        warnings,
        model,
      }
    }

    if (body.status === 'parse_failed') {
      return {
        ...base,
        ok: false,
        kind: 'parse_failed',
        message: UPLOAD_STATUS_MESSAGES.parse_failed,
        extraction,
        // parse_failed carries neither model nor warnings, but does carry errors.
        errors: Array.isArray(body.errors) ? body.errors : [],
      }
    }

    return { ...base, ok: false, kind: 'unknown', message: 'Unexpected response from the server.' }
  }

  const detail = bodyDetail(body)

  if (httpStatus === 413) {
    return {
      ...base,
      ok: false,
      kind: 'file_too_large',
      message: detailToText(detail, 'That file is too large.'),
    }
  }

  // 415 and 422 both carry the detail OBJECT. extraction_status distinguishes
  // an unsupported type from a readable file with no text in it.
  if (httpStatus === 415 || httpStatus === 422) {
    const extractionStatus = detailExtractionStatus(detail)
    const fallback =
      extractionStatus === 'empty'
        ? 'No readable text was found in that file.'
        : 'That file type is not supported. Upload a PDF or a .docx Word document.'
    return {
      ...base,
      ok: false,
      kind: extractionStatus ?? (httpStatus === 415 ? 'unsupported_format' : 'invalid'),
      message: detailToText(detail, fallback),
      extraction: extractionStatus ? { status: extractionStatus, page_count: null } : null,
    }
  }

  if (httpStatus === 400) {
    return {
      ...base,
      ok: false,
      kind: 'bad_upload',
      message: detailToText(detail, 'That file could not be read.'),
    }
  }

  if (httpStatus === 404) {
    return {
      ...base,
      ok: false,
      kind: 'no_student_profile',
      message: 'No student profile is set up for this account yet.',
    }
  }

  const shared = sharedHttpFailure(httpStatus, body)
  if (shared) return { ...base, ...shared }

  return {
    ...base,
    ok: false,
    kind: 'unknown',
    message: detailToText(detail, `Upload failed (status ${String(httpStatus)}).`),
  }
}

// ── review GET ──────────────────────────────────────────────────────────────

export const EMPTY_REVIEW = Object.freeze({
  career_profile: null,
  certifications: [],
  work_experience: [],
  projects: [],
})

export function normalizeReviewResponse(httpStatus, body) {
  if (httpStatus === 200 && body && typeof body === 'object') {
    const sections = {
      career_profile:
        body.career_profile && typeof body.career_profile === 'object'
          ? body.career_profile
          : null,
    }
    for (const table of CHILD_TABLES) {
      sections[table] = Array.isArray(body[table]) ? body[table] : []
    }
    return { ok: true, kind: 'ok', message: '', httpStatus, sections, pendingCount: countPending(sections) }
  }

  const shared = sharedHttpFailure(httpStatus, body) ?? {
    ok: false,
    kind: httpStatus === 404 ? 'no_student_profile' : 'unknown',
    message:
      httpStatus === 404
        ? 'No student profile is set up for this account yet.'
        : detailToText(bodyDetail(body), `Could not load your records (status ${String(httpStatus)}).`),
  }
  return { ...shared, httpStatus, sections: { ...EMPTY_REVIEW }, pendingCount: 0 }
}

export function countPending(sections) {
  if (!sections) return 0
  let count = sections.career_profile ? 1 : 0
  for (const table of CHILD_TABLES) {
    count += Array.isArray(sections[table]) ? sections[table].length : 0
  }
  return count
}

// ── review PATCH ────────────────────────────────────────────────────────────

/** Distinguishes the two unrelated 409s. See disagreement #4. */
const ALREADY_CONFIRMED_MARKER = 'already been confirmed'

export function normalizePatchResponse(httpStatus, body) {
  if (httpStatus === 200 && body && typeof body === 'object') {
    return { ok: true, kind: 'ok', message: '', httpStatus, row: body }
  }

  const detail = bodyDetail(body)
  const text = detailToText(detail, '')

  if (httpStatus === 404) {
    return {
      ok: false,
      kind: 'not_found',
      // Deliberately not "belongs to someone else": the backend collapses
      // absent and cross-student into one 404 precisely so the client cannot
      // tell, and the UI must not invent the distinction back.
      message: 'That entry is no longer available. It has been removed from this list.',
      httpStatus,
      row: null,
    }
  }

  if (httpStatus === 409) {
    const confirmed = text.toLowerCase().includes(ALREADY_CONFIRMED_MARKER)
    return {
      ok: false,
      kind: confirmed ? 'already_confirmed' : 'conflict',
      message: confirmed
        ? 'This entry was already confirmed and can no longer be edited.'
        : text || 'That value collides with another entry.',
      httpStatus,
      row: null,
    }
  }

  if (httpStatus === 422) {
    return {
      ok: false,
      kind: 'invalid',
      message: text || 'That value is not valid.',
      httpStatus,
      row: null,
    }
  }

  const shared = sharedHttpFailure(httpStatus, body) ?? {
    ok: false,
    kind: 'unknown',
    message: text || `Could not save that change (status ${String(httpStatus)}).`,
  }
  return { ...shared, httpStatus, row: null }
}

// ── confirm ─────────────────────────────────────────────────────────────────

/**
 * Response counts, rekeyed to the singular request-side vocabulary.
 *
 * Disagreement #3: the request body field is `career_profile`, the response
 * count key is `career_profiles`. One vocabulary internally.
 */
export function confirmedToSingular(confirmed) {
  const source = confirmed && typeof confirmed === 'object' ? confirmed : {}
  const counted = (value) => (Number.isFinite(value) ? value : 0)
  return {
    career_profile: counted(source.career_profiles),
    certifications: counted(source.certifications),
    work_experience: counted(source.work_experience),
    projects: counted(source.projects),
  }
}

export function normalizeConfirmResponse(httpStatus, body) {
  if (httpStatus === 200 && body && typeof body === 'object') {
    const confirmed = confirmedToSingular(body.confirmed)
    const reported = Number.isFinite(body.total_confirmed) ? body.total_confirmed : null
    const summed = ALL_SECTIONS.reduce((total, key) => total + confirmed[key], 0)
    return {
      ok: true,
      kind: 'ok',
      message: '',
      httpStatus,
      scope: typeof body.scope === 'string' ? body.scope : 'all_unconfirmed',
      confirmed,
      totalConfirmed: reported ?? summed,
    }
  }

  const shared = sharedHttpFailure(httpStatus, body) ?? {
    ok: false,
    kind: httpStatus === 404 ? 'no_student_profile' : 'unknown',
    message: detailToText(
      bodyDetail(body),
      `Could not confirm your records (status ${String(httpStatus)}).`,
    ),
  }
  return {
    ...shared,
    httpStatus,
    scope: null,
    confirmed: confirmedToSingular(null),
    totalConfirmed: 0,
  }
}

// ── edit diffing ────────────────────────────────────────────────────────────

function sameValue(a, b) {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, index) => item === b[index])
  }
  return a === b
}

/**
 * Only the fields that actually changed, restricted to this table's editable
 * set. PATCH is supposed to carry the changed field(s) and nothing else; the
 * backend would strip the rest silently, so sending them would hide mistakes
 * rather than surface them.
 */
export function changedFields(table, original, draft) {
  const allowed = editableFieldNames(table)
  const changes = {}
  for (const name of allowed) {
    const before = original ? original[name] : undefined
    const after = draft ? draft[name] : undefined
    if (!sameValue(normalizeFieldValue(before), normalizeFieldValue(after))) {
      changes[name] = normalizeFieldValue(after)
    }
  }
  return changes
}

/** Blank text becomes null, matching how the backend stores "not stated". */
export function normalizeFieldValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean)
  }
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed === '' ? null : trimmed
  }
  return value ?? null
}

export function parseListInput(text) {
  if (typeof text !== 'string') return []
  return text
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

export function formatListInput(value) {
  return Array.isArray(value) ? value.join(', ') : ''
}

// ── review-screen model ─────────────────────────────────────────────────────
//
// The redesigned review screen renders from three derived facts: whether a
// field is filled, whether the student changed it, and how many of each exist
// across the whole page. All three live here rather than in CareerReview.tsx
// for the reason this module exists at all -- `node --test` cannot load .tsx,
// so logic placed in the component is logic that cannot be tested. The
// component keeps only rendering and DOM effects.

/** A field the student has not filled in: null, blank, or an empty list. */
export function isEmptyValue(value) {
  const normalized = normalizeFieldValue(value)
  if (normalized === null || normalized === undefined) return true
  if (Array.isArray(normalized)) return normalized.length === 0
  if (typeof normalized === 'string') return normalized.trim() === ''
  return false
}

/** Glyphs shown in each field row's left gutter. */
export const GLYPH_READ = '·'    // · straight from the resume
export const GLYPH_EDITED = '✎'  // ✎ changed by the student
export const GLYPH_EMPTY = '⌀'   // ⌀ emptied out by the student

/**
 * Which glyph a field row shows.
 *
 * `original` is the server's row, `draft` the working copy. Comparing the two
 * -- rather than tracking a "touched" flag -- means a student who types a
 * change and then types it back reverts to "·", which is honest: the stored
 * value did come straight from the resume.
 */
export function fieldGlyph(original, draft, fieldName) {
  const before = normalizeFieldValue(original ? original[fieldName] : null)
  const after = normalizeFieldValue(draft ? draft[fieldName] : null)
  const changed = !sameValue(before, after)
  if (isEmptyValue(after)) return changed ? GLYPH_EMPTY : null
  return changed ? GLYPH_EDITED : GLYPH_READ
}

/** Editable field names on this row that are currently empty, in field order. */
export function entryGaps(table, row) {
  const section = REVIEW_SECTIONS[table]
  if (!section) return []
  return section.fields.filter((field) => isEmptyValue(row ? row[field.name] : null)).map((f) => f.name)
}

/** Editable field names on this row that are currently filled, in field order. */
export function entryFilled(table, row) {
  const section = REVIEW_SECTIONS[table]
  if (!section) return []
  return section.fields
    .filter((field) => !isEmptyValue(row ? row[field.name] : null))
    .map((f) => f.name)
}

/**
 * The three ledger counters, computed across every row on the page.
 *
 * `read` counts filled-and-unchanged, `edited` counts changed-and-still-filled,
 * `gaps` counts empty. They partition `total` exactly -- the commit bar and the
 * ledger both read this one function so they can never disagree, which is the
 * whole point of deriving it in one place.
 *
 * `rows` is a list of { table, original, draft } -- the caller assembles it
 * from whatever it has, so this stays free of section-shape knowledge.
 */
export function reviewCounters(rows) {
  let read = 0
  let edited = 0
  let gaps = 0

  for (const entry of rows || []) {
    const section = REVIEW_SECTIONS[entry.table]
    if (!section) continue
    for (const field of section.fields) {
      const glyph = fieldGlyph(entry.original, entry.draft, field.name)
      if (glyph === GLYPH_READ) read += 1
      else if (glyph === GLYPH_EDITED) edited += 1
      else gaps += 1
    }
  }

  const total = read + edited + gaps
  return {
    read,
    edited,
    gaps,
    total,
    // Progress is "how much of the document we have something for", which is
    // what the bar under the counters fills to.
    filledRatio: total === 0 ? 1 : (total - gaps) / total,
  }
}

/**
 * Coerce a `number` field's raw input.
 *
 * Returns null for anything unusable, INCLUDING an empty string -- an emptied
 * number field is a legitimate "not stated", handled by the caller reverting or
 * clearing. Rejects rather than rounds: a credit_hours the student typed as
 * "3 hours" is a mistake to surface, not a 3 to assume. Mirrors the backend's
 * coerce_credit_hours (GradusIQ_career/transcript/parser.py), including its
 * refusal to accept booleans or non-finite values.
 */
export function parseNumberInput(text) {
  if (typeof text === 'number') {
    return Number.isFinite(text) ? text : null
  }
  if (typeof text !== 'string') return null
  const trimmed = text.trim()
  if (trimmed === '') return null
  if (!/^-?\d*\.?\d+$/.test(trimmed)) return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}

/** Display form for a `number` field. Empty string when not stated. */
export function formatNumberInput(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (typeof value === 'string' && parseNumberInput(value) !== null) return value.trim()
  return ''
}
