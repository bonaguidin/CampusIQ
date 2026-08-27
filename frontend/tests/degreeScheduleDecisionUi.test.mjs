import assert from 'node:assert/strict'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

const candidate = (id, codes, credits) => ({
  candidate_id: id, requirement_group_id: 'choice', requirement_name: 'Statistical Methods',
  course_codes: codes, unresolved_course_codes: [],
  candidate_courses: codes.map((code, index) => ({
    course_code: code,
    title: code === 'ABC 123' ? null : `${code} catalog title`,
    credits: code === 'ABC 123' ? null : credits[index],
  })),
  existing_contribution: 0, additional_course_count: codes.length,
  additional_credits: credits.reduce((total, value) => total + value, 0),
  academic_feasibility: 'FEASIBLE', completion_term_index: 1,
  limitations: [], source_order: [], exclusion_reasons: [], exclusion_details: [],
})

test('Degree Schedule decisions are actionable, grouped, deduplicated, and responsive', { timeout: 60_000 }, async (t) => {
  const single = candidate('single', ['ABC 123'], [3])
  const multi = candidate('multi', ['CEE 2302', 'CS 3377'], [3, 3])
  const schedule = {
    student_id: 'sid', program_id: 'pid', status: 'SCHEDULED', failure: null,
    schedule_version: `sha256:${'a'.repeat(64)}`,
    selection_state: { status: 'NONE', selections: [], failure: null },
    terms: [{ term_key: '2026-Fall', total_credit_hours: 3, courses: [{ course_code: 'MATH 2413', credit_hours: 3, requirement_group_id: 'auto', limitations: [] }] }],
    decisions: [
      { requirement_group_id: 'auto', requirement_name: 'Calculus', state: 'AUTO_SELECTED', feasible_candidate_ids: ['auto'], excluded_candidate_ids: [], selected_candidate_id: 'auto' },
      { requirement_group_id: 'choice', requirement_name: 'Statistical Methods', state: 'CHOICE_REQUIRED', feasible_candidate_ids: ['single', 'multi'], excluded_candidate_ids: [], selected_candidate_id: null },
      { requirement_group_id: 'review', requirement_name: 'Restricted Elective', state: 'ADVISER_REVIEW', feasible_candidate_ids: [], excluded_candidate_ids: ['reviewed'], selected_candidate_id: null },
      { requirement_group_id: 'unknown', requirement_name: 'Unstructured Requirement', state: 'DATA_UNRESOLVED', feasible_candidate_ids: [], excluded_candidate_ids: ['unknown'], selected_candidate_id: null },
    ],
    candidate_sets: [{ requirement_group_id: 'choice', requirement_name: 'Statistical Methods', feasible_candidates: [single, multi], excluded_candidates: [] }],
    unscheduled: [
      { requirement_group_id: 'choice', name: 'Statistical Methods', reason: 'SELECTION_DEFERRED' },
      { requirement_group_id: 'ucc', name: 'University Core Curriculum', reason: 'FREEFORM_MANUAL_REVIEW' },
    ],
  }
  const putBodies = []
  let nextPutConflict = null
  const planning = planningRoutes({ terms: [] })
  const apiPlugin = {
    name: 'degree-schedule-decisions-api',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/schedule' && request.method === 'GET') {
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(schedule))
          return
        }
        if (path === '/api/v2/student/me/schedule/choices' && request.method === 'PUT') {
          let raw = ''
          request.on('data', (chunk) => { raw += chunk })
          request.on('end', () => {
            const body = JSON.parse(raw)
            putBodies.push(body)
            if (nextPutConflict) {
              response.statusCode = 409
              response.setHeader('content-type', 'application/json')
              response.end(JSON.stringify({ detail: { code: nextPutConflict } }))
              nextPutConflict = null
              return
            }
            const chosen = body.selections[0]
            schedule.schedule_version = `sha256:${'b'.repeat(64)}`
            schedule.selection_state = { status: 'APPLIED', selections: body.selections, failure: null }
            schedule.decisions = schedule.decisions.map((decision) => decision.requirement_group_id === chosen.requirement_group_id
              ? { ...decision, state: 'LOCKED', selected_candidate_id: chosen.candidate_id }
              : decision)
            response.setHeader('content-type', 'application/json')
            response.end(JSON.stringify({ status: 'APPLIED', schedule_version: schedule.schedule_version, selections: body.selections }))
          })
          return
        }
        if (path === '/api/v2/student/me/requirement-satisfaction' && request.method === 'GET') {
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify({ student_id: 'sid', program_id: 'pid', groups: [] }))
          return
        }
        next()
      })
    },
  }
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-degree-schedule-decisions', import.meta.url).pathname,
    logLevel: 'silent', plugins: [apiPlugin], server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  await page.route('**/rest/v1/institutions*', (route) => route.fulfill({ status: 200, body: 'null' }))
  await page.goto(`http://127.0.0.1:${address.port}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()

  const section = page.locator('.degree-schedule-decisions')
  await section.getByText('Decisions needed to complete your plan').waitFor()
  assert.equal(await section.getByText('Statistical Methods').count(), 1)
  assert.equal(await section.getByText('2 valid options').count(), 1)
  assert.equal(await section.getByText('ABC 123').count(), 1)
  assert.equal(await section.getByText('CEE 2302', { exact: true }).count(), 1)
  assert.equal(await section.getByText('CS 3377', { exact: true }).count(), 1)
  assert.equal(await section.getByText('6 credits total').count(), 1)
  assert.equal(await section.getByText('Adviser review needed').count(), 1)
  assert.equal(await section.getByText('Course data unavailable').count(), 1)
  assert.equal(await section.getByText('University Core Curriculum').count(), 1)
  assert.equal(await section.getByText('Calculus').count(), 0)
  assert.doesNotMatch(await section.textContent(), /Recommended|Best option|UNKNOWN 999|null/)
  assert.equal(await section.getByRole('button', { name: /Choose ABC 123 for Statistical Methods/ }).count(), 1)
  assert.equal(await section.getByRole('button', { name: /Choose CEE 2302 and CS 3377 for Statistical Methods/ }).count(), 1)

  await section.getByRole('button', { name: /Choose CEE 2302 and CS 3377 for Statistical Methods/ }).click()
  await section.getByText('Your academic choices').waitFor()
  assert.equal(putBodies.length, 1)
  assert.deepEqual(putBodies[0], {
    schedule_version: `sha256:${'a'.repeat(64)}`,
    selections: [{ requirement_group_id: 'choice', candidate_id: 'multi', course_codes: ['CEE 2302', 'CS 3377'] }],
  })
  assert.equal(await section.getByText('Selected', { exact: true }).count() >= 1, true)
  assert.equal(await section.getByRole('button', { name: 'Change choice' }).count(), 1)
  assert.equal(await section.getByRole('button', { name: 'Clear choice' }).count(), 1)

  nextPutConflict = 'SCHEDULE_VERSION_CONFLICT'
  await section.getByRole('button', { name: 'Change choice' }).click()
  await section.getByRole('button', { name: /Change to ABC 123 for Statistical Methods/ }).click()
  await section.getByText(/degree plan changed while you were choosing/).waitFor()
  assert.equal(putBodies.length, 2)
  assert.equal(await section.getByText('Selected', { exact: true }).count() >= 1, true)

  schedule.selection_state = {
    status: 'RESELECTION_REQUIRED',
    selections: [{ requirement_group_id: 'choice', candidate_id: 'removed', course_codes: ['OLD 1000'] }],
    failure: {
      code: 'LOCK_CANDIDATE_NOT_FOUND', requirement_group_id: 'choice', candidate_id: 'removed',
      current_course_codes: [], submitted_course_codes: ['OLD 1000'], exclusion_reasons: [],
    },
  }
  schedule.decisions = schedule.decisions.map((decision) => decision.requirement_group_id === 'choice'
    ? { ...decision, state: 'CHOICE_REQUIRED', selected_candidate_id: null }
    : decision)
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await section.getByText('Your saved course choice needs attention').waitFor()
  assert.equal(await section.getByRole('button', { name: 'Clear saved choice' }).count(), 1)
  assert.equal(await section.getByRole('button', { name: /Choose ABC 123 for Statistical Methods/ }).count(), 1)

  const multiPath = section.locator('.degree-schedule-candidate-path').filter({ hasText: 'CEE 2302' })
  assert.equal(await multiPath.getByText('CS 3377', { exact: true }).count(), 1)
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await section.evaluate((element) => element.scrollWidth <= element.clientWidth), true)
  assert.equal(await multiPath.evaluate((element) => element.scrollWidth <= element.clientWidth), true)
  assert.equal(await section.getByRole('button', { name: 'Clear saved choice' }).isVisible(), true)

  await section.getByRole('button', { name: /Choose ABC 123 for Statistical Methods/ }).click()
  await section.getByText('Your academic choices').waitFor()
  assert.equal(putBodies.length, 3)
  assert.deepEqual(putBodies[2].selections, [{
    requirement_group_id: 'choice', candidate_id: 'single', course_codes: ['ABC 123'],
  }])
})
