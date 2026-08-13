// The redesigned Career profile, driven through a real browser.
//
// The view-model tests already pin what the data does; this pins what the page
// does with it -- collapse and expansion, keyboard reachability, the absence
// treatments, theming, and the layouts at three widths.

import assert from 'node:assert/strict'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'

const LONG_HEAD = 'Built a convolutional model for ECG arrhythmia classification on the MIT-BIH database'
const LONG_TAIL = 'per-class error analysis across the five AAMI categories.'

async function startServer(t) {
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-career-profile', import.meta.url).pathname,
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  return `http://127.0.0.1:${String(address.port)}`
}

/** Opens the dashboard on the Career tab for a given fixture. */
async function openCareer(page, origin, query) {
  await page.goto(`${origin}/authenticated-dashboard-preview.html?${query}`)
  await page.getByRole('button', { name: 'Career' }).click()
  await page.locator('.cp').waitFor()
}

test('career profile: summary, direction, skills collapse, timeline, certifications, projects', { timeout: 45_000 }, async (t) => {
  const origin = await startServer(t)
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
  await openCareer(page, origin, 'mode=complete&career=rich')

  // ── CASE C1 / C2: the summary reports canonical values and real counts.
  await page.locator('.cp-summary-roles').getByText('AI Engineer').waitFor()
  const metrics = await page.locator('.cp-metric').evaluateAll((nodes) =>
    nodes.map((n) => [n.querySelector('.cp-metric-label').textContent, n.querySelector('.cp-metric-value').textContent]))
  assert.deepEqual(metrics, [['Skills', '24'], ['Experiences', '3'], ['Projects', '2'], ['Certifications', '2']])
  // Counts match what is actually rendered further down the page.
  assert.equal(await page.locator('.cp-timeline .cp-tl-item').count(), 3)
  assert.equal(await page.locator('.cp-project').count(), 2)
  assert.equal(await page.locator('.cp-cert').count(), 2)

  // CASE C4: no invented readiness figure anywhere on the Career surface.
  const careerText = await page.locator('.cp').innerText()
  assert.equal(/\d+\s?%/.test(careerText), false, 'a percentage appeared on the Career page')
  assert.equal(/readiness score|match score|ranked/i.test(careerText), false)

  // ── CASE S1 / S2: skills are separate labels, not a comma wall, and a big
  // set starts collapsed.
  assert.equal(careerText.includes('Python, PyTorch'), false, 'skills rendered as a comma wall')
  // Scoped to the skills section throughout: experience and projects render
  // chips of their own, and counting all of them together would compare two
  // different things across the collapse.
  const shown = await page.locator('.cp-skills .cp-chip').count()
  assert.ok(shown < 24, `expected a collapsed subset, saw ${String(shown)} skill chips`)
  await page.locator('.cp-skills .cp-chip').getByText('Python', { exact: true }).waitFor()

  // Chips are labels, not fake buttons: nothing happens when you click a
  // skill, so none of them should be in the tab order or announced as one.
  const chipTags = await page.locator('.cp-skills .cp-chip').evaluateAll((nodes) => [...new Set(nodes.map((n) => n.tagName))])
  assert.deepEqual(chipTags, ['LI'], 'skill chips must not be buttons')

  // ── CASE S3 / S4 / S5: expansion is a real, keyboard-operable button.
  const expander = page.locator('.cp-skills .cp-more')
  // The label states the hidden count once, derived from the list. "Show all 24
  // skills +6" said the same thing twice; the number that decides whether to
  // click is how many are missing.
  assert.equal(await expander.innerText(), `Show ${String(24 - shown)} more`)
  assert.equal(await expander.getAttribute('aria-expanded'), 'false')
  await expander.focus()
  await page.keyboard.press('Enter')
  assert.equal(await expander.getAttribute('aria-expanded'), 'true')
  assert.equal(await page.locator('.cp-skills .cp-chip').count(), 24, 'expanding must reveal every skill')
  await page.locator('.cp-skills .cp-chip').getByText('Vector Databases').waitFor()
  assert.equal(await expander.innerText(), 'Show less')
  await page.keyboard.press('Enter')
  assert.equal(await expander.getAttribute('aria-expanded'), 'false')
  assert.equal(await page.locator('.cp-skills .cp-chip').count(), shown, 'Show less must restore the compact state')

  // Skills group by the canonical split only -- and both headings are present
  // in BOTH states, so expanding does not appear to add a category. textContent
  // rather than innerText: the headings are uppercased by CSS, and asserting on
  // the rendered casing would pin a style choice instead of the copy.
  const subheads = () => page.locator('.cp-skills .cp-subhead').evaluateAll((n) => n.map((e) => e.textContent))
  assert.deepEqual(await subheads(), ['Technical', 'Soft skills'], 'collapsed state dropped a group heading')
  await expander.click()
  assert.deepEqual(await subheads(), ['Technical', 'Soft skills'])
  await expander.click()

  // ── CASE E1 / E2 / E3: order, hierarchy, and no invented dates.
  const orgs = await page.locator('.cp-tl-org').allInnerTexts()
  assert.deepEqual(orgs, ['Littlebird', 'Aggie Data Science Club', '10Spy'])
  const second = page.locator('.cp-tl-item').nth(1)
  assert.equal(await second.locator('.cp-tl-role').innerText(), 'Co-Project Manager')
  assert.equal(await second.locator('.cp-tl-meta').count(), 0, 'a role with no duration must show no date line')
  const timelineText = await page.locator('.cp-timeline').innerText()
  for (const invented of ['Unknown', 'N/A', 'Dates not']) {
    assert.equal(timelineText.includes(invented), false, `"${invented}" was invented for a missing field`)
  }

  // ── CERT1 / CERT2: real columns, missing ones simply absent.
  // The issuer lives on the meta line; the name also contains "NVIDIA", so
  // the meta element is named rather than matched by text alone.
  assert.equal(await page.locator('.cp-cert').filter({ hasText: 'NVIDIA Certified Associate' }).locator('.cp-cert-meta').innerText(), 'NVIDIA · 2025')
  const pending = page.locator('.cp-cert').filter({ hasText: 'AWS Cloud Practitioner' })
  assert.equal(await pending.locator('.cp-cert-status').innerText(), 'In progress')
  assert.equal(await pending.locator('.cp-cert-meta').count(), 0, 'no issuer/date line when both are missing')

  // ── CASE P1 / P2 / P3 / P4: preview, full original, collapse, aria.
  const project = page.locator('.cp-project').filter({ hasText: 'Arrhythmia' })
  const body = project.locator('.cp-project-body')
  const previewText = await body.innerText()
  assert.ok(previewText.startsWith(LONG_HEAD), 'the preview must be a prefix of the original')
  assert.ok(previewText.endsWith('…'), 'a truncated preview must be marked as such')
  assert.equal(previewText.includes(LONG_TAIL), false, 'the full description must start hidden')

  const details = project.locator('.cp-more')
  assert.equal(await details.innerText(), 'View details')
  assert.equal(await details.getAttribute('aria-expanded'), 'false')
  await details.click()
  assert.equal(await details.getAttribute('aria-expanded'), 'true')
  const fullText = await body.innerText()
  assert.ok(fullText.includes(LONG_TAIL), 'View details must reveal the full original description')
  assert.equal(fullText.endsWith('…'), false)
  await details.click()
  assert.equal(await details.getAttribute('aria-expanded'), 'false')
  assert.equal(await body.innerText(), previewText, 'collapse must restore the preview')

  // CASE P6: a short project with no tools renders cleanly and offers no
  // "View details" for text that is already complete.
  const short = page.locator('.cp-project').filter({ hasText: 'Campus Scheduler' })
  assert.equal(await short.locator('.cp-chip').count(), 0)
  assert.equal(await short.locator('.cp-more').count(), 0)
  // CASE P5: real tools show; nothing was parsed out of prose.
  await project.locator('.cp-chip').getByText('PyTorch').waitFor()

  // ── Institution theming reaches the accents, and only through tokens.
  const accentOf = async (rgb) => page.evaluate((value) => {
    document.documentElement.style.setProperty('--accent-text-rgb', value)
    return {
      marker: getComputedStyle(document.querySelector('.cp-tl-marker')).backgroundColor,
      more: getComputedStyle(document.querySelector('.cp-more')).color,
    }
  }, rgb)
  assert.deepEqual(await accentOf('80 0 0'), { marker: 'rgb(80, 0, 0)', more: 'rgb(80, 0, 0)' })
  assert.deepEqual(await accentOf('0 51 160'), { marker: 'rgb(0, 51, 160)', more: 'rgb(0, 51, 160)' })
  await page.evaluate(() => { document.documentElement.style.removeProperty('--accent-text-rgb') })

  // Restraint: the accent is an accent. Chips and card surfaces stay neutral.
  const chipBg = await page.locator('.cp-skills .cp-chip').first().evaluate((el) => getComputedStyle(el).backgroundColor)
  assert.equal(chipBg, 'rgb(247, 247, 247)', 'skill chips must not be filled with the institution colour')
})

test('career profile: absences collapse and never become empty rectangles', { timeout: 45_000 }, async (t) => {
  const origin = await startServer(t)
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })

  // ── A confirmed profile with nothing in it.
  await openCareer(page, origin, 'mode=complete&career=bare')
  // Career direction speaks field by field. The old single "No career
  // direction yet." covered all four at once, which is exactly why a student
  // with interests and no target roles was told nothing about the roles.
  await page.getByText('No target roles added yet.').waitFor()
  await page.getByText('No interests added yet.').waitFor()
  assert.equal(await page.getByText('No career direction yet.').count(), 0)
  await page.getByText('No skills confirmed yet.').waitFor()
  await page.getByText('No experience confirmed yet.').waitFor()
  await page.getByText('No certifications yet.').waitFor()
  await page.getByText('No projects yet.').waitFor()

  // The old page printed three negative sentences inside one full-height card.
  assert.equal(await page.getByText('No target roles provided.').count(), 0)
  assert.equal(await page.getByText('No interests provided.').count(), 0)
  assert.equal(await page.getByText('No career goal provided.').count(), 0)

  // Every absence is a line, not a rectangle. 120px is generously above the
  // two/three lines these render and far below the old card heights.
  const heights = await page.locator('.cp-absent').evaluateAll((nodes) =>
    nodes.map((n) => Math.round(n.getBoundingClientRect().height)))
  assert.ok(heights.length >= 5, `expected an absence per empty section, saw ${String(heights.length)}`)
  assert.ok(Math.max(...heights) < 120, `an absence reserved ${String(Math.max(...heights))}px`)

  // Counts of zero are not printed as a "0" badge beside the heading.
  assert.equal(await page.locator('.cp-section-count').count(), 0)

  // The only offered action is a route that genuinely exists -- no dead button.
  // The route is offered ONCE, not beside every gap: confirming a resume
  // rewrites all five sections at the same time, so repeating it would offer
  // the same single action five times.
  assert.equal(await page.locator('.cp-absent-link').count(), 1, 'the resume route must appear once per page')
  assert.equal(await page.locator('.cp-absent-link').getAttribute('href'), '/resume')
  assert.equal(await page.locator('.cp button:not(.cp-more)').count(), 0, 'no non-functional buttons')

  // ── The awkward middle: entries but no direction, and no certifications.
  await openCareer(page, origin, 'mode=complete&career=partial')
  await page.getByText('No target roles added yet.').waitFor()
  await page.getByText('No interests added yet.').waitFor()
  await page.getByText('No certifications yet.').waitFor()
  // The summary headline is a SEPARATE element from the direction field's
  // absence, and deliberately worded differently -- one orients, the other
  // states a gap. Both must survive, and neither may stand in for the other.
  await page.locator('.cp-summary-roles--absent').getByText('No target roles yet').waitFor()
  assert.equal(await page.locator('.cp-summary-roles--absent').count(), 1)
  assert.equal(await page.locator('.cp-direction .cp-absent').count(), 2)
  // What IS there still renders in full.
  assert.equal(await page.locator('.cp-timeline .cp-tl-item').count(), 3)
  assert.equal(await page.locator('.cp-project').count(), 2)
  // And the summary still counts only what exists.
  const values = await page.locator('.cp-metric-value').allInnerTexts()
  assert.deepEqual(values, ['22', '3', '2', '0'])

  // ── THE REGRESSION: interests present, target roles absent. Under the old
  // section-level gate this profile "had a career direction", so the page
  // rendered the interests and stayed silent about the roles -- the field
  // every analysis requires. Each field must now answer for itself.
  await openCareer(page, origin, 'mode=complete&career=lopsided')
  await page.locator('.cp-direction').getByText('Physical AI · Robotics').waitFor()
  await page.getByText('No target roles added yet.').waitFor()
  assert.equal(await page.locator('.cp-direction .cp-absent').count(), 1,
    'exactly the empty field may render an absence')
  // The one action on the page still appears once, and still beside the gap
  // that has a consequence worth stating.
  assert.equal(await page.locator('.cp-absent-link').count(), 1)
  // 'not_sure' is a real answer -- asked, does not know -- and must read as
  // one rather than borrowing the never-asked absence's label.
  await page.locator('.cp-details').getByText('Not sure').waitFor()
  assert.equal(await page.locator('.cp-details .cp-detail-value--absent').count(), 0,
    'this fixture sets every detail, so none may render as absent')
})

// The three facts guidance is calibrated against had no representation at all
// in the authenticated app: a student could be told an analysis needed their
// expected graduation on a page that never showed what it held. These rows are
// read-only in this step -- editing arrives later, and until it does nothing
// here may imply an ability the page does not have.
test('career profile: details rows report graduation, majors and AI comfort', { timeout: 45_000 }, async (t) => {
  const origin = await startServer(t)
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })

  // ── Every value present, and the student is switching majors.
  await openCareer(page, origin, 'mode=complete&career=rich')
  const details = page.locator('.cp-details')
  await details.getByText('Spring 2028').waitFor()
  await details.getByText('Computer Science', { exact: true }).waitFor()
  await details.getByText('Switching to Data Science').waitFor()
  // The stored column is 'moderate'; a machine token is not English.
  await details.getByText('Moderate').waitFor()
  assert.equal((await details.innerText()).includes('moderate'), false, 'a raw enum token reached the page')
  assert.equal(await details.locator('.cp-detail-value--absent').count(), 0)

  // Read-only in this step: no control of any kind inside the block.
  assert.equal(await details.locator('button, a, input, select').count(), 0, 'a details row became interactive')

  // ── Not switching. The sentinel is a stored answer, never a typed major,
  // so it is reported as the answer it is and never echoed back verbatim.
  await openCareer(page, origin, 'mode=complete&career=partial')
  await page.locator('.cp-details').getByText('Not switching majors').waitFor()
  assert.equal((await page.locator('.cp').innerText()).includes('N/A'), false, 'the sentinel was printed as a major')

  // ── Nothing set. An absence says so rather than filling with a dash.
  await openCareer(page, origin, 'mode=complete&career=bare')
  const bare = page.locator('.cp-details')
  assert.equal(await bare.locator('.cp-detail-value--absent').count(), 3, 'every unset row must state its absence')
  assert.equal(await bare.getByText('Not set').count(), 2)
  // Null AI comfort means never asked -- which is not the same answer as the
  // selectable 'Not sure', and must not borrow its label.
  await bare.getByText('Not answered').waitFor()
  assert.equal(await bare.getByText('Not sure').count(), 0)
  // No note floats beside a value that does not exist.
  assert.equal(await bare.locator('.cp-detail-note').count(), 0)
})

test('career profile: responsive at 1280, 834 and 390 with no overflow', { timeout: 45_000 }, async (t) => {
  const origin = await startServer(t)
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
  await openCareer(page, origin, 'mode=complete&career=rich')

  for (const width of [1280, 834, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.waitForTimeout(150)

    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
      `page overflowed at ${String(width)}px`)

    // No element inside the Career section may exceed its own container.
    const overflowing = await page.locator('.cp').evaluate((root) =>
      [...root.querySelectorAll('*')].filter((el) => el.scrollWidth > el.clientWidth + 1).map((el) => el.className).slice(0, 5))
    assert.deepEqual(overflowing, [], `overflowing elements at ${String(width)}px`)

    // The unequal desktop split must collapse rather than become two strips.
    const columns = await page.locator('.cp-grid--split').first().evaluate((el) => getComputedStyle(el).gridTemplateColumns)
    if (width <= 834) {
      assert.equal(columns.split(' ').length, 1, `columns did not stack at ${String(width)}px`)
    } else {
      assert.equal(columns.split(' ').length, 2, 'desktop must keep the unequal split')
      const [left, right] = columns.split(' ').map(parseFloat)
      assert.ok(right > left, 'skills column must be the wider one')
    }

    // The four summary metrics: a single row on wide layouts, a balanced 2x2 on
    // mobile. Asserted from laid-out geometry rather than the CSS rule, because
    // what was wrong before was the RESULT -- three fitted one row and
    // "Certifications" wrapped alone, which read as an accident.
    const rows = await page.locator('.cp-metric').evaluateAll((nodes) => {
      const tops = nodes.map((n) => Math.round(n.getBoundingClientRect().top))
      return [...new Set(tops)].sort((a, b) => a - b).map((top) => tops.filter((t) => t === top).length)
    })
    if (width <= 390) {
      assert.deepEqual(rows, [2, 2], `metrics must form a balanced 2x2 at ${String(width)}px, saw rows of ${JSON.stringify(rows)}`)
    } else {
      assert.deepEqual(rows, [4], `metrics must stay on one row at ${String(width)}px`)
    }

    // The timeline stays readable and the expander stays a usable target.
    assert.ok(await page.locator('.cp-tl-org').first().isVisible())
    const target = await page.locator('.cp-skills .cp-more').boundingBox()
    // WCAG 2.5.8 minimum target size.
    assert.ok(target.height >= 24, `expander is a ${String(target.height)}px target at ${String(width)}px`)
  }
})

test('career profile: reduced motion carries no information loss', { timeout: 45_000 }, async (t) => {
  const origin = await startServer(t)
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 }, reducedMotion: 'reduce' })
  await openCareer(page, origin, 'mode=complete&career=rich')

  // Nothing on the Career surface animates...
  const animating = await page.locator('.cp').evaluate((root) =>
    [root, ...root.querySelectorAll('*')].filter((el) => getComputedStyle(el).animationName !== 'none').length)
  assert.equal(animating, 0)

  // ...and every interaction still works and still reveals the same content.
  const project = page.locator('.cp-project').filter({ hasText: 'Arrhythmia' })
  await project.locator('.cp-more').click()
  assert.ok((await project.locator('.cp-project-body').innerText()).includes(LONG_TAIL))

  const expander = page.locator('.cp-skills .cp-more')
  await expander.click()
  assert.equal(await page.locator('.cp-skills .cp-chip').count(), 24)
})
