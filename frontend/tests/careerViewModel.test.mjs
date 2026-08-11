// The Career presentation shaping, checked without a browser.
//
// The properties that matter most here are negative ones: nothing is scored,
// nothing is classified, and no description is rewritten. Those are easy to
// violate later by accident, so they are pinned rather than assumed.

import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

import {
  DESCRIPTION_PREVIEW_LIMIT,
  buildCareerViewModel,
  careerDirection,
  certificationEntries,
  experienceEntries,
  list,
  previewOf,
  projectEntries,
  skillGroups,
  text,
} from '../src/data/careerViewModel.mjs'

const LONG = 'Built a convolutional model for ECG arrhythmia classification on the MIT-BIH database, covering the full pipeline from signal preprocessing and beat segmentation through to model training, evaluation and error analysis across the five AAMI classes.'

const RICH = {
  confirmed: true,
  target_roles: ['AI Engineer', 'ML Engineer'],
  interests: ['Robotics', 'LLM Systems'],
  career_goals: 'Build intelligent systems at the intersection of AI and hardware.',
  geographic_preference: 'Austin, TX',
  ai_anxiety_level: null,
  skills: { technical: ['Python', 'PyTorch', 'CUDA'], soft: ['Written communication'], ai_exposure: null },
  certifications: [{ name: 'NVIDIA Certified Associate', issuer: 'NVIDIA', status: 'completed', date: '2025', source: 'resume_parse' }],
  work_experience: [
    { employer: 'Littlebird', role: 'AI Intern', duration: '2025 – Present', location: 'Remote', description: 'Shipped retrieval tooling.', skills_gained: ['RAG'], source: 'resume_parse' },
    { employer: '10Spy', role: 'Intern', duration: null, location: null, description: null, skills_gained: [], source: 'resume_parse' },
  ],
  projects: [{ name: 'Arrhythmia Classification', timeframe: 'Spring 2025', description: LONG, tools: ['PyTorch', 'NumPy'], source: 'resume_parse' }],
}

const EMPTY = {
  confirmed: true,
  target_roles: [], interests: [], career_goals: null, geographic_preference: null, ai_anxiety_level: null,
  skills: { technical: [], soft: [], ai_exposure: null },
  certifications: [], work_experience: [], projects: [],
}

// ── CASE C1 / C2 / C3 ──────────────────────────────────────────────────────

test('the summary is built from canonical values and counts are array lengths', () => {
  const model = buildCareerViewModel(RICH)
  assert.deepEqual(model.counts, { skills: 4, experience: 2, projects: 1, certifications: 1 })
  assert.deepEqual(model.direction.targetRoles, ['AI Engineer', 'ML Engineer'])
  assert.equal(model.direction.goals, RICH.career_goals)
  assert.equal(model.direction.location, 'Austin, TX')
  assert.equal(model.empty, false)

  // CASE C2: a count is exactly what is in the array, nothing weighted.
  const oneSkill = buildCareerViewModel({ ...RICH, skills: { technical: ['Python'], soft: [], ai_exposure: null } })
  assert.equal(oneSkill.counts.skills, 1)
})

// CASE C4: no fabricated readiness figure can appear, because nothing computes
// one. The absence is asserted against the shipped source, not just the output.
test('no score, percentage or ranking is produced anywhere', async () => {
  const model = buildCareerViewModel(RICH)
  const serialised = JSON.stringify(model)
  assert.equal(/\d+\s?%/.test(serialised), false)
  for (const key of ['score', 'readiness', 'rating', 'rank', 'percent', 'probability', 'match']) {
    assert.equal(new RegExp(`"[^"]*${key}[^"]*":`, 'i').test(serialised), false, `view model exposes a "${key}" field`)
  }

  const source = await readFile(new URL('../src/data/careerViewModel.mjs', import.meta.url), 'utf8')
  const exported = [...source.matchAll(/export (?:const|function) (\w+)/g)].map((m) => m[1])
  for (const name of exported) {
    assert.equal(/score|rank|percent|probability|predict|classif/i.test(name), false,
      `exported "${name}" reads as scoring or classification`)
  }
})

// ── CASE C3 / partial-profile safety ───────────────────────────────────────

test('missing, null, empty and wrong-typed fields all degrade to absence', () => {
  const model = buildCareerViewModel(EMPTY)
  assert.equal(model.empty, true)
  assert.deepEqual(model.counts, { skills: 0, experience: 0, projects: 0, certifications: 0 })
  assert.equal(model.direction.present, false)
  assert.deepEqual(model.skillGroups, [])

  // Nothing here may throw on a profile that is missing keys outright.
  for (const shape of [{}, { confirmed: true }, { skills: null }, { work_experience: null }, { projects: undefined }]) {
    assert.doesNotThrow(() => buildCareerViewModel(shape))
  }

  // Loose row readers reject anything that is not a usable string.
  for (const bad of [null, undefined, '', '   ', 42, [], {}]) {
    assert.equal(text({ employer: bad }, 'employer'), null)
  }
  assert.deepEqual(list({ tools: ['a', '', '  b ', 7, null] }, 'tools'), ['a', 'b'])
  assert.deepEqual(list({ tools: 'not-a-list' }, 'tools'), [])
})

// ── SKILLS ─────────────────────────────────────────────────────────────────

test('skills group by the canonical technical/soft split and nothing else', () => {
  const groups = skillGroups(RICH)
  assert.deepEqual(groups.map((g) => g.key), ['technical', 'soft'])
  assert.deepEqual(groups[0].skills, ['Python', 'PyTorch', 'CUDA'])

  // An empty group is dropped rather than rendered as a heading over nothing.
  const technicalOnly = skillGroups({ skills: { technical: ['Python'], soft: [] } })
  assert.deepEqual(technicalOnly.map((g) => g.key), ['technical'])
  assert.deepEqual(skillGroups({ skills: { technical: [], soft: [] } }), [])
})

test('no semantic skill taxonomy is invented', async () => {
  const source = await readFile(new URL('../src/data/careerViewModel.mjs', import.meta.url), 'utf8')
  // A keyword table mapping skill names to invented categories is the specific
  // thing that must not appear: it would look canonical on screen while being
  // a guess in the source.
  for (const invented of ['Machine Learning', 'Data / Analytics', 'Frameworks', 'Research /']) {
    assert.equal(source.includes(`'${invented}`), false, `"${invented}" looks like an invented category`)
  }
  const groups = skillGroups(RICH)
  assert.deepEqual(groups.map((g) => g.label), ['Technical', 'Soft skills'])
})

// ── EXPERIENCE (E1–E3) ─────────────────────────────────────────────────────

test('experience preserves source order and never invents dates', () => {
  const entries = experienceEntries(RICH)
  assert.deepEqual(entries.map((e) => e.employer), ['Littlebird', '10Spy'])
  assert.equal(entries[0].role, 'AI Intern')
  assert.equal(entries[0].duration, '2025 – Present')

  // CASE E3: a record with no duration/location yields nulls, not placeholders.
  assert.equal(entries[1].duration, null)
  assert.equal(entries[1].location, null)
  assert.equal(entries[1].description, null)
  assert.deepEqual(entries[1].skills, [])
  const serialised = JSON.stringify(entries[1])
  for (const invented of ['Present', 'Unknown', 'N/A', 'Dates']) {
    assert.equal(serialised.includes(invented), false, `"${invented}" was substituted for missing data`)
  }
})

// ── PROJECTS (P1 / P2 / P5 / P6) ───────────────────────────────────────────

test('a long description is previewed by truncation, never by summarising', () => {
  const [project] = projectEntries(RICH)
  assert.equal(project.truncated, true)
  assert.ok(project.preview.length <= DESCRIPTION_PREVIEW_LIMIT + 1)

  // CASE P5: the preview is a PREFIX of the original -- every word came from
  // the student. Nothing was reworded, reordered or generated.
  const head = project.preview.replace(/…$/, '')
  assert.ok(LONG.startsWith(head), 'the preview must be a literal prefix of the original')

  // CASE P2: the full original survives untouched for the expanded view.
  assert.equal(project.description, LONG)

  // Short text is left alone and gets no misleading ellipsis.
  const short = previewOf('A React app for course planning.')
  assert.deepEqual(short, { preview: 'A React app for course planning.', truncated: false })
  assert.deepEqual(previewOf(null), { preview: null, truncated: false })
  assert.deepEqual(previewOf('   '), { preview: null, truncated: false })
})

test('projects carry their real tools list, and none is fabricated when absent', () => {
  assert.deepEqual(projectEntries(RICH)[0].tools, ['PyTorch', 'NumPy'])
  // CASE P6: no tools field -> no tags, rather than tags parsed out of prose.
  const untagged = projectEntries({ projects: [{ name: 'Scheduler', description: LONG }] })
  assert.deepEqual(untagged[0].tools, [])
  assert.equal(untagged[0].name, 'Scheduler')
})

// ── CERTIFICATIONS (CERT1 / CERT2) ─────────────────────────────────────────

test('certifications read their canonical columns and tolerate missing ones', () => {
  const [cert] = certificationEntries(RICH)
  assert.equal(cert.name, 'NVIDIA Certified Associate')
  assert.equal(cert.issuer, 'NVIDIA')
  assert.equal(cert.statusLabel, 'Completed')

  const sparse = certificationEntries({ certifications: [{ name: 'Cloud Fundamentals' }] })
  assert.equal(sparse[0].issuer, null)
  assert.equal(sparse[0].date, null)
  assert.equal(sparse[0].statusLabel, null)

  // 'in_progress' is a live CHECK value, so it gets a real label.
  const pending = certificationEntries({ certifications: [{ name: 'X', status: 'in_progress' }] })
  assert.equal(pending[0].statusLabel, 'In progress')
})

// ── DIRECTION ──────────────────────────────────────────────────────────────

test('direction reports presence honestly for every partial shape', () => {
  assert.equal(careerDirection(RICH).present, true)
  assert.equal(careerDirection(EMPTY).present, false)
  assert.equal(careerDirection({ target_roles: ['AI Engineer'] }).present, true)
  assert.equal(careerDirection({ interests: ['Robotics'] }).present, true)
  assert.equal(careerDirection({ career_goals: 'Ship things.' }).present, true)
  // Blank strings are an absence, not a value.
  assert.equal(careerDirection({ career_goals: '   ', target_roles: ['  '] }).present, false)
})

// ── CASE B / C / D / E: realistic partial profiles ─────────────────────────

test('every realistic partial profile produces an intentional, non-empty shape', () => {
  const cases = {
    'skills only': { ...EMPTY, skills: { technical: ['Python'], soft: [], ai_exposure: null } },
    'work + projects, no goals': { ...EMPTY, work_experience: RICH.work_experience, projects: RICH.projects },
    'goals only': { ...EMPTY, target_roles: ['AI Engineer'], career_goals: 'Ship things.' },
    minimal: EMPTY,
  }
  for (const [label, career] of Object.entries(cases)) {
    const model = buildCareerViewModel(career)
    assert.equal(typeof model.empty, 'boolean', label)
    assert.ok(Array.isArray(model.skillGroups), label)
    assert.ok(Array.isArray(model.experience), label)
    assert.ok(Array.isArray(model.projects), label)
    assert.ok(Array.isArray(model.certifications), label)
  }
  assert.equal(buildCareerViewModel(cases['skills only']).empty, false)
  assert.equal(buildCareerViewModel(cases.minimal).empty, true)
})
