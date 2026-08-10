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

  const TAMU_ID = '75d68331-91d2-47e8-9671-2a3b065955d0'
  const SMU_ID = '6b180bbf-66d7-4aef-b8c6-2ae534c78e9a'
  const themes = {
    [TAMU_ID]: { brand_primary_hex: '#500000', brand_rail_hex: '#2B0B0B', brand_on_primary_hex: '#FFFFFF' },
    [SMU_ID]: { brand_primary_hex: '#0033A0', brand_rail_hex: '#171E2B', brand_on_primary_hex: '#FFFFFF' },
  }
  const themeRequests = []
  await page.route('**/rest/v1/institutions*', async (route) => {
    const url = new URL(route.request().url())
    themeRequests.push(url.search)
    const idFilter = url.searchParams.get('id')
    const nameFilter = url.searchParams.get('name')
    const id = idFilter?.replace(/^eq\./, '')
    const theme = id ? themes[id] : nameFilter === 'eq.Texas A&M University' ? themes[TAMU_ID] : null
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'application/vnd.pgrst.object+json' },
      body: JSON.stringify(theme),
    })
  })

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

  // CASE 6: canonical institution rendering for TAMU and SMU.
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
  assert.match(authSource, /fetchInstitutionThemeById\(institutionId\)/)
  assert.match(authSource, /fetchInstitutionThemeByName\(p\.student\.institution\)/)
  assert.match(dashboardSource, /return <DemoDashboardPage/)
  assert.match(dashboardSource, /return <AuthenticatedDashboard/)

  // Authenticated theme resolution is keyed only by the canonical ID. The
  // display-name variation deliberately never enters the lookup.
  const applyById = async (id) => page.evaluate(async (institutionId) => {
    const themeModule = await import('/src/lib/institutionTheme.ts')
    const theme = await themeModule.fetchInstitutionThemeById(institutionId)
    themeModule.applyInstitutionTheme(theme)
    const style = document.documentElement.style
    return {
      accent: style.getPropertyValue('--accent-rgb'),
      accentText: style.getPropertyValue('--accent-text-rgb'),
      onAccent: style.getPropertyValue('--on-accent-rgb'),
      rail: style.getPropertyValue('--rail-bg-rgb'),
    }
  }, id)

  assert.deepEqual(await applyById(TAMU_ID), {
    accent: '80 0 0', accentText: '68 0 0', onAccent: '255 255 255', rail: '43 11 11',
  })
  // Switching accounts replaces every institution token; TAMU values do not survive.
  assert.deepEqual(await applyById(SMU_ID), {
    accent: '0 51 160', accentText: '0 43 136', onAccent: '255 255 255', rail: '23 30 43',
  })
  assert.equal(themeRequests.some((query) => query.includes(`id=eq.${TAMU_ID}`)), true)
  assert.equal(themeRequests.some((query) => query.includes(`id=eq.${SMU_ID}`)), true)

  // Logout/reset clears inline values and exposes the neutral :root defaults.
  const cleared = await page.evaluate(async () => {
    const themeModule = await import('/src/lib/institutionTheme.ts')
    themeModule.clearInstitutionTheme()
    return {
      inlineAccent: document.documentElement.style.getPropertyValue('--accent-rgb'),
      computedAccent: getComputedStyle(document.documentElement).getPropertyValue('--accent-rgb').trim(),
    }
  })
  assert.deepEqual(cleared, { inlineAccent: '', computedAccent: '36 36 36' })

  // Demo compatibility remains the explicitly name-based path.
  const demoTheme = await page.evaluate(async () => {
    const themeModule = await import('/src/lib/institutionTheme.ts')
    return themeModule.fetchInstitutionThemeByName('Texas A&M University')
  })
  assert.deepEqual(demoTheme, themes[TAMU_ID])
  assert.equal(themeRequests.some((query) => query.includes('name=eq.Texas+A%26M+University')), true)
})
