export const TRANSCRIPT_UPLOAD_URL = '/api/v2/student/me/transcript/upload'
export const TRANSCRIPT_REVIEW_URL = '/api/v2/student/me/transcript/review'
export const TRANSCRIPT_CONFIRM_URL = '/api/v2/student/me/transcript/confirm'

// Imported and re-exported from resumeApi so the two flows cannot drift on
// either the timeout budget or the sentinel status. See resumeApi.mjs for the
// reasoning behind both values.
import { CONFIRM_TIMEOUT_MS, REQUEST_TIMEOUT_STATUS } from './resumeApi.mjs'

export { CONFIRM_TIMEOUT_MS, REQUEST_TIMEOUT_STATUS }

export const TRANSCRIPT_FIELDS = [
  'course_code',
  'title',
  'credit_hours',
  'letter_grade',
  'status',
]

export function transcriptEditUrl(id) {
  return `${TRANSCRIPT_REVIEW_URL}/${encodeURIComponent(id)}`
}

// ── section config ──────────────────────────────────────────────────────────

/** The only values course_records.status may take (parser.VALID_COURSE_STATUSES). */
export const COURSE_STATUS_VALUES = ['completed', 'in_progress']

/**
 * The transcript review surface's field config -- deliberately PARALLEL to
 * resumeApi's REVIEW_SECTIONS rather than an entry inside it.
 *
 * transcript/review.py:9-16 argues the same separation on the backend: adding
 * course_records to the career review's table map would put course rows into
 * the career payload, which the career screen would then render. The two are
 * separate screens over separate data. Sharing the *pattern* -- the field
 * descriptor shape, and so every component that consumes it -- is the reuse
 * worth having; sharing the registry is not.
 *
 * Field types are the existing FieldRow vocabulary, unchanged:
 *   course_code / title / letter_grade -> text
 *   status                             -> status (see COURSE_STATUS_VALUES)
 *   credit_hours                       -> number  (its first real consumer)
 *
 * subtitleFields is transcript-specific: the resume card derives its subtitle
 * by scanning for the first two filled non-title fields, which here would pick
 * up `title` and read as a duplicate of nothing useful. Naming the two wanted
 * (credits, grade) ports what TranscriptReview already showed in its meta row.
 */
export const TRANSCRIPT_SECTION = {
  label: 'Courses',
  singular: 'course',
  titleField: 'course_code',
  subtitleFields: ['credit_hours', 'letter_grade'],
  fields: [
    { name: 'course_code', label: 'Course code', type: 'text' },
    { name: 'title', label: 'Course title', type: 'text' },
    { name: 'credit_hours', label: 'Credits', type: 'number' },
    { name: 'letter_grade', label: 'Grade', type: 'text' },
    { name: 'status', label: 'Status', type: 'status' },
  ],
}

/** Editable field names, mirroring review.py's EDITABLE_FIELDS exactly. */
export const TRANSCRIPT_SECTIONS = { course_records: TRANSCRIPT_SECTION }

// ── credit_hours boundary ───────────────────────────────────────────────────

/**
 * Backend string -> number, for the FieldRow edit boundary only.
 *
 * course_records.credit_hours is stored and returned as a STRING
 * (review.py:307 does str(coerced)), while FieldRow's number type works in
 * JS numbers. Converting anywhere other than this boundary would spread the
 * string/number ambiguity through the draft state.
 */
export function parseCreditHours(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (trimmed === '') return null
  if (!/^-?\d*\.?\d+$/.test(trimmed)) return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}

/**
 * Number -> the 2-decimal string the backend stores, for the save boundary.
 *
 * THIS IS WHAT KEEPS A NO-OP EDIT FROM LOOKING LIKE A REAL ONE. The row
 * arrives as "3.00"; opening and closing the editor without typing yields the
 * number 3; `sameValue` is a strict ===, so "3.00" !== 3 would mark the field
 * edited and PATCH a value identical to the stored one. Canonicalizing both
 * sides to "3.00" before any comparison makes a pure reformat a no-op, which
 * is exactly what it is.
 *
 * Returns null for values that do not parse -- reverting garbage is FieldRow's
 * job at the edit boundary, and by the time a value reaches here it has
 * already survived that check.
 */
export function formatCreditHours(value) {
  const parsed = parseCreditHours(value)
  return parsed === null ? null : parsed.toFixed(2)
}

/**
 * One field's value in the form both sides of a comparison can agree on.
 *
 * Only credit_hours needs it; every other transcript field is a plain string
 * the shared normalizeFieldValue already handles.
 */
export function canonicalTranscriptValue(fieldName, value) {
  if (fieldName === 'credit_hours') return formatCreditHours(value)
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed === '' ? null : trimmed
  }
  return value ?? null
}

/**
 * Only the fields that actually changed, canonicalized first.
 *
 * The transcript twin of resumeApi's changedFields. Separate because that one
 * resolves its allowed field list through REVIEW_SECTIONS, and because it has
 * no notion of credit_hours' string/number duality.
 */
export function transcriptChangedFields(original, draft) {
  const changes = {}
  for (const field of TRANSCRIPT_SECTION.fields) {
    const name = field.name
    const before = canonicalTranscriptValue(name, original ? original[name] : undefined)
    const after = canonicalTranscriptValue(name, draft ? draft[name] : undefined)
    if (before !== after) changes[name] = after
  }
  return changes
}

/** Whether a transcript field differs from its parsed original, canonically. */
export function transcriptFieldChanged(original, draft, fieldName) {
  return (
    canonicalTranscriptValue(fieldName, original ? original[fieldName] : undefined) !==
    canonicalTranscriptValue(fieldName, draft ? draft[fieldName] : undefined)
  )
}

export function detailText(body, fallback) {
  const detail = body && typeof body === 'object' ? body.detail : null
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
    return detail.message.trim() || fallback
  }
  return fallback
}

function bodyDetail(body) {
  return body && typeof body === 'object' ? body.detail : undefined
}

/**
 * The `error` code carried on a structured detail, else null.
 *
 * Same shape of helper as resumeApi's detailExtractionStatus, for the same
 * reason: several distinct backend conditions share one HTTP status, and the
 * discriminator is a key on the detail OBJECT. Branching on the message text
 * instead would break the next time someone rewords a sentence -- which is
 * exactly what extraction.py warns against.
 */
export function detailErrorCode(detail) {
  if (detail && typeof detail === 'object' && typeof detail.error === 'string') {
    return detail.error
  }
  return null
}

/** The extraction_status carried on 415/422 upload errors, else null. */
export function detailExtractionStatus(detail) {
  if (detail && typeof detail === 'object' && typeof detail.extraction_status === 'string') {
    return detail.extraction_status
  }
  return null
}

/**
 * Map an HTTP failure onto a kind the UI can branch on.
 *
 * Three statuses carry more than one backend meaning, and in each case the
 * remedy differs -- so collapsing them loses the only thing the student can
 * act on:
 *
 *   413  a file over MAX_TRANSCRIPT_BYTES (send a smaller file) vs.
 *        TranscriptTooLongError (the CONTENT is too long for the parser; a
 *        smaller file is not the fix). Plain-string detail vs. {error}.
 *   422  an encrypted PDF (a ten-second fix the student owns) vs. any other
 *        unprocessable body. Discriminated on extraction_status, which
 *        extraction.py made a status of its own precisely so callers branch.
 *   409  grade_scale_unverified -- a state of OUR data that the student can do
 *        nothing about -- vs. no-home-institution / no-grading-scale /
 *        already-confirmed, which behave like ordinary conflicts.
 */
function failure(status, body, fallback) {
  const detail = bodyDetail(body)
  const code = detailErrorCode(detail)

  if (status === 0) return { ok: false, kind: 'network', message: 'Could not reach the server.' }
  // Distinct from 'network' on purpose: the request did reach the server, we
  // just stopped waiting for it. Same copy as the resume flow's timeout.
  if (status === REQUEST_TIMEOUT_STATUS) return { ok: false, kind: 'timeout', message: 'This is taking longer than expected. The server may still be starting up — try again in a moment.' }
  if (status === 401) return { ok: false, kind: 'unauthenticated', message: 'Your session has expired. Sign in again.' }
  if (status === 409) {
    const kind = code === 'grade_scale_unverified' ? 'grade_scale_unverified' : 'conflict'
    return { ok: false, kind, message: detailText(body, fallback) }
  }
  if (status === 413) {
    const kind = code === 'transcript_too_long' ? 'transcript_too_long' : 'file_too_large'
    return { ok: false, kind, message: detailText(body, fallback) }
  }
  if (status === 415) return { ok: false, kind: 'unsupported_format', message: detailText(body, fallback) }
  if (status === 422) {
    const kind = detailExtractionStatus(detail) === 'encrypted' ? 'encrypted' : 'invalid'
    return { ok: false, kind, message: detailText(body, fallback) }
  }
  if (status === 429) return { ok: false, kind: 'busy', message: detailText(body, 'The service is busy. Try again shortly.') }
  return { ok: false, kind: 'server', message: detailText(body, fallback) }
}

/** Empty-but-well-formed cross-check, so callers never branch on absence. */
const NO_CROSS_CHECK = { ok: true, termsChecked: 0, termsSkipped: 0, mismatches: [] }

/**
 * The arithmetic cross-check the upload route already returns.
 *
 * Advisory only -- `ok: false` means printed and computed totals disagree, NOT
 * that the upload failed. It was previously dropped on the floor here, so the
 * data reached the client and was discarded before any UI could show it.
 */
function normalizeCrossCheck(raw) {
  if (!raw || typeof raw !== 'object') return NO_CROSS_CHECK
  return {
    ok: raw.ok !== false,
    termsChecked: Number.isFinite(raw.terms_checked) ? raw.terms_checked : 0,
    termsSkipped: Number.isFinite(raw.terms_skipped) ? raw.terms_skipped : 0,
    mismatches: Array.isArray(raw.mismatches) ? raw.mismatches : [],
  }
}

/** Catalog match report. Same "dropped on the floor" history as cross_check. */
function normalizeCatalog(raw) {
  if (!raw || typeof raw !== 'object') return { matched: 0, unmatched: 0, misses: [] }
  return {
    matched: Number.isFinite(raw.matched) ? raw.matched : 0,
    unmatched: Number.isFinite(raw.unmatched) ? raw.unmatched : 0,
    misses: Array.isArray(raw.misses) ? raw.misses : [],
  }
}

export function normalizeTranscriptReview(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return { ...failure(status, body, 'Could not load your transcript review.'), records: [], terms: [], institutions: [], excludedByRepeat: [], pendingCatalogReview: 0 }
  }
  return {
    ok: true,
    kind: 'ok',
    message: '',
    records: Array.isArray(body.course_records) ? body.course_records : [],
    terms: Array.isArray(body.terms) ? body.terms : [],
    institutions: Array.isArray(body.institutions) ? body.institutions : [],
    excludedByRepeat: Array.isArray(body.excluded_by_repeat) ? body.excluded_by_repeat : [],
    pendingCatalogReview: Number.isFinite(body.pending_catalog_review) ? body.pending_catalog_review : 0,
  }
}

export function normalizeTranscriptUpload(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return {
      ...failure(status, body, 'Could not process that transcript.'),
      rejected: [], warnings: [], inserted: 0,
      crossCheck: NO_CROSS_CHECK, catalog: normalizeCatalog(null),
    }
  }
  if (body.status !== 'ok') {
    const defaults = {
      not_a_transcript: 'That file does not look like an academic transcript.',
      unparseable: 'We could not reliably read the academic records in that file.',
      parse_failed: 'We read the file but could not structure its academic records.',
    }
    return {
      ok: false,
      kind: body.status || 'parse_failed',
      message: defaults[body.status] || 'Could not process that transcript.',
      rejected: Array.isArray(body.rejected) ? body.rejected : [],
      warnings: Array.isArray(body.warnings) ? body.warnings : [],
      inserted: 0,
      // A non-ok parse never reaches the cross-check or catalog steps, so these
      // are structurally absent rather than empty. Same shape regardless, so no
      // caller has to branch on which failure path it came from.
      crossCheck: NO_CROSS_CHECK,
      catalog: normalizeCatalog(null),
    }
  }
  const inserted = body.written?.course_records?.inserted
  return {
    ok: true,
    kind: 'ok',
    message: 'Transcript read successfully.',
    rejected: Array.isArray(body.rejected) ? body.rejected : [],
    warnings: Array.isArray(body.warnings) ? body.warnings : [],
    inserted: Number.isFinite(inserted) ? inserted : 0,
    crossCheck: normalizeCrossCheck(body.cross_check),
    catalog: normalizeCatalog(body.catalog),
  }
}

/**
 * Distinguishes the PATCH route's two unrelated 409s.
 *
 * Both ReviewRowAlreadyConfirmed and ReviewConflict are raised as
 * HTTPException(409, detail=str(exc)) -- a plain string with no `error` code
 * to branch on -- so a message substring is the only discriminator available.
 * This is the same compromise resumeApi makes (its "disagreement #4"), and it
 * is a compromise: it breaks if review.py's wording changes. It is confined to
 * this one constant so there is a single place to fix if that happens.
 *
 * Deliberately NOT how grade_scale_unverified is detected -- that one carries a
 * structured {error} code, so it gets branched on properly.
 */
const ALREADY_CONFIRMED_MARKER = 'already been confirmed'

export function normalizeTranscriptPatch(status, body) {
  if (status === 200 && body && typeof body === 'object') {
    return { ok: true, kind: 'ok', message: '', record: body }
  }

  // The row is gone, for a reason the backend deliberately will not disclose:
  // review.py returns 404 for both "no such row" and "another student's row",
  // so the UI must not invent the distinction back. Previously this fell
  // through to a generic server error, which left a vanished row on screen.
  if (status === 404) {
    return {
      ok: false,
      kind: 'not_found',
      message: 'That course is no longer available. It has been removed from this list.',
      record: null,
    }
  }

  if (status === 409) {
    const text = detailText(body, '')
    const confirmed = text.toLowerCase().includes(ALREADY_CONFIRMED_MARKER)
    return {
      ok: false,
      kind: confirmed ? 'already_confirmed' : 'conflict',
      message: confirmed
        ? 'This course was already confirmed and can no longer be edited.'
        : text || 'That value collides with another course record.',
      record: null,
    }
  }

  return { ...failure(status, body, 'Could not save that correction.'), record: null }
}

export function normalizeTranscriptConfirm(status, body) {
  if (status === 200 && body && typeof body === 'object' && body.status === 'ok') {
    return { ok: true, kind: 'ok', message: '', confirmed: Number(body.confirmed) || 0, repeats: body.repeats ?? null }
  }
  return { ...failure(status, body, 'Could not confirm your transcript.'), confirmed: 0, repeats: null }
}
