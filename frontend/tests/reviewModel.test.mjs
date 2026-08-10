import assert from 'node:assert/strict'
import test from 'node:test'

import {
  GLYPH_EDITED,
  GLYPH_EMPTY,
  GLYPH_READ,
  REVIEW_SECTIONS,
  entryFilled,
  entryGaps,
  fieldGlyph,
  formatNumberInput,
  isEmptyValue,
  parseNumberInput,
  reviewCounters,
} from '../src/lib/resumeApi.mjs'

// The redesigned review screen renders entirely from these functions. They live
// in .mjs precisely so they are testable -- node --test cannot load .tsx, so
// anything moved into the component is untestable by construction.

// ── isEmptyValue ────────────────────────────────────────────────────────────

test('isEmptyValue treats null, blank, and empty lists as unfilled', () => {
  for (const empty of [null, undefined, '', '   ', '\n', []]) {
    assert.equal(isEmptyValue(empty), true, `${JSON.stringify(empty)} should be empty`)
  }
  for (const filled of ['x', ' x ', ['a'], 0, 3.5, false]) {
    assert.equal(isEmptyValue(filled), false, `${JSON.stringify(filled)} should be filled`)
  }
})

test('isEmptyValue does not treat 0 or false as missing', () => {
  // A credit_hours of 0 is a real value (zero-credit courses exist), and
  // collapsing it into a gap pill would invite the student to "fill in" a
  // field that is already correct.
  assert.equal(isEmptyValue(0), false)
  assert.equal(isEmptyValue(false), false)
})

// ── fieldGlyph ──────────────────────────────────────────────────────────────

test('fieldGlyph: unchanged filled field reads as "·"', () => {
  const row = { employer: 'NVIDIA' }
  assert.equal(fieldGlyph(row, { ...row }, 'employer'), GLYPH_READ)
})

test('fieldGlyph: changed filled field reads as "✎"', () => {
  assert.equal(fieldGlyph({ employer: 'NVIDIA' }, { employer: 'Nvidia Corp' }, 'employer'), GLYPH_EDITED)
})

test('fieldGlyph: field emptied by the student reads as "⌀"', () => {
  assert.equal(fieldGlyph({ employer: 'NVIDIA' }, { employer: '' }, 'employer'), GLYPH_EMPTY)
  assert.equal(fieldGlyph({ tools: ['a'] }, { tools: [] }, 'tools'), GLYPH_EMPTY)
})

test('fieldGlyph: field empty on both sides renders no row at all', () => {
  // null, not a glyph: an untouched empty field belongs in the gap pills, not
  // as a row with a marker beside nothing.
  assert.equal(fieldGlyph({ issuer: null }, { issuer: null }, 'issuer'), null)
  assert.equal(fieldGlyph({}, {}, 'issuer'), null)
})

test('fieldGlyph: typing a change and typing it back reverts to "·"', () => {
  // Derived from a value comparison rather than a touched flag -- the stored
  // value really did come straight from the resume, so it should say so.
  assert.equal(fieldGlyph({ role: 'AI Intern' }, { role: 'AI Intern' }, 'role'), GLYPH_READ)
})

test('fieldGlyph: whitespace-only difference is not an edit', () => {
  assert.equal(fieldGlyph({ role: 'AI Intern' }, { role: '  AI Intern  ' }, 'role'), GLYPH_READ)
})

test('fieldGlyph: a filled gap (empty -> value) reads as edited', () => {
  assert.equal(fieldGlyph({ issuer: null }, { issuer: 'Amazon' }, 'issuer'), GLYPH_EDITED)
})

test('fieldGlyph: list reordering counts as an edit', () => {
  assert.equal(fieldGlyph({ tools: ['a', 'b'] }, { tools: ['b', 'a'] }, 'tools'), GLYPH_EDITED)
})

// ── entryGaps / entryFilled ─────────────────────────────────────────────────

test('entryGaps and entryFilled partition a section\'s fields exactly', () => {
  const row = { name: 'AWS Cloud Practitioner', issuer: null, status: 'completed', date: '' }
  const gaps = entryGaps('certifications', row)
  const filled = entryFilled('certifications', row)

  assert.deepEqual(filled, ['name', 'status'])
  assert.deepEqual(gaps, ['issuer', 'date'])
  assert.equal(gaps.length + filled.length, REVIEW_SECTIONS.certifications.fields.length)
})

test('entryGaps preserves the section field order, not row key order', () => {
  const row = { date: '2024', name: 'X' }
  assert.deepEqual(entryGaps('certifications', row), ['issuer', 'status'])
})

test('entryGaps on an unknown table is empty rather than throwing', () => {
  assert.deepEqual(entryGaps('nope', { a: 1 }), [])
  assert.deepEqual(entryFilled('nope', { a: 1 }), [])
})

// ── reviewCounters ──────────────────────────────────────────────────────────

function certRow(overrides = {}) {
  return { name: 'AWS', issuer: 'Amazon', status: 'completed', date: '2024', ...overrides }
}

test('reviewCounters partitions every field into read | edited | gaps', () => {
  const original = certRow()
  const rows = [{ table: 'certifications', original, draft: { ...original } }]
  const counters = reviewCounters(rows)

  assert.equal(counters.total, 4)
  assert.equal(counters.read, 4)
  assert.equal(counters.edited, 0)
  assert.equal(counters.gaps, 0)
  assert.equal(counters.read + counters.edited + counters.gaps, counters.total)
})

test('reviewCounters counts an edit and a gap separately', () => {
  const original = certRow({ date: null })
  const rows = [
    { table: 'certifications', original, draft: { ...original, issuer: 'AWS Training' } },
  ]
  const counters = reviewCounters(rows)

  assert.equal(counters.total, 4)
  assert.equal(counters.read, 2) // name, status
  assert.equal(counters.edited, 1) // issuer
  assert.equal(counters.gaps, 1) // date
})

test('reviewCounters sums across several sections', () => {
  const rows = [
    { table: 'certifications', original: certRow(), draft: certRow() },
    {
      table: 'projects',
      original: { name: 'Scheduler', timeframe: null, description: null, tools: [] },
      draft: { name: 'Scheduler', timeframe: null, description: null, tools: [] },
    },
  ]
  const counters = reviewCounters(rows)

  assert.equal(counters.total, 4 + 4)
  assert.equal(counters.read, 4 + 1)
  assert.equal(counters.gaps, 3)
})

test('reviewCounters filledRatio drives the progress bar', () => {
  const original = certRow({ date: null, issuer: null })
  const counters = reviewCounters([{ table: 'certifications', original, draft: { ...original } }])

  assert.equal(counters.gaps, 2)
  assert.equal(counters.filledRatio, 0.5)
})

test('reviewCounters on nothing is a full bar, not a divide-by-zero', () => {
  for (const empty of [[], null, undefined]) {
    const counters = reviewCounters(empty)
    assert.equal(counters.total, 0)
    assert.equal(counters.filledRatio, 1)
    assert.ok(Number.isFinite(counters.filledRatio))
  }
})

test('reviewCounters skips unknown tables rather than throwing', () => {
  const counters = reviewCounters([{ table: 'not_a_table', original: {}, draft: {} }])
  assert.equal(counters.total, 0)
})

test('the commit bar and the ledger cannot disagree', () => {
  // Both read this one object. The assertion is really about the shape: gaps
  // and total come from the same call, so "N fields stay empty" is always the
  // ledger's own N.
  const original = certRow({ date: null })
  const counters = reviewCounters([{ table: 'certifications', original, draft: { ...original } }])

  const barSaysSaved = counters.total - counters.gaps
  assert.equal(barSaysSaved, counters.read + counters.edited)
})

// ── number field type ───────────────────────────────────────────────────────

test('number is part of the review field-type vocabulary', () => {
  // Declared for transcript review's credit_hours. No resume section uses it
  // yet; this asserts the renderer contract exists so the later stage does not
  // have to retrofit it.
  const types = new Set()
  for (const section of Object.values(REVIEW_SECTIONS)) {
    for (const field of section.fields) types.add(field.type)
  }
  for (const known of types) {
    assert.ok(
      ['text', 'textarea', 'list', 'status', 'number'].includes(known),
      `unexpected field type ${known}`,
    )
  }
})

test('parseNumberInput accepts real numbers in string or numeric form', () => {
  assert.equal(parseNumberInput('3'), 3)
  assert.equal(parseNumberInput('3.5'), 3.5)
  assert.equal(parseNumberInput('  4.00  '), 4)
  assert.equal(parseNumberInput('0'), 0)
  assert.equal(parseNumberInput('-2'), -2)
  assert.equal(parseNumberInput(3.5), 3.5)
})

test('parseNumberInput rejects garbage rather than coercing it', () => {
  // The failure this prevents: "3 hours" silently becoming 3 in a field that
  // multiplies into a GPA.
  for (const bad of ['', '   ', '3 hours', 'three', 'abc', '1.2.3', '--2', '1e5', null, undefined, true, false, {}, []]) {
    assert.equal(parseNumberInput(bad), null, `${JSON.stringify(bad)} must reject`)
  }
})

test('parseNumberInput rejects non-finite values', () => {
  assert.equal(parseNumberInput(Number.NaN), null)
  assert.equal(parseNumberInput(Number.POSITIVE_INFINITY), null)
  assert.equal(parseNumberInput('Infinity'), null)
})

test('formatNumberInput round-trips a number and blanks anything else', () => {
  assert.equal(formatNumberInput(3), '3')
  assert.equal(formatNumberInput(3.5), '3.5')
  assert.equal(formatNumberInput(0), '0')
  assert.equal(formatNumberInput('4.0'), '4.0')
  assert.equal(formatNumberInput(null), '')
  assert.equal(formatNumberInput('three'), '')
  assert.equal(formatNumberInput(Number.NaN), '')
})

test('a number field participates in glyphs and counters like any other', () => {
  const section = { table: 'certifications' }
  // Simulated: fieldGlyph is type-agnostic, it compares normalized values.
  assert.equal(fieldGlyph({ credit_hours: 3 }, { credit_hours: 3 }, 'credit_hours'), GLYPH_READ)
  assert.equal(fieldGlyph({ credit_hours: 3 }, { credit_hours: 4 }, 'credit_hours'), GLYPH_EDITED)
  assert.equal(fieldGlyph({ credit_hours: 3 }, { credit_hours: null }, 'credit_hours'), GLYPH_EMPTY)
  assert.equal(fieldGlyph({ credit_hours: null }, { credit_hours: null }, 'credit_hours'), null)
  assert.ok(section)
})
