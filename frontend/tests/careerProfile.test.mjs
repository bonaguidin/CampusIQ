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

async function startServer(t, plugins = []) {
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-career-profile', import.meta.url).pathname,
    logLevel: 'silent',
    plugins,
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  return `http://127.0.0.1:${String(address.port)}`
}

/**
 * Waits for the server to have recorded `count` PATCHes.
 *
 * The immediate-save field has no button to go quiet and no visible committed
 * state to wait on -- the preview's reload returns the same profile -- so the
 * request itself is the only honest signal that the save happened.
 */
async function waitForPatch(patches, count, timeout = 5000) {
  const deadline = Date.now() + timeout
  while (patches.length < count) {
    if (Date.now() > deadline) throw new Error(`expected ${String(count)} patches, saw ${String(patches.length)}`)
    await new Promise((resolve) => setTimeout(resolve, 25))
  }
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
  // Every button on this page must do something. The expanders always did;
  // the inline Edit controls are the new ones, and they are the ONLY other
  // kind allowed -- a button belonging to neither group is the "no dead
  // affordance" rule being broken again.
  const strayButtons = await page.locator('.cp button:not(.cp-more)').evaluateAll((nodes) =>
    nodes.filter((node) => !node.closest('.editable-section-actions')).map((node) => node.textContent))
  assert.deepEqual(strayButtons, [], 'a button in the career profile does nothing')

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
  // one rather than borrowing the never-asked absence's label. Scoped to the
  // value: the radio group repeats every option name beneath it.
  await page.locator('.cp-details .cp-detail-value').getByText('Not sure').waitFor()
  // Graduation, current major and AI comfort are all set here. Intended major
  // is the sentinel, which is an answer -- but the answer is that there is no
  // second major, so it renders in the absent voice rather than as a name.
  assert.equal(await page.locator('.cp-details .cp-detail-value--absent').count(), 1)
  await page.locator('.cp-details .cp-detail-value--absent').getByText('Not switching majors').waitFor()
})

// The three facts guidance is calibrated against had no representation at all
// in the authenticated app: a student could be told an analysis needed their
// expected graduation on a page that never showed what it held. This pins what
// the rows REPORT; the test below it pins what they save.
//
// Values are read from .cp-detail-value throughout rather than by page text.
// The AI radio labels repeat every option name, so a bare getByText('Moderate')
// matches both the stored answer and the control offering to change it -- two
// different claims that happen to share a word.
test('career profile: details rows report graduation, majors and AI comfort', { timeout: 45_000 }, async (t) => {
  const origin = await startServer(t)
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })

  // ── Every value present, and the student is switching majors.
  await openCareer(page, origin, 'mode=complete&career=rich')
  const details = page.locator('.cp-details')
  const values = () => details.locator('.cp-detail-value').allInnerTexts()
  await details.locator('.cp-detail-value').first().waitFor()
  // Current major and intended major are two facts, not one fact and its
  // caption, so each states itself in its own row.
  assert.deepEqual(await values(), ['Spring 2028', 'Computer Science', 'Data Science', 'Moderate'])
  // The stored column is 'moderate'; a machine token is not English.
  assert.equal((await details.locator('.cp-detail-value').allInnerTexts()).includes('moderate'), false,
    'a raw enum token reached the page')
  assert.equal(await details.locator('.cp-detail-value--absent').count(), 0)

  // ── Not switching. The sentinel is a stored answer, never a typed major,
  // so it is reported as the answer it is and never echoed back verbatim.
  await openCareer(page, origin, 'mode=complete&career=partial')
  await page.locator('.cp-details').getByText('Not switching majors').waitFor()
  assert.equal((await page.locator('.cp').innerText()).includes('N/A'), false, 'the sentinel was printed as a major')

  // ── Nothing set. An absence says so rather than filling with a dash.
  await openCareer(page, origin, 'mode=complete&career=bare')
  const bare = page.locator('.cp-details')
  // Four units report a value: graduation, current major, intended major and
  // AI comfort. Each states its own absence in its own words.
  assert.equal(await bare.locator('.cp-detail-value--absent').count(), 4, 'every unset row must state its absence')
  assert.equal(await bare.locator('.cp-detail-value--absent').filter({ hasText: 'Not set' }).count(), 2)
  // Null AI comfort means never asked -- which is not the same answer as the
  // selectable 'Not sure', and must not borrow its label.
  await bare.locator('.cp-detail-value--absent').getByText('Not answered').waitFor()
  assert.equal(await bare.locator('.cp-detail-value').filter({ hasText: 'Not sure' }).count(), 0)
  // Nothing is preselected while the column is null: an unselected group is
  // how "never asked" looks, and any checked radio would answer for them.
  assert.equal(await bare.locator('input[name="cp-ai-comfort"]:checked').count(), 0)
  // A value never carries a subordinate caption. The switching state used to
  // hang off the current major that way, which said the two were one fact;
  // they are two, and each now has its own labelled unit.
  assert.equal(await bare.locator('.cp-detail-note').count(), 0, 'a value grew a caption again')
  assert.equal(await bare.locator('.cp-detail-unit').count(), 2, 'the major row must hold two units')
})

/**
 * The six units, saved where they are read.
 *
 * These assertions are the container-independent half of what the profile
 * modal's test already pinned -- the sentinel round-trip, the season/year
 * prefill, the tag chips, the unselected radio group, the single-key PATCH
 * body and the reload -- re-aimed at the inline rows. They were never really
 * about the dialog; they are about what the fields do with the data, which is
 * why the same claims survive the move.
 */
test('career profile: six units save independently, inline', { timeout: 45_000 }, async (t) => {
  const patches = []
  const apiPlugin = { name: 'profile-api', configureServer(server) { server.middlewares.use((request, response, next) => {
    if (request.url?.split('?')[0] === '/api/v2/student/me/profile' && request.method === 'PATCH') {
      let body = ''
      request.on('data', (chunk) => { body += chunk })
      request.on('end', () => {
        patches.push(JSON.parse(body))
        response.statusCode = 200
        response.setHeader('content-type', 'application/json')
        response.end(JSON.stringify({ ok: true }))
      })
      return
    }
    next()
  }) } }

  const origin = await startServer(t, [apiPlugin])
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
  await openCareer(page, origin, 'mode=complete&career=rich')

  // The major row holds two units inside one cell, so the cell itself would
  // also match a heading belonging to one of them. Excluding the wrapper keeps
  // this resolving to the unit that actually owns the Edit button.
  const row = (label) => page
    .locator('.cp-detail-unit, .cp-field, .cp-detail:not(.cp-detail--stack)')
    .filter({ has: page.getByRole('heading', { name: label, exact: true }) })

  // ── Five independently editable units, each with its own Edit control. AI
  // comfort is the sixth unit and deliberately has none: every value it can
  // hold is already valid, so there is no intermediate state to protect.
  assert.equal(await page.locator('.cp .editable-section').count(), 5)
  for (const label of ['Expected graduation', 'Current major', 'Intended major', 'Target roles', 'Interests']) {
    assert.equal(await row(label).getByRole('button', { name: 'Edit' }).count(), 1, `${label} is not editable`)
  }

  // ── The graduation pair prefills from the stored string, rather than making
  // the student re-derive "Spring 2028" into two selects.
  const graduation = row('Expected graduation')
  await graduation.getByRole('button', { name: 'Edit' }).click()
  assert.equal(await graduation.getByLabel('Season').inputValue(), 'Spring')
  assert.equal(await graduation.getByLabel('Year').inputValue(), '2028')

  // BOTH OR NEITHER: half an answer is refused, and refusing it neither saves
  // nor closes the row.
  await graduation.getByLabel('Season').selectOption('')
  await graduation.getByRole('button', { name: 'Save' }).click()
  await graduation.getByText('Choose both a graduation season and year, or leave both blank.').waitFor()
  assert.equal(patches.length, 0, 'an invalid pair was sent to the server')
  await graduation.getByLabel('Season').selectOption('Fall')
  await graduation.getByRole('button', { name: 'Save' }).click()
  await graduation.getByRole('button', { name: 'Edit' }).waitFor()
  // ONE FIELD, ONE KEY. The row sends what it owns and nothing else.
  assert.deepEqual(patches.at(-1), { expected_graduation: 'Fall 2028' })
  assert.equal(await page.evaluate(() => document.body.dataset.profileReloaded), 'yes')
  await page.getByRole('status').filter({ hasText: 'Profile saved' }).waitFor()

  // ── Current major is its own unit. Fixing a mis-parsed major is a plain
  // text edit that must not drag the switching question along with it.
  const currentMajor = row('Current major')
  await currentMajor.getByRole('button', { name: 'Edit' }).click()
  assert.equal(await currentMajor.getByLabel('Current major').inputValue(), 'Computer Science')
  await currentMajor.getByLabel('Current major').fill('Computer Engineering')
  await currentMajor.getByRole('button', { name: 'Save' }).click()
  await currentMajor.getByRole('button', { name: 'Edit' }).waitFor()
  // No sentinel, no gate, and above all no major_intended riding along.
  assert.deepEqual(patches.at(-1), { major_current: 'Computer Engineering' })

  // An unchanged text field spends no request.
  const afterCurrent = patches.length
  await currentMajor.getByRole('button', { name: 'Edit' }).click()
  await currentMajor.getByRole('button', { name: 'Save' }).click()
  await currentMajor.getByRole('button', { name: 'Edit' }).waitFor()
  assert.equal(patches.length, afterCurrent, 'an unchanged current major was sent to the server')

  // ── The sentinel round-trip. `rich` stores a real intended major, so the
  // box is ticked and the field carries it.
  const major = row('Intended major')
  await major.getByRole('button', { name: 'Edit' }).click()
  const switching = major.getByLabel("I'm planning to switch majors")
  assert.equal(await switching.isChecked(), true)
  assert.equal(await major.getByLabel('Intended major').inputValue(), 'Data Science')
  // Unticking gates the field and clears it -- "staying" is never expressed by
  // leaving a half-typed major behind.
  await switching.uncheck()
  assert.equal(await major.getByLabel('Intended major').isDisabled(), true)
  assert.equal(await major.getByLabel('Intended major').inputValue(), '')
  await major.getByRole('button', { name: 'Save' }).click()
  await major.getByRole('button', { name: 'Edit' }).waitFor()
  // Not switching is a POSITIVE write of the sentinel, never an erasure: the
  // API rejects '' and treats an omitted key as "leave untouched".
  assert.deepEqual(patches.at(-1), { major_intended: 'N/A' })

  // A switching student who names no major is refused, and the sentinel is
  // not quietly written in their place. (The preview's reload returns the same
  // profile, so the row re-opens on the stored 'Data Science' -- the empty
  // field this rejects has to be made empty here.)
  const afterMajor = patches.length
  await major.getByRole('button', { name: 'Edit' }).click()
  const switchBox = major.getByLabel("I'm planning to switch majors")
  if (!(await switchBox.isChecked())) await switchBox.check()
  await major.getByLabel('Intended major').fill('')
  await major.getByRole('button', { name: 'Save' }).click()
  await major.getByText('Name the major you are switching to, or untick the box.').waitFor()
  assert.equal(patches.length, afterMajor, 'an incomplete switch was saved')
  await major.getByRole('button', { name: 'Cancel' }).click()

  // ── Tag chips: the editor opens holding what the profile already has.
  const roles = row('Target roles')
  await roles.getByRole('button', { name: 'Edit' }).click()
  await roles.locator('.tag-chip').filter({ hasText: 'AI Engineer' }).waitFor()
  await roles.getByRole('button', { name: 'Remove ML Engineer' }).click()
  await roles.getByRole('button', { name: 'Save' }).click()
  await roles.getByRole('button', { name: 'Edit' }).waitFor()
  assert.deepEqual(patches.at(-1), { target_roles: ['AI Engineer', 'Robotics Engineer'] })

  // Cancel restores rather than saves: an abandoned edit costs no request.
  const before = patches.length
  const interests = row('Interests')
  await interests.getByRole('button', { name: 'Edit' }).click()
  await interests.getByRole('button', { name: 'Remove Robotics' }).click()
  await interests.getByRole('button', { name: 'Cancel' }).click()
  assert.equal(patches.length, before, 'cancel sent a request')
  await interests.getByText('Physical AI · Robotics · LLM Systems').waitFor()

  // ── AI comfort saves on selection, with no Save button to press.
  assert.equal(await row('AI comfort').getByRole('button', { name: 'Edit' }).count(), 0)
  const comfort = page.locator('.cp-details')

  // click(), not check(): check() asserts the radio ends up selected, and the
  // preview's reload hands back the same profile, so the group re-renders on
  // the stored answer. Firing the event is what is under test here; what the
  // control settles on afterwards is the fixture's business.
  //
  // Re-picking the stored answer spends no request. `rich` stores 'moderate',
  // so this is the selection that is already true.
  const settled = patches.length
  await comfort.getByLabel('Moderate').click()
  await page.waitForTimeout(250)
  assert.equal(patches.length, settled, 'a no-op selection was sent to the server')

  await comfort.getByLabel('High').click()
  await waitForPatch(patches, settled + 1)
  assert.deepEqual(patches.at(-1), { ai_anxiety_level: 'high' })

  // Every save wrote exactly one key: the units are genuinely independent.
  assert.deepEqual(patches.map((patch) => Object.keys(patch).length), patches.map(() => 1))
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
