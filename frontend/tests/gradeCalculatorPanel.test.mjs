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

// Confirmed model keeps the deterministic replacement rule (calculator-
// executed) plus a spread of informational rules -- curve / late work /
// makeup -- that must land in the persistent "Professor's rules" panel,
// not the review list.
const CONFIRMED_MODEL = {
  ...EXTRACTED_MODEL,
  rules: [
    EXTRACTED_MODEL.rules[0], // replacement (deterministic)
    EXTRACTED_MODEL.rules[1], // curve
    {
      rule_type: 'late_work', description: 'No late homework will be accepted.',
      source: null, target: null, condition: null,
      evidence: { page: 3, text: 'No late homework will be accepted.', confidence: 1.0 },
    },
    {
      rule_type: 'makeup', description: 'Makeup exams require a documented, university-excused absence.',
      source: null, target: null, condition: null,
      evidence: { page: 4, text: 'Makeup exams require a documented, university-excused absence.', confidence: 1.0 },
    },
  ],
  warnings: [],
}

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
    clarifying_answers: {},
    cutoff_overlap_resolution: { schema_version: '1', resolved: [], unresolved: [] },
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
  let capturedGradeStateBody = null

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
          capturedGradeStateBody = body
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

  // --- review-required state: the curve rule still lists under "Special
  //     grading rules" with its can't-calculate note, but the rule-based
  //     findings (non_deterministic_grading_rule, possible_curve) no longer
  //     appear in the review list -- they're informational now ---
  await page.getByText("The syllabus does not provide enough information").waitFor()

  // --- the old flat findings list is gone entirely ---
  assert.equal(await page.locator('.grade-findings-list').count(), 0)
  assert.equal(await page.locator('.grade-finding').count(), 0)

  const reviewCard = page.locator('.grade-review-card')
  // rule-informational findings are filtered out of the review list
  assert.equal(await reviewCard.locator('[data-finding-code="non_deterministic_grading_rule"]').count(), 0)
  assert.equal(await reviewCard.locator('[data-finding-code="possible_curve"]').count(), 0)
  assert.equal(await reviewCard.getByText('Your syllabus says grades may be curved').count(), 0)
  assert.equal(await reviewCard.getByText("CampusIQ can't calculate this curve rule automatically").count(), 0)
  // no inline finding on any rule card anymore
  assert.equal(await page.locator('.grade-rule-card .grade-inline-finding').count(), 0)
  // the "Ignore this rule for What-If calculations" button is gone
  assert.equal(await page.getByRole('button', { name: 'Ignore this rule for What-If calculations' }).count(), 0)

  // --- the grading breakdown no longer shows a per-category assessment
  //     count: it was never a blocker and it's meaningless to a student
  //     entering one average per category ---
  const breakdown = page.locator('[aria-label="Grading breakdown"]')
  await breakdown.waitFor()
  assert.equal(await breakdown.getByText('Number of assessments: Unknown').count(), 0)
  assert.equal(await breakdown.getByText(/\d+ assessments/).count(), 0)

  // --- overlapping_grade_thresholds is NOT reclassified: it still shows in
  //     the General section at the top of the review card, with the real
  //     letters/ranges ---
  const general = page.locator('.grade-inline-findings--general')
  await general.getByText('Letter grades B and B+ have overlapping cutoffs: B is 80–89, B+ is 85–92.').waitFor()

  // --- dismiss is session-only: dismissing the threshold finding hides it
  //     immediately, with no network call, and it comes back on reopen ---
  const thresholdFinding = general.locator('.grade-inline-finding', { hasText: 'overlapping cutoffs' })
  await thresholdFinding.getByRole('button', { name: 'Dismiss this finding' }).click()
  assert.equal(await general.getByText('overlapping cutoffs').count(), 0)

  await page.getByRole('button', { name: '← Back to your calculators' }).click()
  await page.locator('.grade-profile-row-button', { hasText: 'PHYS 207' }).click()
  await page.getByRole('heading', { name: 'Needs your review' }).waitFor()
  // reopening re-fetched the same findings and dismissal did not persist
  await page.locator('.grade-inline-findings--general').getByText('overlapping cutoffs').waitFor()

  // --- confirm straight from review; rules no longer gate calculator_ready ---
  await page.getByRole('button', { name: 'Confirm' }).click()

  // --- grade entry ---
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()

  // --- Professor's rules panel: persistent beside the calculator, fed
  //     from the grade model's rules[] (not findings). Every informational
  //     rule type renders with its label, text and page provenance; the
  //     deterministic replacement rule does NOT appear here; there is no
  //     dismiss / ignore control. ---
  const rulesPanel = page.locator('[data-testid="professors-rules"]')
  await rulesPanel.getByRole('heading', { name: "Professor's rules" }).waitFor()
  await rulesPanel.getByText('Grades may be curved upward.').waitFor()
  await rulesPanel.getByText('No late homework will be accepted.').waitFor()
  await rulesPanel.getByText('Makeup exams require a documented, university-excused absence.').waitFor()
  await rulesPanel.getByText('Curve', { exact: true }).waitFor()
  await rulesPanel.getByText('Late work', { exact: true }).waitFor()
  await rulesPanel.getByText('Makeup work', { exact: true }).waitFor()
  await rulesPanel.getByText('Source: page 3').waitFor()
  await rulesPanel.getByText('Source: page 4').waitFor()
  assert.equal(await rulesPanel.getByText('Score replacement').count(), 0, 'deterministic replacement rule must not appear in Professor\'s rules')
  assert.equal(await rulesPanel.getByText(/replaces Midterm/).count(), 0)
  assert.equal(await rulesPanel.getByRole('button').count(), 0, 'Professor\'s rules panel has no dismiss / ignore control')

  await page.fill('#actual-category\\:Mid-term\\ Exam', '78')
  await page.fill('#actual-category\\:Lecture\\ Quizzes', '92')
  await page.fill('#actual-category\\:Recitation\\ Quizzes', '88')
  await page.getByRole('button', { name: 'Calculate' }).click()

  await page.getByText('81.4%').waitFor()
  await page.getByText('Based on 50% of the course completed').waitFor()

  // --- Save grades: the per-category averages the student typed are what
  //     gets persisted as category_scores[].actual_score (no per-assessment
  //     breakdown required) ---
  await page.getByRole('button', { name: 'Save grades' }).click()
  await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'))
  assert.ok(capturedGradeStateBody, 'Save grades sent a grade-state PUT')
  assert.deepEqual(
    [...capturedGradeStateBody.category_scores].sort((a, b) => a.category_name.localeCompare(b.category_name)),
    [
      { category_name: 'Lecture Quizzes', actual_score: 92 },
      { category_name: 'Mid-term Exam', actual_score: 78 },
      { category_name: 'Recitation Quizzes', actual_score: 88 },
    ],
  )
  assert.deepEqual(capturedGradeStateBody.assessment_scores, [])

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

test('Grade Calculator: remove a calculator from the list (confirm-gated soft delete)', { timeout: 30_000 }, async (t) => {
  const planning = planningRoutes({ terms: [] })
  const PROFILE = {
    id: PROFILE_ID, institution: 'tamu', course_code: 'ECEN 248', term: 'Fall 2026', section: '501',
    review_state: 'needs_review', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    calculator_ready: false, current_grade: null,
  }
  let listRows = [PROFILE]
  let deleteCount = 0

  const apiPlugin = {
    name: 'grade-calculator-remove',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction') return json(response, 404, { detail: 'Not found.' })
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return json(response, 404, { detail: 'Not found.' })
        if (path === '/api/v2/student/me/syllabus-grade-profiles' && request.method === 'GET') {
          return json(response, 200, { syllabus_grade_profiles: listRows })
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && request.method === 'DELETE') {
          deleteCount += 1
          listRows = []
          return json(response, 200, { removed: PROFILE_ID })
        }
        next()
      })
    },
  }
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-grade-calculator-remove', import.meta.url).pathname,
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

  const row = page.locator('.grade-profile-row', { hasText: 'ECEN 248' })
  await row.waitFor()
  const removeButton = row.getByRole('button', { name: /Remove grade calculator for ECEN 248/ })

  // --- cancelling the confirm does nothing ---
  page.once('dialog', (d) => d.dismiss())
  await removeButton.click()
  await page.waitForTimeout(100)
  assert.equal(deleteCount, 0, 'dismissing the confirm must not call DELETE')
  await row.waitFor()

  // --- accepting the confirm removes the row ---
  page.once('dialog', (d) => {
    assert.match(d.message(), /Remove the grade calculator for ECEN 248\?/)
    d.accept()
  })
  await removeButton.click()

  await page.locator('.grade-profile-row', { hasText: 'ECEN 248' }).waitFor({ state: 'detached' })
  assert.equal(deleteCount, 1, 'accepting the confirm calls DELETE exactly once')
  await page.getByText('See what you need to reach your target grade').waitFor()
})

// --- cutoff-overlap clarifying questions -----------------------------------------

const CUTOFF_MODEL = {
  ...EXTRACTED_MODEL,
  grade_thresholds: [
    { letter: 'A', minimum: 91, maximum: 100, evidence: { page: 2, text: 'A: 91-100', confidence: 1.0 } },
    { letter: 'B', minimum: 80, maximum: 90, evidence: { page: 2, text: 'B: 80-90', confidence: 1.0 } },
    { letter: 'C', minimum: 70, maximum: 80, evidence: { page: 2, text: 'C: 70-80', confidence: 1.0 } },
  ],
  rules: [],
  warnings: [],
}

const RECONCILIATION_BC_OVERLAP = {
  status: 'needs_student_review',
  findings: [
    { code: 'overlapping_grade_thresholds', severity: 'error', message: "thresholds 'B' (80-90) and 'C' (70-80) overlap", field: 'B,C' },
  ],
  evidence_coverage: { total_claims: 5, supported_claims: 5, coverage_ratio: 1, unsupported_claims: [] },
}
const RESOLUTION_BC = { schema_version: '1', resolved: [{ letters: ['B', 'C'], boundary: 80, winner: 'B', loser: 'C' }], unresolved: [] }

// Boot the panel with a middleware `handle(path, method, request, response)`
// that returns true when it answered. Navigates into the single profile.
async function mountCutoffPanel(t, cacheKey, handle) {
  const planning = planningRoutes({ terms: [] })
  const apiPlugin = {
    name: cacheKey,
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction') return json(response, 404, { detail: 'Not found.' })
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return json(response, 404, { detail: 'Not found.' })
        if (path === '/api/v2/student/me/syllabus-grade-profiles' && request.method === 'GET') {
          return json(response, 200, { syllabus_grade_profiles: [{ id: PROFILE_ID, institution: 'tamu', course_code: 'PHYS 207', term: 'Fall 2026', section: '529', review_state: 'needs_review', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', calculator_ready: false, current_grade: null }] })
        }
        if (await handle(path, request.method, request, response)) return undefined
        next()
      })
    },
  }
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL(`../node_modules/.vite-${cacheKey}`, import.meta.url).pathname,
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
  await page.locator('.grade-profile-row-button', { hasText: 'PHYS 207' }).click()
  return page
}

test('Grade Calculator: cutoff-overlap question — propose, confirm, unblock', { timeout: 45_000 }, async (t) => {
  let confirmed = false
  let correctionBody = null
  const page = await mountCutoffPanel(t, 'grade-calculator-cutoff-confirm', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: CUTOFF_MODEL, reconciliation: RECONCILIATION_BC_OVERLAP, cutoff_overlap_resolution: RESOLUTION_BC }))
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      correctionBody = JSON.parse(await readBody(request))
      confirmed = true
      json(response, 200, detail({
        extracted_grade_model: CUTOFF_MODEL,
        confirmed_grade_model: CUTOFF_MODEL,
        calculator_ready: true,
        review_state: 'needs_review',
        reconciliation: RECONCILIATION_BC_OVERLAP,
        confirmed_reconciliation: RECONCILIATION_ACCEPTED,
        corrections: correctionBody.corrections,
        clarifying_answers: { 'cutoff_overlap:B,C': { answer: 'confirm_default', boundary: 80, winner: 'B', loser: 'C' } },
        cutoff_overlap_resolution: RESOLUTION_BC,
      }))
      return true
    }
    return false
  })

  // the question renders with ranges joined from grade_thresholds
  const question = page.locator('.grade-cutoff-question[data-cutoff-pair="B,C"]')
  await question.getByText(/Your syllabus lists B as 80–90 and C as 70–80/).waitFor()
  await question.getByText(/80 is B, not C\. Sound right\?/).waitFor()
  // the raw overlapping_grade_thresholds finding is NOT also shown for a resolvable pair
  assert.equal(await page.locator('.grade-inline-findings--general').getByText(/overlapping cutoffs/).count(), 0)

  await question.getByRole('button', { name: "Yes, that's right" }).click()
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()

  assert.ok(confirmed)
  assert.deepEqual(correctionBody.corrections, [
    { target_type: 'threshold', operation: 'resolve_cutoff_overlap', threshold_letter: 'B' },
  ])
  // question gone once answered
  assert.equal(await page.locator('.grade-cutoff-question[data-cutoff-pair="B,C"]').count(), 0)
})

test('Grade Calculator: unresolved overlap is not an auto-question; manual editor for both entry points', { timeout: 45_000 }, async (t) => {
  let corrections = []
  const RESOLUTION_MIXED = {
    schema_version: '1',
    resolved: [{ letters: ['B', 'C'], boundary: 80, winner: 'B', loser: 'C' }],
    unresolved: [{ letters: ['A', 'C'], reason: 'non_adjacent_letters' }],
  }
  const RECON_MIXED = {
    status: 'needs_student_review',
    findings: [
      { code: 'overlapping_grade_thresholds', severity: 'error', message: "thresholds 'B' (80-90) and 'C' (70-80) overlap", field: 'B,C' },
      { code: 'overlapping_grade_thresholds', severity: 'error', message: "thresholds 'A' (75-100) and 'C' (70-80) overlap", field: 'A,C' },
    ],
    evidence_coverage: { total_claims: 5, supported_claims: 5, coverage_ratio: 1, unsupported_claims: [] },
  }
  const model = { ...CUTOFF_MODEL, grade_thresholds: [
    { letter: 'A', minimum: 75, maximum: 100, evidence: null },
    { letter: 'B', minimum: 80, maximum: 90, evidence: null },
    { letter: 'C', minimum: 70, maximum: 80, evidence: null },
  ] }
  const page = await mountCutoffPanel(t, 'grade-calculator-cutoff-manual', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: model, reconciliation: RECON_MIXED, cutoff_overlap_resolution: RESOLUTION_MIXED }))
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      corrections = JSON.parse(await readBody(request)).corrections
      json(response, 200, detail({
        extracted_grade_model: model, confirmed_grade_model: model, calculator_ready: true,
        reconciliation: RECON_MIXED, confirmed_reconciliation: RECONCILIATION_ACCEPTED,
        corrections, cutoff_overlap_resolution: RESOLUTION_MIXED,
      }))
      return true
    }
    return false
  })

  // A/C is unresolved: no "Sound right?" proposal, but its raw finding stays,
  // and there's a "Set the cutoffs" action.
  const unresolved = page.locator('.grade-cutoff-question[data-cutoff-pair="A,C"]')
  await unresolved.getByText(/cutoffs for A and C overlap and CampusIQ can't pick a safe default/).waitFor()
  assert.equal(await unresolved.getByText(/Sound right\?/).count(), 0)
  await page.locator('.grade-inline-findings--general').getByText("Letter grades A and C have overlapping cutoffs: A is 75–100, C is 70–80.").waitFor()

  // "No, let me set it myself" on the resolvable B/C question opens the editor
  await page.locator('.grade-cutoff-question[data-cutoff-pair="B,C"]').getByRole('button', { name: 'No, let me set it myself' }).click()
  await page.locator('[data-testid="cutoff-manual-editor"][data-cutoff-pair="B,C"]').waitFor()
  await page.fill('#cutoff-C-max', '79')
  await page.getByRole('button', { name: 'Save cutoffs' }).click()
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()
  assert.deepEqual(corrections, [{ target_type: 'threshold', operation: 'set_maximum', threshold_letter: 'C', value: 79 }])
})

test('Grade Calculator: an answered cutoff shows resolved and does not re-ask on reload', { timeout: 45_000 }, async (t) => {
  // Answered, but still in review because one unrelated finding blocks -- so
  // the clarifying-questions section stays on screen.
  const answered = detail({
    extracted_grade_model: CUTOFF_MODEL,
    reconciliation: RECONCILIATION_BC_OVERLAP,
    confirmed_grade_model: CUTOFF_MODEL,
    calculator_ready: false,
    corrections: [{ target_type: 'threshold', operation: 'resolve_cutoff_overlap', threshold_letter: 'B' }],
    clarifying_answers: { 'cutoff_overlap:B,C': { answer: 'confirm_default', boundary: 80, winner: 'B', loser: 'C' } },
    cutoff_overlap_resolution: RESOLUTION_BC,
    confirmed_reconciliation: {
      status: 'needs_student_review',
      findings: [{ code: 'grading_method_unknown', severity: 'warning', message: 'x', field: 'grading_method' }],
      evidence_coverage: RECONCILIATION_ACCEPTED.evidence_coverage,
    },
  })

  const page = await mountCutoffPanel(t, 'grade-calculator-cutoff-answered', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, answered)
      return true
    }
    return false
  })

  await page.locator('.grade-cutoff-resolved[data-cutoff-pair="B,C"]').getByText('80 counts as B, not C').waitFor()
  assert.equal(await page.locator('.grade-cutoff-question[data-cutoff-pair="B,C"]').count(), 0)

  // navigate away and back — still resolved, still no question
  await page.getByRole('button', { name: '← Back to your calculators' }).click()
  await page.locator('.grade-profile-row-button', { hasText: 'PHYS 207' }).click()
  await page.locator('.grade-cutoff-resolved[data-cutoff-pair="B,C"]').waitFor()
  assert.equal(await page.locator('.grade-cutoff-question[data-cutoff-pair="B,C"]').count(), 0)
})

test('Grade Calculator: non-blocking informational findings are filtered from the review list', { timeout: 45_000 }, async (t) => {
  const model = { ...EXTRACTED_MODEL, grade_thresholds: [], rules: [], warnings: [] }
  const recon = {
    status: 'needs_student_review',
    findings: [
      // non-blocking, no correction path -> must NOT show in the review list
      { code: 'unknown_assessment_count', severity: 'warning', message: 'The exact number of Lecture Quizzes is unknown.', field: 'Lecture Quizzes' },
      // genuinely blocking -> must still show
      { code: 'grading_method_unknown', severity: 'warning', message: 'grading_method could not be determined from the syllabus', field: 'grading_method' },
    ],
    evidence_coverage: { total_claims: 4, supported_claims: 4, coverage_ratio: 1, unsupported_claims: [] },
  }
  const page = await mountCutoffPanel(t, 'grade-calculator-nonblocking-filter', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: model, reconciliation: recon }))
      return true
    }
    return false
  })

  await page.getByRole('heading', { name: 'Needs your review' }).waitFor()
  // the blocking finding is still shown, so the review list isn't just empty
  assert.ok((await page.locator('[data-finding-code="grading_method_unknown"]').count()) >= 1)
  // unknown_assessment_count is filtered out entirely
  assert.equal(await page.locator('[data-finding-code="unknown_assessment_count"]').count(), 0)
  assert.equal(await page.getByText("doesn't say exactly how many assessments are in this category").count(), 0)
})
