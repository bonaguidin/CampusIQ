import assert from 'node:assert/strict'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

const PROFILE_ID = 'profile-phys-207'

const EXTRACTED_MODEL = {
  schema_version: '1',
  course: { course_code: 'PHYS 207', course_title: null, section: '529', term: 'Fall 2026', instructor: null },
  grading_method: 'weighted',
  categories: [
    { name: 'Mid-term Exam', weight: 35, count: null, evidence: { page: 2, text: 'Mid-term Exam: 35%', confidence: 1.0 } },
    { name: 'Final Exam', weight: 50, count: null, evidence: { page: 2, text: 'Final Exam: 50%', confidence: 1.0 } },
    { name: 'Lecture Quizzes', weight: 5, count: null, evidence: { page: 2, text: 'Lecture Quizzes: 5%', confidence: 1.0 } },
    { name: 'Recitation Quizzes', weight: 10, count: null, evidence: { page: 2, text: 'Recitation Quizzes: 10%', confidence: 1.0 } },
  ],
  assessments: [],
  grade_thresholds: [
    { letter: 'B', minimum: 80, maximum: 89, evidence: { page: 2, text: 'B: 80-89', confidence: 1.0 } },
    { letter: 'B+', minimum: 85, maximum: 92, evidence: { page: 2, text: 'B+: 85-92', confidence: 1.0 } },
  ],
  rules: [
    {
      rule_type: 'replacement', description: 'Final replaces Midterm when higher.',
      source: 'Final Exam', target: 'Mid-term Exam', condition: 'final_score > midterm_score',
      evidence: { page: 2, text: 'Final replaces Midterm when higher.', confidence: 1.0 },
    },
    {
      rule_type: 'curve', description: 'Grades may be curved upward.',
      source: null, target: null, condition: null,
      evidence: { page: 2, text: 'Grades may be curved upward.', confidence: 1.0 },
    },
  ],
  warnings: [{ type: 'possible_curve', description: 'No deterministic curve formula is given.', related_field: null }],
}

const CONFIRMED_MODEL = { ...EXTRACTED_MODEL, rules: [EXTRACTED_MODEL.rules[0]], warnings: [] }

// field values below use the real backend shapes (reconciliation.py): a
// per-rule-instance index for non_deterministic_grading_rule (rules[1] is
// the curve rule, index 1 in EXTRACTED_MODEL.rules), and the letter pair
// for overlapping_grade_thresholds. Messages are the real backend message
// templates, not placeholders -- this is what findingCopy()'s per-code
// templates in GradeCalculatorPanel.tsx actually parse.
const RECONCILIATION_REVIEW = {
  status: 'needs_student_review',
  findings: [
    { code: 'possible_curve', severity: 'warning', message: 'possible curve', field: null },
    {
      code: 'non_deterministic_grading_rule', severity: 'warning',
      message: 'curve rule is not structured precisely enough to apply deterministically: Grades may be curved upward.',
      field: 'rules[1]',
    },
    {
      code: 'overlapping_grade_thresholds', severity: 'error',
      message: "thresholds 'B' (80-89) and 'B+' (85-92) overlap",
      field: 'B,B+',
    },
  ],
  evidence_coverage: { total_claims: 6, supported_claims: 6, coverage_ratio: 1, unsupported_claims: [] },
}

const RECONCILIATION_ACCEPTED = {
  status: 'accepted',
  findings: [{ code: 'category_weight_validation', severity: 'valid', message: 'category weights sum to 100.0', field: 'categories' }],
  evidence_coverage: { total_claims: 5, supported_claims: 5, coverage_ratio: 1, unsupported_claims: [] },
}

function detail(overrides = {}) {
  return {
    id: PROFILE_ID,
    course: { institution: 'tamu', course_code: 'PHYS 207', term: 'Fall 2026', section: '529' },
    review_state: 'needs_review',
    calculator_ready: false,
    current_revision: { id: 'rev-1', source_filename: 'syllabus.pdf', source_page_count: 2, reconciliation_status: 'needs_student_review', confirmed_reconciliation_status: null, confirmed_at: null, created_at: '2026-01-01T00:00:00Z' },
    extracted_grade_model: EXTRACTED_MODEL,
    confirmed_grade_model: null,
    reconciliation: RECONCILIATION_REVIEW,
    confirmed_reconciliation: null,
    corrections: [],
    grade_state: null,
    grade_state_revision: null,
    possible_duplicate_profiles: [],
    revision_created: true,
    ...overrides,
  }
}

function readBody(request) {
  return new Promise((resolve) => {
    const chunks = []
    request.on('data', (chunk) => chunks.push(chunk))
    request.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
  })
}

function json(response, status, body) {
  response.statusCode = status
  response.setHeader('content-type', 'application/json')
  response.end(JSON.stringify(body))
}

test('Grade Calculator: empty state, upload, review, confirm, grade entry, calculate, target solve', { timeout: 45_000 }, async (t) => {
  // term id 'term-2' deliberately matches authenticatedDashboardPreview.tsx's
  // ?currentTerm=inprogress fixture (CS 221 / MATH 251, both in_progress),
  // so the eligible-course dropdown genuinely merges two sources under one
  // term: in-progress courses from the `courses` prop (CS 221, MATH 251)
  // and planned courses from this mock (PHYS 207) -- not just the latter.
  const planning = planningRoutes({
    terms: [{ key: '2026-Fall', id: 'term-2', label: 'Fall 2026', year: 2026, season: 'Fall', sequence: 1, start_date: '2026-08-24', end_date: '2026-12-10', enrolled: false, is_upcoming: true }],
    upcomingTermKey: '2026-Fall',
    state: { planned: [{ id: 'planned-phys', term_id: 'term-2', course_code: 'PHYS 207', title: 'Electricity and Magnetism', credit_hours: 4, catalog_course_id: null, created_at: null, kind: 'planned' }] },
  })
  let state = 'empty' // empty -> reviewing -> corrected -> confirmed
  let capturedIngestBody = null

  const apiPlugin = {
    name: 'grade-calculator-api',
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction') return json(response, 404, { detail: 'Not found.' })
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return json(response, 404, { detail: 'Not found.' })

        if (path === '/api/v2/student/me/syllabus-grade-profiles' && request.method === 'GET') {
          return json(response, 200, { syllabus_grade_profiles: [] })
        }
        if (path === '/api/v2/student/me/syllabus-grade-profiles/ingest' && request.method === 'POST') {
          // Captured (not asserted here): an assertion failure thrown inside
          // this middleware would reject the in-flight upload request rather
          // than fail the test cleanly. Asserted after the upload completes.
          capturedIngestBody = await readBody(request)
          state = 'reviewing'
          return json(response, 200, detail())
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && request.method === 'POST') {
          await readBody(request)
          state = 'corrected'
          return json(response, 200, detail({
            confirmed_reconciliation: RECONCILIATION_ACCEPTED,
            current_revision: { ...detail().current_revision, confirmed_reconciliation_status: 'accepted' },
          }))
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/confirm` && request.method === 'POST') {
          state = 'confirmed'
          return json(response, 200, detail({
            review_state: 'confirmed',
            calculator_ready: true,
            confirmed_grade_model: CONFIRMED_MODEL,
            confirmed_reconciliation: RECONCILIATION_ACCEPTED,
            current_revision: { ...detail().current_revision, confirmed_reconciliation_status: 'accepted', confirmed_at: '2026-01-01T00:00:00Z' },
          }))
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && request.method === 'GET') {
          if (state === 'confirmed') {
            return json(response, 200, detail({
              review_state: 'confirmed', calculator_ready: true,
              confirmed_grade_model: CONFIRMED_MODEL, confirmed_reconciliation: RECONCILIATION_ACCEPTED,
            }))
          }
          return json(response, 200, detail())
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/grade-state` && request.method === 'PUT') {
          const body = JSON.parse(await readBody(request))
          return json(response, 200, { revision: 1, category_scores: body.category_scores, assessment_scores: body.assessment_scores })
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/calculate` && request.method === 'POST') {
          await readBody(request)
          return json(response, 200, {
            grading_method: 'weighted',
            components: [],
            completed_weight: 50.0,
            earned_course_percentage: 40.7,
            current_grade: 81.4,
            projected_grade: null,
            current_letter_grade: null,
            projected_letter_grade: null,
            applied_rules: [],
            warnings: [],
          })
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/solve-target` && request.method === 'POST') {
          const body = JSON.parse(await readBody(request))
          const required = body.target_grade === 90 ? 90.12 : 78.35
          return json(response, 200, {
            target_component: 'Final Exam', target_grade: body.target_grade, target_label: null,
            required_score: required, feasible: true, already_achieved: false,
            applied_rules: [{ rule_type: 'replacement', source: 'Final Exam', target: 'Mid-term Exam', changed_calculation: true, description: 'Final replaces Midterm when higher.' }],
            warnings: [],
          })
        }
        next()
      })
    },
  }

  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-grade-calculator', import.meta.url).pathname,
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const origin = `http://127.0.0.1:${address.port}`

  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete&currentTerm=inprogress`)

  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Grade Calculator', exact: true }).click()

  // --- empty state ---
  await page.getByText('See what you need to reach your target grade').waitFor()
  assert.equal(await page.locator('.grade-calculator-panel [role="alert"]').count(), 0)
  assert.equal(await page.getByText('Not Found', { exact: true }).count(), 0)
  await page.getByRole('button', { name: 'Upload syllabus' }).click()

  // --- upload ---
  await page.setInputFiles('#syllabus-file', {
    name: 'syllabus.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 fake'),
  })
  await page.selectOption('#syllabus-term', { label: 'Fall 2026' })
  // --- the course dropdown genuinely merges eligibleCoursesByTerm from two
  //     sources for this term: CS 221 comes ONLY from the `courses` prop
  //     (an in_progress course, via ?currentTerm=inprogress), not from the
  //     fetchPlannedCourses mock -- proving the prop is actually wired in,
  //     not just passed through unused ---
  const courseOptionsText = await page.locator('#syllabus-course-code option').allTextContents()
  assert.ok(courseOptionsText.some((t) => t.includes('CS 221')), 'in_progress course from the courses prop must be selectable')
  assert.ok(courseOptionsText.some((t) => t.includes('PHYS 207')), 'planned course must still be selectable alongside it')
  await page.selectOption('#syllabus-course-code', 'PHYS 207')
  await page.getByRole('button', { name: 'Upload syllabus' }).click()

  // --- institutionName actually reaches the ingest request body, not just
  //     the component's own props ---
  await page.getByRole('heading', { name: 'Needs your review' }).waitFor()
  assert.ok(capturedIngestBody, 'ingest request body was captured')
  assert.match(capturedIngestBody, /name="institution"\r\n\r\nTexas A&M University\r\n/)

  // --- review-required state with findings + curve rule ---
  await page.getByText('Your syllabus says grades may be curved').waitFor()
  await page.getByText("The syllabus does not provide enough information").waitFor()

  // --- the old flat findings list is gone entirely ---
  assert.equal(await page.locator('.grade-findings-list').count(), 0)
  assert.equal(await page.locator('.grade-finding').count(), 0)

  // --- non_deterministic_grading_rule renders inline on its OWN rule card,
  //     with the real per-rule detail (not the old blanket generic string) ---
  const curveCard = page.locator('.grade-rule-card', { hasText: 'Curve' })
  await curveCard.getByText("CampusIQ can't calculate this curve rule automatically: Grades may be curved upward.").waitFor()
  assert.equal(
    await page.getByText("CampusIQ can't calculate this rule automatically.", { exact: true }).count(),
    0,
    'the old generic no-detail string must not appear',
  )
  // the replacement rule card (deterministic, no matching finding) carries no inline finding
  const replacementCard = page.locator('.grade-rule-card', { hasText: 'Score replacement' })
  assert.equal(await replacementCard.locator('.grade-inline-finding').count(), 0)

  // --- overlapping_grade_thresholds has no dedicated row in the review step
  //     (thresholds aren't rendered there), so it falls back to the General
  //     section at the top of the review card, with the real letters/ranges ---
  const general = page.locator('.grade-inline-findings--general')
  await general.getByText('Letter grades B and B+ have overlapping cutoffs: B is 80–89, B+ is 85–92.').waitFor()
  await general.getByText('Your syllabus says grades may be curved').waitFor()

  // --- dismiss is session-only: dismissing the threshold finding hides it
  //     immediately, with no network call, and it comes back on reopen ---
  const thresholdFinding = general.locator('.grade-inline-finding', { hasText: 'overlapping cutoffs' })
  await thresholdFinding.getByRole('button', { name: 'Dismiss this finding' }).click()
  assert.equal(await general.getByText('overlapping cutoffs').count(), 0)
  // the curve-rule finding, untouched, is still there
  await curveCard.getByText("CampusIQ can't calculate this curve rule automatically").waitFor()

  await page.getByRole('button', { name: '← Back to your calculators' }).click()
  await page.locator('.grade-profile-row-button', { hasText: 'PHYS 207' }).click()
  await page.getByRole('heading', { name: 'Needs your review' }).waitFor()
  // reopening re-fetched the same findings and dismissal did not persist
  await page.locator('.grade-inline-findings--general').getByText('overlapping cutoffs').waitFor()

  // --- ignore the curve rule (correction), then confirm ---
  await page.getByRole('button', { name: 'Ignore this rule for What-If calculations' }).click()
  await page.getByRole('button', { name: 'Confirm' }).click()

  // --- grade entry ---
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()
  await page.fill('#actual-category\\:Mid-term\\ Exam', '78')
  await page.fill('#actual-category\\:Lecture\\ Quizzes', '92')
  await page.fill('#actual-category\\:Recitation\\ Quizzes', '88')
  await page.getByRole('button', { name: 'Calculate' }).click()

  await page.getByText('81.4%').waitFor()
  await page.getByText('Based on 50% of the course completed').waitFor()

  // --- target solver ---
  await page.selectOption('#target-component', 'Final Exam')
  await page.fill('#target-numeric', '90')
  await page.getByRole('button', { name: 'Solve' }).click()
  await page.getByText('90.12').waitFor()

  // --- responsive: no horizontal overflow ---
  for (const width of [390, 834, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      true,
      `horizontal overflow at ${width}px`,
    )
  }
})

test('Grade Calculator replaces a framework 404 with friendly list-load copy', { timeout: 30_000 }, async (t) => {
  const planning = planningRoutes({ terms: [] })
  const apiPlugin = {
    name: 'grade-calculator-list-error',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction') return json(response, 404, { detail: 'Not found.' })
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return json(response, 404, { detail: 'Not found.' })
        if (path === '/api/v2/student/me/syllabus-grade-profiles' && request.method === 'GET') {
          return json(response, 404, { detail: 'Not Found' })
        }
        next()
      })
    },
  }
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-grade-calculator-list-error', import.meta.url).pathname,
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()
  await page.goto(`http://127.0.0.1:${address.port}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Grade Calculator', exact: true }).click()
  await page.getByRole('alert').getByText("We couldn't load your saved grade calculators. Try again.").waitFor()
  assert.equal(await page.getByText('Not Found', { exact: true }).count(), 0)
})
