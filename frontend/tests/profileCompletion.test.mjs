import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

test('profile completion modal and fallback route share one form without changing SHIFT gating', async () => {
  const [app, page, modal, analysis, shift] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/ProfileCompletionPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/profile/ProfileCompletionModal.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/AnalysisPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../../GradusIQ_career/features/shift.py', import.meta.url), 'utf8'),
  ])
  assert.match(app, /path="\/profile\/complete"/)
  assert.match(page, /<ProfileCompletionForm/)
  assert.match(modal, /<ProfileCompletionForm/)
  assert.match(modal, /role="dialog"/)
  assert.match(modal, /aria-modal="true"/)
  assert.match(analysis, /useProfileCompletionModal/)
  const requiredPaths = shift.match(/required_paths\s*=\s*\(([\s\S]*?)\)/)?.[1] ?? ''
  assert.doesNotMatch(requiredPaths, /ai_anxiety_level/)
})

// The N/A the form writes is FIT's sentinel, and nothing at runtime would
// notice if the two drifted: the value crosses the boundary as an opaque
// string in a PATCH body, so a stale client would just start telling FIT that
// every staying student is switching. This is the check that catches it.
test('the frontend N/A sentinel still matches fit.py', async () => {
  const [sentinel, fit] = await Promise.all([
    readFile(new URL('../src/lib/majorSentinel.ts', import.meta.url), 'utf8'),
    readFile(new URL('../../GradusIQ_career/features/fit.py', import.meta.url), 'utf8'),
  ])
  const python = fit.match(/^_NO_INTENDED_MAJOR\s*=\s*"([^"]*)"/m)?.[1]
  const typescript = sentinel.match(/export const NO_INTENDED_MAJOR = '([^']*)'/)?.[1]
  assert.ok(python, 'fit.py no longer defines _NO_INTENDED_MAJOR')
  assert.ok(typescript, 'majorSentinel.ts no longer exports NO_INTENDED_MAJOR')
  assert.equal(typescript, python)
  // fit.py compares case-insensitively; the mirrored read helper must too.
  assert.match(sentinel, /toUpperCase\(\) === NO_INTENDED_MAJOR/)
})

test('the completion form owns only its five fields and routes the rest to resume review', async () => {
  const [form, analysis, page] = await Promise.all([
    readFile(new URL('../src/components/profile/ProfileCompletionForm.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/AnalysisPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/ProfileCompletionPage.tsx', import.meta.url), 'utf8'),
  ])

  // Skills belong to /resume. The form must not offer a competing editor, and
  // must not claim a field it cannot write.
  assert.doesNotMatch(form, /skills_technical|skills_soft|Technical skills|Professional skills/)
  assert.match(form, /resume review/)
  // Both résumé-owned gaps bypass the modal entirely, or they reopen a dialog
  // with no field for the thing that is missing.
  // Matched against the LABELS map alone -- the prose around it names these
  // paths precisely to record that their absence is a decision.
  const labels = page.match(/const LABELS: Record<string, string> = \{([\s\S]*?)\};/)?.[1] ?? ''
  assert.ok(labels, 'ProfileCompletionPage no longer declares a LABELS map')
  for (const path of ['career.skills_self_reported', 'career.work_experience']) {
    assert.match(analysis, new RegExp(`RESUME_OWNED_PATHS = new Set\\(\\[[^\\]]*'${path}'`))
    assert.doesNotMatch(labels, new RegExp(path.replace('.', '\\.')))
  }

  // "Not answered" was a default-selected state dressed as a choice, so a
  // never-asked profile rendered as an answered one. Null is now unselected.
  assert.doesNotMatch(form, /Not answered/)
  assert.match(form, /Skip this if you'd rather not say\./)
  assert.doesNotMatch(form, /checked=\{anxiety === ''\}/)

  // Not switching is written, never typed: the checkbox gates the field and
  // the sentinel comes from the shared constant.
  assert.match(form, /I'm planning to switch majors/)
  assert.match(form, /disabled=\{!switching\}/)
  assert.match(form, /switching \? majorIntended\.trim\(\) : NO_INTENDED_MAJOR/)
  // The literal may appear in prose (comments, helper copy); what must not
  // exist is a second hardcoded copy of it in the code itself.
  const code = form.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
  assert.doesNotMatch(code, /'N\/A'|"N\/A"/)
})
