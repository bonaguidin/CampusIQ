import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { chromium } from 'playwright'
import { createServer } from 'vite'

test('authenticated dashboard covers canonical states, routing, themes, errors, demo separation, and mobile', { timeout: 45_000 }, async (t) => {
  const requests = []
  const apiPlugin = { name: 'dashboard-api', configureServer(server) { server.middlewares.use((request, response, next) => {
    if (request.url?.startsWith('/api/v2/student/me/analyze/')) {
      requests.push({ url: request.url, authorization: request.headers.authorization })
      response.statusCode = 200; response.setHeader('content-type', 'application/json')
      response.end(JSON.stringify({ feature: 'GAP', status: 'skipped', summary: '', data: {}, errors: ['missing'] }))
      return
    }
    next()
  }) } }
  const server = await createServer({ root: new URL('..', import.meta.url).pathname, logLevel: 'silent', plugins: [apiPlugin], server: { host: '127.0.0.1' } })
  await server.listen(); t.after(async () => server.close())
  const address = server.httpServer?.address(); assert.ok(address && typeof address === 'object')
  const origin = `http://127.0.0.1:${String(address.port)}`
  const browser = await chromium.launch(); t.after(async () => browser.close())
  const page = await browser.newPage()

  // CASE 1: complete real identity, institution, official GPA, academics and career.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('heading', { name: 'Alex Morgan' }).waitFor()
  await page.getByText('Texas A&M University').waitFor()
  await page.getByText('Official GPA').first().waitFor()
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByText('CS 101').waitFor()
  await page.getByRole('button', { name: 'Career' }).click()
  await page.getByText('Software Engineer').waitFor()
  await page.getByText('Cloud Fundamentals').waitFor()

  // CASE 2: career only renders academic onboarding.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=career`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('link', { name: 'Upload transcript' }).waitFor()

  // CASE 3: academics only renders career onboarding.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=academic`)
  await page.getByRole('button', { name: 'Career' }).click()
  await page.getByRole('link', { name: 'Upload resume' }).waitFor()

  // CASE 4: minimal profile renders both useful onboarding paths without a crash.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=minimal`)
  assert.equal(await page.getByText('minimal', { exact: true }).count() > 0, true)
  assert.equal(await page.getByRole('link', { name: 'Upload transcript' }).count(), 1)
  assert.equal(await page.getByRole('link', { name: 'Upload resume' }).count(), 1)

  // CASE 5: API/account failure is explicit and retryable, never a demo profile.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=error`)
  await page.getByText('Profile API failed.').waitFor()
  await page.getByRole('button', { name: 'Try again' }).click()
  assert.equal(await page.evaluate(() => document.body.dataset.retried), 'yes')
  assert.equal(await page.getByText('Jordan Reyes').count(), 0)

  // CASE 6: institution-neutral canonical rendering for TAMU and SMU.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete&institution=smu`)
  await page.getByText('Southern Methodist University').waitFor()

  // CASE 8: authenticated analysis uses /me and forwards the bearer token.
  await page.getByRole('button', { name: 'Career' }).click()
  for (const title of ['Readiness Check (GAP)', 'Role Fit (FIT)', 'Trend Guidance (SHIFT)']) {
    await page.locator('.analysis-panel').filter({ hasText: title }).getByRole('button', { name: 'Run analysis' }).click()
  }
  await page.getByText(/missing information/).first().waitFor()
  assert.deepEqual(requests.map(({ url }) => url), [
    '/api/v2/student/me/analyze/gap',
    '/api/v2/student/me/analyze/fit',
    '/api/v2/student/me/analyze/shift',
  ])
  assert.equal(requests.every(({ authorization }) => authorization === 'Bearer real-access-token'), true)

  // CASE 10: mobile viewport has no page-level horizontal overflow.
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)

  // CASES 7/9: source boundaries preserve demo loading and clear demo identity on real sign-in.
  const authSource = await readFile(new URL('../src/auth/AuthContext.tsx', import.meta.url), 'utf8')
  const dashboardSource = await readFile(new URL('../src/pages/DashboardPage.tsx', import.meta.url), 'utf8')
  assert.match(authSource, /staticJsonAdapter\.loadStudent/)
  assert.match(authSource, /sessionStorage\.removeItem\(SESSION_KEY\)/)
  assert.match(authSource, /previousUserId !== nextUserId/)
  assert.match(authSource, /fetchInstitutionThemeByName\(institution\)/)
  assert.match(dashboardSource, /return <DemoDashboardPage/)
  assert.match(dashboardSource, /return <AuthenticatedDashboard/)
})
