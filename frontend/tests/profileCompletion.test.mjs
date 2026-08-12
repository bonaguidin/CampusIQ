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
