import assert from 'node:assert/strict'
import test from 'node:test'

import {
  AGE_MINIMUM,
  INSTITUTIONS,
  ageInYears,
  isOldEnough,
  parseIsoDate,
  readSignupMetadata,
  todayIso,
  validateSignupForm,
} from '../src/lib/signupRules.mjs'

const TAMU = '75d68331-91d2-47e8-9671-2a3b065955d0'
const SMU = '6b180bbf-66d7-4aef-b8c6-2ae534c78e9a'

test('institution vocabulary is exactly the two real institutions', () => {
  assert.equal(INSTITUTIONS.length, 2)
  assert.deepEqual(
    INSTITUTIONS.map((i) => i.id),
    [TAMU, SMU],
  )
  assert.deepEqual(
    INSTITUTIONS.map((i) => i.name),
    ['Texas A&M University', 'Southern Methodist University'],
  )
})

test('parseIsoDate accepts real dates and rejects everything else', () => {
  assert.deepEqual(parseIsoDate('2000-01-31'), { year: 2000, month: 1, day: 31 })
  assert.deepEqual(parseIsoDate('  2000-01-31  '), { year: 2000, month: 1, day: 31 })
  assert.deepEqual(parseIsoDate('2008-02-29'), { year: 2008, month: 2, day: 29 }) // leap year

  // Impossible calendar dates, not merely malformed strings.
  assert.equal(parseIsoDate('2001-02-29'), null) // 2001 is not a leap year
  assert.equal(parseIsoDate('2001-02-30'), null)
  assert.equal(parseIsoDate('2001-13-01'), null)
  assert.equal(parseIsoDate('2001-00-10'), null)

  // Wrong shapes and wrong types.
  assert.equal(parseIsoDate('01/31/2000'), null)
  assert.equal(parseIsoDate('2000-1-31'), null)
  assert.equal(parseIsoDate(''), null)
  assert.equal(parseIsoDate(null), null)
  assert.equal(parseIsoDate(undefined), null)
  assert.equal(parseIsoDate(20000131), null)
  assert.equal(parseIsoDate({ year: 2000 }), null)
})

test('ageInYears counts whole years and respects the birthday boundary', () => {
  assert.equal(ageInYears('2008-08-03', '2026-08-03'), 18) // birthday today
  assert.equal(ageInYears('2008-08-04', '2026-08-03'), 17) // birthday tomorrow
  assert.equal(ageInYears('2008-08-02', '2026-08-03'), 18) // birthday yesterday
  assert.equal(ageInYears('2008-09-01', '2026-08-03'), 17) // later month this year
  assert.equal(ageInYears('2008-12-31', '2026-08-03'), 17)
  assert.equal(ageInYears('1990-01-01', '2026-08-03'), 36)

  // A future date of birth yields a negative age rather than throwing.
  assert.equal(ageInYears('2030-01-01', '2026-08-03'), -4)

  assert.equal(ageInYears('not-a-date', '2026-08-03'), null)
  assert.equal(ageInYears('2008-08-03', 'not-a-date'), null)
})

test('ageInYears handles a Feb 29 birthday in a non-leap year', () => {
  // The 18th birthday of a 2008-02-29 baby falls in 2026, which has no Feb 29.
  assert.equal(ageInYears('2008-02-29', '2026-02-28'), 17)
  assert.equal(ageInYears('2008-02-29', '2026-03-01'), 18)
})

test('isOldEnough gates on AGE_MINIMUM and fails closed on bad input', () => {
  assert.equal(AGE_MINIMUM, 18)
  assert.equal(isOldEnough('2008-08-03', '2026-08-03'), true)
  assert.equal(isOldEnough('2008-08-04', '2026-08-03'), false)
  assert.equal(isOldEnough('2020-01-01', '2026-08-03'), false)

  // Unparseable, missing, or future values are never "old enough".
  assert.equal(isOldEnough('', '2026-08-03'), false)
  assert.equal(isOldEnough(null, '2026-08-03'), false)
  assert.equal(isOldEnough('2001-02-30', '2026-08-03'), false)
  assert.equal(isOldEnough('2030-01-01', '2026-08-03'), false)
})

test('todayIso formats local calendar parts, zero-padded', () => {
  assert.equal(todayIso(new Date(2026, 0, 5)), '2026-01-05')
  assert.equal(todayIso(new Date(2026, 11, 31)), '2026-12-31')
  assert.match(todayIso(), /^\d{4}-\d{2}-\d{2}$/)
})

const VALID_FORM = {
  name: 'Ada Lovelace',
  email: 'ada@example.edu',
  password: 'correct-horse',
  institutionId: TAMU,
  dateOfBirth: '2000-05-05',
}

test('validateSignupForm accepts a complete adult submission', () => {
  assert.equal(validateSignupForm(VALID_FORM, '2026-08-03'), null)
  assert.equal(validateSignupForm({ ...VALID_FORM, institutionId: SMU }, '2026-08-03'), null)
})

test('validateSignupForm rejects each missing or invalid field', () => {
  assert.equal(validateSignupForm({ ...VALID_FORM, name: '   ' }, '2026-08-03'), 'Enter your full name.')
  assert.equal(validateSignupForm({ ...VALID_FORM, email: '' }, '2026-08-03'), 'Enter your email address.')
  assert.match(validateSignupForm({ ...VALID_FORM, password: 'short' }, '2026-08-03'), /at least 6/)
  assert.equal(
    validateSignupForm({ ...VALID_FORM, institutionId: 'some-other-school' }, '2026-08-03'),
    'Select your institution.',
  )
  assert.equal(
    validateSignupForm({ ...VALID_FORM, dateOfBirth: '' }, '2026-08-03'),
    'Enter your date of birth.',
  )
  assert.match(
    validateSignupForm({ ...VALID_FORM, dateOfBirth: '2001-02-30' }, '2026-08-03'),
    /real calendar date/,
  )
  assert.equal(validateSignupForm({}, '2026-08-03'), 'Enter your full name.')
})

test('validateSignupForm blocks under-18 submissions', () => {
  assert.match(
    validateSignupForm({ ...VALID_FORM, dateOfBirth: '2010-01-01' }, '2026-08-03'),
    /at least 18/,
  )
  // The day before the 18th birthday is still under age; the day of is not.
  assert.match(
    validateSignupForm({ ...VALID_FORM, dateOfBirth: '2008-08-04' }, '2026-08-03'),
    /at least 18/,
  )
  assert.equal(validateSignupForm({ ...VALID_FORM, dateOfBirth: '2008-08-03' }, '2026-08-03'), null)
})

test('validateSignupForm reports a missing date before an age failure', () => {
  // An empty field must not accuse the user of being underage.
  assert.equal(
    validateSignupForm({ ...VALID_FORM, dateOfBirth: '' }, '2026-08-03'),
    'Enter your date of birth.',
  )
})

test('readSignupMetadata returns the three fields when all are present', () => {
  assert.deepEqual(
    readSignupMetadata({
      name: '  Ada Lovelace  ',
      institution_id: TAMU,
      date_of_birth: '2000-05-05',
      email_verified: true,
    }),
    { name: 'Ada Lovelace', institutionId: TAMU, dateOfBirth: '2000-05-05' },
  )
})

test('readSignupMetadata returns null when this is not a sign-up session', () => {
  // Supabase always writes some metadata; a session with no sign-up behind it
  // has the bag but not our fields.
  assert.equal(readSignupMetadata({ email_verified: true }), null)
  assert.equal(readSignupMetadata({}), null)
  assert.equal(readSignupMetadata(null), null)
  assert.equal(readSignupMetadata(undefined), null)
  assert.equal(readSignupMetadata('nope'), null)
})

test('readSignupMetadata requires all three fields, not a partial bag', () => {
  const full = { name: 'Ada', institution_id: TAMU, date_of_birth: '2000-05-05' }
  assert.equal(readSignupMetadata({ ...full, name: '   ' }), null)
  assert.equal(readSignupMetadata({ ...full, institution_id: '' }), null)
  assert.equal(readSignupMetadata({ ...full, date_of_birth: undefined }), null)
  assert.equal(readSignupMetadata({ ...full, name: 42 }), null)
})

test('readSignupMetadata rejects a malformed institution id or date of birth', () => {
  const full = { name: 'Ada', institution_id: TAMU, date_of_birth: '2000-05-05' }
  assert.equal(readSignupMetadata({ ...full, institution_id: 'tamu' }), null)
  assert.equal(readSignupMetadata({ ...full, date_of_birth: '05/05/2000' }), null)
  assert.equal(readSignupMetadata({ ...full, date_of_birth: '2001-02-30' }), null)

  // A well-formed UUID that is not one of ours still passes this check -- the
  // foreign key on student_institutions.institution_id is the real authority.
  const unknown = { ...full, institution_id: '11111111-2222-3333-4444-555555555555' }
  assert.equal(readSignupMetadata(unknown)?.institutionId, '11111111-2222-3333-4444-555555555555')
})
