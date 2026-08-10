export const TRANSCRIPT_UPLOAD_URL = '/api/v2/student/me/transcript/upload'
export const TRANSCRIPT_REVIEW_URL = '/api/v2/student/me/transcript/review'
export const TRANSCRIPT_CONFIRM_URL = '/api/v2/student/me/transcript/confirm'

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

export function detailText(body, fallback) {
  const detail = body && typeof body === 'object' ? body.detail : null
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
    return detail.message.trim() || fallback
  }
  return fallback
}

function failure(status, body, fallback) {
  if (status === 0) return { ok: false, kind: 'network', message: 'Could not reach the server.' }
  if (status === 401) return { ok: false, kind: 'unauthenticated', message: 'Your session has expired. Sign in again.' }
  if (status === 409) return { ok: false, kind: 'conflict', message: detailText(body, fallback) }
  if (status === 413) return { ok: false, kind: 'file_too_large', message: detailText(body, fallback) }
  if (status === 415) return { ok: false, kind: 'unsupported_format', message: detailText(body, fallback) }
  if (status === 422) return { ok: false, kind: 'invalid', message: detailText(body, fallback) }
  if (status === 429) return { ok: false, kind: 'busy', message: detailText(body, 'The service is busy. Try again shortly.') }
  return { ok: false, kind: 'server', message: detailText(body, fallback) }
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
    return { ...failure(status, body, 'Could not process that transcript.'), rejected: [], warnings: [], inserted: 0 }
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
  }
}

export function normalizeTranscriptPatch(status, body) {
  if (status === 200 && body && typeof body === 'object') {
    return { ok: true, kind: 'ok', message: '', record: body }
  }
  return { ...failure(status, body, 'Could not save that correction.'), record: null }
}

export function normalizeTranscriptConfirm(status, body) {
  if (status === 200 && body && typeof body === 'object' && body.status === 'ok') {
    return { ok: true, kind: 'ok', message: '', confirmed: Number(body.confirmed) || 0, repeats: body.repeats ?? null }
  }
  return { ...failure(status, body, 'Could not confirm your transcript.'), confirmed: 0, repeats: null }
}
