import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeTranscriptConfirm, normalizeTranscriptPatch, normalizeTranscriptReview, normalizeTranscriptUpload } from '../src/lib/transcriptApi.mjs'

test('transcript API normalizers follow the backend response shapes', () => {
  const review = normalizeTranscriptReview(200, { course_records: [{ id: '1' }], terms: [{ id: 't' }], institutions: [{ id: 'i' }], excluded_by_repeat: [], pending_catalog_review: 1 })
  assert.equal(review.ok, true); assert.equal(review.records.length, 1); assert.equal(review.pendingCatalogReview, 1)
  assert.equal(normalizeTranscriptUpload(200, { status: 'ok', written: { course_records: { inserted: 2 } } }).inserted, 2)
  assert.equal(normalizeTranscriptPatch(422, { detail: 'bad credits' }).message, 'bad credits')
  assert.equal(normalizeTranscriptConfirm(409, { detail: { message: 'scale pending' } }).message, 'scale pending')
})

test('transcript recovery failure never normalizes as an empty success', () => {
  const result = normalizeTranscriptReview(502, { detail: 'database unavailable' })
  assert.equal(result.ok, false); assert.equal(result.records.length, 0); assert.equal(result.message, 'database unavailable')
})
