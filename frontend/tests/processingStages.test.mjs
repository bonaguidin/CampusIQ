// The presentational stage schedule, checked without a clock or a browser.
//
// These are the properties that make the stages honest rather than merely
// pretty: monotonic, clamped, and incapable of reporting completion. Asserting
// them here means a future change to the timings cannot quietly reintroduce a
// wrap-around or a fifth "done" stage.

import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

import {
  BUSY_LABEL,
  RESUME_STAGES,
  STAGE_SCHEDULE,
  TRANSCRIPT_STAGES,
  TRUST_NOTE,
  stageIndexAt,
  stageTimeouts,
  stagesFor,
} from '../src/lib/processingStages.mjs'

test('the schedule is strictly ascending and starts immediately', () => {
  assert.equal(STAGE_SCHEDULE[0], 0, 'the first stage must be current with no delay')
  for (let i = 1; i < STAGE_SCHEDULE.length; i += 1) {
    assert.ok(STAGE_SCHEDULE[i] > STAGE_SCHEDULE[i - 1], `threshold ${String(i)} must advance`)
  }
  // One timer per threshold after the first -- no timer for stage 0.
  assert.deepEqual(stageTimeouts(), STAGE_SCHEDULE.slice(1))
  assert.equal(stageTimeouts().length, STAGE_SCHEDULE.length - 1)
})

// CASE P3 / P4: stages progress for both kinds while a request stays pending.
test('both flows have a stage for every threshold, in the documented order', () => {
  for (const [kind, stages, expected] of [
    ['resume', RESUME_STAGES, [
      'Uploading your resume…',
      'Reading your resume…',
      'Extracting experience, projects, and certifications…',
      'Preparing your review…',
    ]],
    ['transcript', TRANSCRIPT_STAGES, [
      'Uploading your transcript…',
      'Reading your transcript…',
      'Extracting courses and grades…',
      'Preparing your review…',
    ]],
  ]) {
    assert.equal(stages.length, STAGE_SCHEDULE.length, `${kind} needs one stage per threshold`)
    assert.deepEqual(stages.map((s) => s.label), expected)
    assert.equal(stagesFor(kind), stages)
    for (const stage of stages) {
      assert.ok(stage.detail.trim().length > 0, `${kind} stages each need a detail line`)
    }
  }
})

// CASE P3 / P4: elapsed time selects the stage, monotonically.
test('the stage index advances with elapsed time and never goes backwards', () => {
  assert.equal(stageIndexAt(0), 0)
  assert.equal(stageIndexAt(899), 0)
  assert.equal(stageIndexAt(900), 1)
  assert.equal(stageIndexAt(2199), 1)
  assert.equal(stageIndexAt(2200), 2)
  assert.equal(stageIndexAt(3999), 2)
  assert.equal(stageIndexAt(4000), 3)

  let previous = -1
  for (let elapsed = 0; elapsed <= 12_000; elapsed += 50) {
    const index = stageIndexAt(elapsed)
    assert.ok(index >= previous, `stage went backwards at ${String(elapsed)}ms`)
    previous = index
  }
})

// CASE P10: the final stage is terminal. A wrap-around would tell the student
// the work restarted, which is false and worst exactly when they are anxious.
test('the last stage is a resting place, never a loop back to the first', () => {
  const last = STAGE_SCHEDULE.length - 1
  for (const elapsed of [4000, 10_000, 60_000, 600_000, 86_400_000]) {
    assert.equal(stageIndexAt(elapsed), last, `wrapped or advanced past the end at ${String(elapsed)}`)
  }
  // Nonsense input degrades to the first stage rather than throwing or NaN.
  for (const bad of [undefined, null, 'soon', Number.NaN, Number.POSITIVE_INFINITY, -5]) {
    const index = stageIndexAt(bad)
    assert.ok(Number.isInteger(index) && index >= 0 && index <= last)
  }
})

// CASE P5: stages are presentational. Nothing here can report completion.
test('no stage claims completion, progress, or a percentage', () => {
  const everything = [...RESUME_STAGES, ...TRANSCRIPT_STAGES]
    .flatMap((stage) => [stage.label, stage.detail])
    .concat(Object.values(TRUST_NOTE), Object.values(BUSY_LABEL))

  for (const text of everything) {
    assert.equal(/\d+\s*%/.test(text), false, `"${text}" must not state a percentage`)
    assert.equal(/\bdone\b|\bcomplete[d]?\b|\bfinished\b|almost/i.test(text), false,
      `"${text}" must not imply completion`)
  }
})

// CASE P5: the module exposes no completion concept at all, so there is
// nothing for a caller to mistake for one.
test('the shipped module exposes no completion signal', async () => {
  const source = await readFile(new URL('../src/lib/processingStages.mjs', import.meta.url), 'utf8')
  // Exported names only. The prose above them is free to discuss percentages
  // precisely because it is explaining why there are none.
  const exported = [...source.matchAll(/export (?:const|function) (\w+)/g)].map((m) => m[1])
  assert.ok(exported.length > 0, 'the module must export something')
  for (const name of exported) {
    assert.equal(/done|complete|finish|percent|ratio|progress/i.test(name), false,
      `exported "${name}" reads as a completion or progress signal`)
  }
})

// CASE P9 (the source half): the hook clears every timer it creates.
test('the stage hook cleans up its timers', async () => {
  const source = await readFile(new URL('../src/hooks/useProcessingStage.ts', import.meta.url), 'utf8')
  assert.match(source, /clearTimeout/)
  // A cleanup function is returned from the effect, which is what React calls
  // on both an `active` flip and on unmount.
  assert.match(source, /return \(\) => \{[\s\S]*clearTimeout[\s\S]*\}/)
  // Resets rather than freezing when work stops.
  assert.match(source, /if \(!active\)[\s\S]*setStage\(0\)/)
})

test('trust copy survives from the old upload screens, per kind', () => {
  assert.match(TRUST_NOTE.resume, /review everything before it is saved/i)
  assert.match(TRUST_NOTE.transcript, /review every course before it is added/i)
  assert.equal(BUSY_LABEL.resume, 'Processing resume…')
  assert.equal(BUSY_LABEL.transcript, 'Processing transcript…')
})
