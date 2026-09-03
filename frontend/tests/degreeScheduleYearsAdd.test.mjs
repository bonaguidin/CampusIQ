import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const YEARS = new URL('../src/components/DegreeScheduleYears.tsx', import.meta.url)
const SEARCH = new URL('../src/components/CourseSearchAdd.tsx', import.meta.url)
const TERM_PLANNER = new URL('../src/components/TermPlanner.tsx', import.meta.url)

test('CourseSearchAdd is shared, not reinvented: TermPlanner delegates its search to it', async () => {
  const [planner, search] = await Promise.all([readFile(TERM_PLANNER, 'utf8'), readFile(SEARCH, 'utf8')])
  // The debounce + catalog search moved into the shared component.
  assert.match(search, /SEARCH_DEBOUNCE_MS/)
  assert.match(search, /searchCatalog\(identity/)
  assert.match(planner, /import \{ CourseSearchAdd \} from '\.\/CourseSearchAdd'/)
  assert.match(planner, /<CourseSearchAdd/)
  // TermPlanner no longer carries its own copy of the search machinery.
  assert.doesNotMatch(planner, /searchCatalog/)
  assert.doesNotMatch(planner, /SEARCH_DEBOUNCE_MS/)
  // Its activation notice still rides along, as the hint slot.
  assert.match(planner, /hint=\{willActivateOnAdd/)
})

test('year view: the add control is gated on a future term and forces a planned write', async () => {
  const years = await readFile(YEARS, 'utf8')
  // The CourseSearchAdd block sits inside the state === 'future' branch only.
  const futureBranch = years.slice(years.indexOf("semester.state === 'future'"))
  assert.match(futureBranch, /<CourseSearchAdd/)
  assert.doesNotMatch(
    years.slice(0, years.indexOf("semester.state === 'future'")),
    /<CourseSearchAdd/,
  )
  // The add call opts out of activation-window promotion.
  assert.match(years, /force_planned: true/)
  assert.match(years, /addPlannedCourse\(identity/)
})

test('year view: planned rows carry the Added badge and a Remove action wired to the delete route', async () => {
  const years = await readFile(YEARS, 'utf8')
  assert.match(years, /degree-schedule-badge--added">Added</)
  assert.match(years, /removePlannedCourse\(identity, id\)/)
  assert.match(years, /aria-label=\{`Remove \$\{course\.course_code\} from your plan`\}/)
  // After a successful add/remove the planned list (and terms, for a freshly
  // materialized academic_terms row) reload -- no optimistic local mutation.
  assert.match(years, /Promise\.all\(\[loadPlanned\(\), loadTerms\(\)\]\)/)
})

test('the Added badge is defined in the filled-tint family, achromatic (neutral), distinct from gold/green', async () => {
  const css = await readFile(new URL('../src/index.css', import.meta.url), 'utf8')
  const block = css.slice(css.indexOf('.degree-schedule-badge--added'))
  assert.match(block.slice(0, 160), /color: var\(--pending\)/)
  assert.match(block.slice(0, 160), /background: var\(--pending-tint\)/)
})
