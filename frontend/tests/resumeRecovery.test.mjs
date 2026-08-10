import assert from 'node:assert/strict'
import test from 'node:test'

import { chromium } from 'playwright'
import { createServer } from 'vite'

const EMPTY = { career_profile: null, certifications: [], work_experience: [], projects: [] }
const PENDING = {
  career_profile: {
    id: 'cp-recovered', source: 'resume_parse', target_roles: ['Software Engineer'],
    interests: ['systems'], career_goals: null, geographic_preference: null,
    ai_anxiety_level: null, skills_technical: ['TypeScript'], skills_soft: [], ai_exposure: null,
  },
  certifications: [],
  work_experience: [{
    id: 'work-recovered', source: 'resume_parse', employer: 'Acme', role: 'Intern',
    duration: null, location: null, description: null, skills_gained: ['TypeScript'],
  }],
  projects: [],
}

function json(response, status = 200) {
  response.statusCode = status
  response.setHeader('content-type', 'application/json')
  response.end(JSON.stringify(status === 200 ? response.body : { detail: response.body }))
}

test('resume page recovers persisted review across load, error, confirmation, and upload', { timeout: 45_000 }, async (t) => {
  const state = { pending: true, failReview: false, reviewGets: 0, uploads: 0, confirms: 0 }
  const apiPlugin = {
    name: 'resume-recovery-test-api',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (path === '/api/v2/student/me/career/review' && request.method === 'GET') {
          state.reviewGets += 1
          response.body = state.failReview ? 'Could not load records for review.' : state.pending ? PENDING : EMPTY
          json(response, state.failReview ? 502 : 200)
          return
        }
        if (path === '/api/v2/student/me/career/confirm' && request.method === 'POST') {
          state.confirms += 1
          state.pending = false
          response.body = {
            status: 'ok', scope: 'all_unconfirmed',
            confirmed: { career_profiles: 1, certifications: 0, work_experience: 1, projects: 0 },
            total_confirmed: 2,
          }
          json(response)
          return
        }
        if (path === '/api/v2/student/me/resume/upload' && request.method === 'POST') {
          state.uploads += 1
          state.pending = true
          response.body = {
            status: 'ok', extraction: { status: 'ok', page_count: 1 }, warnings: [], model: 'test',
            career_profile: { outcome: 'inserted' },
            written: {
              certifications: { inserted: 0, skipped_duplicate: 0 },
              work_experience: { inserted: 1, skipped_duplicate: 0 },
              projects: { inserted: 0, skipped_duplicate: 0 },
            },
          }
          json(response)
          return
        }
        next()
      })
    },
  }

  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const url = `http://127.0.0.1:${String(address.port)}/resume-recovery-preview.html`

  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()

  // CASE 1: pending review exists; upload never flashes before review.
  await page.goto(url)
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
  assert.equal(await page.getByText('Add your resume').count(), 0)
  assert.equal(state.reviewGets, 1, 'recovered sections must prevent CareerReview from issuing a duplicate GET')

  // CASE 3: a full reload recovers from backend state again.
  await page.reload()
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
  assert.equal(state.reviewGets, 2)

  // CASE 5: confirmation clears backend pending state; reload shows upload.
  await page.getByRole('button', { name: 'Confirm all' }).click()
  await page.getByText('Your profile has been saved').waitFor()
  assert.equal(state.confirms, 1)
  await page.reload()
  await page.getByText('Add your resume').waitFor()
  assert.equal(await page.getByRole('heading', { name: 'Here’s what we read.' }).count(), 0)

  // CASE 4: an API failure is not treated as empty; retry performs a new GET.
  state.failReview = true
  await page.reload()
  await page.getByText('Could not check your resume').waitFor()
  assert.equal(await page.getByText('Add your resume').count(), 0)
  state.failReview = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await page.getByText('Add your resume').waitFor()

  // CASE 6: no-pending upload still enters the existing CareerReview flow.
  await page.locator('#resume-file').setInputFiles({
    name: 'resume.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-test'),
  })
  await page.getByRole('button', { name: 'Upload resume' }).click()
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
  assert.equal(state.uploads, 1)
  assert.equal(await page.getByText('Add your resume').count(), 0)
})
