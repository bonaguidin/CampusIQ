// The structural half of the post-confirm cleanup.
//
// The browser tests prove the flows behave correctly TODAY. What they cannot
// catch is the shape of the mistake being removed here: a future change that
// re-adds `setDone(true)` and renders a terminal success page instead of
// navigating. Such a change would keep every existing assertion passing right
// up until someone also wired the page in, so the shape itself is asserted.

import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

import {
  RESUME_SUCCESS_MESSAGE,
  TRANSCRIPT_SUCCESS_MESSAGE,
  readSuccessNotice,
  resumeSuccessState,
  transcriptSuccessMessage,
  transcriptSuccessState,
} from '../src/lib/successNotice.mjs'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('neither confirmation flow has a completed state left to render', async () => {
  for (const path of ['pages/TranscriptPage.tsx', 'pages/ResumePage.tsx']) {
    const source = await read(path)

    // The step union is the structural guarantee. A terminal screen needs a
    // state to render from, and there is none: re-adding one is a visible,
    // reviewable change to this line rather than a quiet extra branch.
    const stepUnion = /type Step =([^;]+);/.exec(source)
    assert.ok(stepUnion, `${path} must still declare its Step union`)
    assert.equal(stepUnion[1].includes("'done'"), false, `${path} must not have a 'done' step`)
    assert.equal(stepUnion[1].includes("'complete'"), false, `${path} must not have a 'complete' step`)

    // Success navigates. It does not set a flag and re-render.
    assert.match(source, /navigate\('\/dashboard'/, `${path} must navigate on success`)
    assert.equal(/setDone\(/.test(source), false, `${path} must not gate on a done flag`)
  }
})

test('the terminal success copy is gone from the shipped source', async () => {
  const sources = await Promise.all(
    ['pages/TranscriptPage.tsx', 'pages/ResumePage.tsx', 'components/TranscriptReview.tsx', 'components/CareerReview.tsx']
      .map(read),
  )
  const all = sources.join('\n')
  for (const phrase of ['Your transcript is saved', 'Your profile has been saved', 'Go to dashboard']) {
    assert.equal(all.includes(phrase), false, `"${phrase}" must not survive anywhere in the flows`)
  }
})

test('the shared GoToDashboard component is deleted, not orphaned', async () => {
  await assert.rejects(read('components/GoToDashboard.tsx'), /ENOENT/)
})

test('the dashboard notice is announced and dismissible', async () => {
  const source = await read('components/DashboardSuccessNotice.tsx')
  assert.match(source, /role="status"/)
  assert.match(source, /aria-live="polite"/)
  // Not modal, not blocking, and it never takes focus.
  assert.equal(/role="(dialog|alertdialog|alert)"/.test(source), false)
  assert.equal(/\.focus\(\)/.test(source), false)
  assert.match(source, /aria-label="Dismiss this message"/)
  // The history entry is rewritten without the state, so a refresh cannot
  // replay the notice.
  assert.match(source, /replace: true, state: null/)
})

test('transcript success copy uses the backend count only when there is one', () => {
  assert.equal(transcriptSuccessMessage(11), 'Transcript saved — 11 courses added to your academic record.')
  assert.equal(transcriptSuccessMessage(1), 'Transcript saved — 1 course added to your academic record.')
  // An absent or zero count is an absence, never "0 courses added".
  assert.equal(transcriptSuccessMessage(0), TRANSCRIPT_SUCCESS_MESSAGE)
  assert.equal(transcriptSuccessMessage(undefined), TRANSCRIPT_SUCCESS_MESSAGE)
  assert.equal(transcriptSuccessMessage('11'), TRANSCRIPT_SUCCESS_MESSAGE)
  assert.equal(transcriptSuccessMessage(Number.NaN), TRANSCRIPT_SUCCESS_MESSAGE)
})

test('resume success copy states the outcome without inventing a count', () => {
  assert.equal(RESUME_SUCCESS_MESSAGE, 'Resume saved — your career profile has been updated.')
  assert.equal(/\d/.test(RESUME_SUCCESS_MESSAGE), false)
  assert.deepEqual(resumeSuccessState(), { success: { type: 'resume', message: RESUME_SUCCESS_MESSAGE } })
})

test('only the exact notice shape is read back out of router state', () => {
  assert.deepEqual(readSuccessNotice(transcriptSuccessState(2)), {
    type: 'transcript',
    message: 'Transcript saved — 2 courses added to your academic record.',
  })
  // A direct visit to /dashboard, or any other entry's state, shows nothing.
  for (const state of [null, undefined, {}, 'transcript', { success: null }, { success: {} },
    { success: { type: 'transcript' } }, { success: { type: 'other', message: 'hi' } },
    { success: { type: 'resume', message: '  ' } }]) {
    assert.equal(readSuccessNotice(state), null)
  }
})
