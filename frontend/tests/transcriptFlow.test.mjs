import assert from 'node:assert/strict'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'

const ROW_ID = '11111111-1111-4111-8111-111111111111'
const REPEAT_ID = '22222222-2222-4222-8222-222222222222'
const TERM_ID = '33333333-3333-4333-8333-333333333333'
const baseRow = { id: ROW_ID, course_code: 'MATH 251', title: 'Engineering Mathematics III', credit_hours: '3.00', letter_grade: 'B', status: 'completed', term_id: TERM_ID, catalog_course_id: null, counts_toward_credit: true, counts_toward_gpa: true, credit_type: 'resident', source: 'transcript_parse', needs_catalog_review: true, repeat_exclusion: null }
const repeatRow = { ...baseRow, id: REPEAT_ID, course_code: 'MATH 151', letter_grade: 'C', needs_catalog_review: false, repeat_exclusion: { excluded_from_gpa: true, reason: 'repeat_replacement', superseded_by_id: ROW_ID, superseded_by: { id: ROW_ID, course_code: 'MATH 251', letter_grade: 'B', term_id: TERM_ID }, still_counts_toward_earned_hours: true } }
const payload = (state) => ({ course_records: state.pending ? [state.row] : [], terms: [{ id: TERM_ID, label: 'Fall 2025', year: 2025, season: 'fall', sequence: 1, institution_id: 'i' }], institutions: [{ id: 'i', name: 'Texas A&M University' }], pending_catalog_review: state.pending ? 1 : 0, excluded_by_repeat: state.pending ? [repeatRow] : [] })
function respond(response, body, status = 200) { response.statusCode = status; response.setHeader('content-type', 'application/json'); response.end(JSON.stringify(status === 200 ? body : { detail: body })) }

test('transcript flow covers upload, recovery, edits, repeats, failures, confirmation, and mobile', { timeout: 45_000 }, async (t) => {
  const state = { pending: false, recoveryFails: false, uploadFails: false, editFails: false, row: { ...baseRow }, uploads: 0 }
  const plugin = { name: 'transcript-api', configureServer(server) { server.middlewares.use((request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/transcript/review' && request.method === 'GET') return state.recoveryFails ? respond(response, 'Could not load course records for review.', 502) : respond(response, payload(state))
    if (path === '/api/v2/student/me/transcript/upload' && request.method === 'POST') { state.uploads++; if (state.uploadFails) return respond(response, { error: 'extraction_failed', message: 'This looks like a scanned transcript.' }, 422); state.pending = true; return respond(response, { status: 'ok', warnings: [], rejected: [], written: { course_records: { inserted: 1, skipped_duplicate: 0 } } }) }
    if (path === `/api/v2/student/me/transcript/review/${ROW_ID}` && request.method === 'PATCH') { if (state.editFails) return respond(response, 'The grade was rejected.', 422); let body=''; request.on('data', (chunk) => { body += chunk }); request.on('end', () => { state.row = { ...state.row, ...JSON.parse(body), title: 'Server-canonical title' }; respond(response, state.row) }); return }
    if (path === '/api/v2/student/me/transcript/confirm' && request.method === 'POST') { state.pending = false; return respond(response, { status: 'ok', confirmed: 1, scope: 'all_unconfirmed', repeats: {} }) }
    next()
  }) } }
  const server = await createServer({ root: new URL('..', import.meta.url).pathname, logLevel: 'silent', plugins: [plugin], server: { host: '127.0.0.1' } }); await server.listen(); t.after(async () => server.close())
  const address = server.httpServer?.address(); assert.ok(address && typeof address === 'object'); const url = `http://127.0.0.1:${address.port}/transcript-preview.html`
  const browser = await chromium.launch(); t.after(async () => browser.close()); const page = await browser.newPage()

  // No transcript; failed extraction stays on upload with a useful error.
  await page.goto(url); await page.getByRole('heading', { name: 'Add your transcript' }).waitFor()
  state.uploadFails = true; await page.locator('#transcript-file').setInputFiles({ name: 'scan.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF') }); await page.getByRole('button', { name: 'Upload transcript' }).click(); await page.getByText('This looks like a scanned transcript.').waitFor(); assert.equal(await page.getByText('Verify your academic record').count(), 0)

  // Successful upload enters the review returned by persistent server state.
  state.uploadFails = false; await page.getByRole('button', { name: 'Choose another file' }).click(); await page.locator('#transcript-file').setInputFiles({ name: 'record.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF') }); await page.getByRole('button', { name: 'Upload transcript' }).click(); await page.getByRole('heading', { name: 'Verify your academic record' }).waitFor(); assert.equal(state.uploads, 2)
  await page.getByText('Fall 2025').waitFor(); await page.getByText(/was replaced by MATH 251/).waitFor(); await page.getByText('Resident (default)').waitFor()

  // Edit failure does not replace rendered data; success uses server response.
  await page.getByRole('button', { name: 'Edit MATH 251' }).click(); await page.getByLabel('Course title').fill('Client title'); state.editFails = true; await page.getByRole('button', { name: 'Save correction' }).click(); await page.getByText('The grade was rejected.').waitFor(); assert.equal(await page.getByText('Client title', { exact: true }).count(), 0)
  state.editFails = false; await page.getByRole('button', { name: 'Save correction' }).click(); await page.getByText('Server-canonical title').waitFor()

  // Pending state survives refresh and remains usable on mobile without page overflow.
  await page.reload(); await page.getByRole('heading', { name: 'Verify your academic record' }).waitFor(); await page.setViewportSize({ width: 390, height: 844 }); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)

  // Confirmation clears pending server state; refresh returns to upload.
  await page.getByRole('button', { name: 'Confirm 1 courses' }).click(); await page.getByRole('heading', { name: 'Your transcript is saved' }).waitFor(); await page.reload(); await page.getByRole('heading', { name: 'Add your transcript' }).waitFor()

  // Recovery failure is explicit and retryable, never an upload fallback.
  state.recoveryFails = true; await page.reload(); await page.getByRole('heading', { name: 'Could not check your transcript' }).waitFor(); assert.equal(await page.getByRole('heading', { name: 'Add your transcript' }).count(), 0); state.recoveryFails = false; await page.getByRole('button', { name: 'Try again' }).click(); await page.getByRole('heading', { name: 'Add your transcript' }).waitFor()
})
