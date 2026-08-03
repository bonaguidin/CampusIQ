// Pure sign-up rules: no React, no network, no Supabase. Plain .mjs on purpose
// -- the frontend has no test runner beyond `node --test tests/*.test.mjs`
// (package.json "test"), and that pattern can only import runtime JS. Keeping
// these two decisions (who is old enough, and what counts as a completed
// sign-up) in a directly-importable module is what makes them testable at all.
// Types for TS callers live alongside in signupRules.d.mts.

/** Minimum age to hold an account. Checked client-side before signUp() is called. */
export const AGE_MINIMUM = 18;

/**
 * The institution picker's entire vocabulary. These are the real
 * `institutions.id` UUIDs from the live database (verified in the audit
 * preceding this task), not placeholders -- student_institutions.institution_id
 * carries a foreign key to institutions(id), so an invented value would be
 * rejected at insert time rather than silently stored.
 */
export const INSTITUTIONS = [
  { id: '75d68331-91d2-47e8-9671-2a3b065955d0', name: 'Texas A&M University' },
  { id: '6b180bbf-66d7-4aef-b8c6-2ae534c78e9a', name: 'Southern Methodist University' },
];

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Parse a `YYYY-MM-DD` string into calendar parts, or null if it is not a real
 * date. Deliberately does NOT use `new Date(string)`: that parses a bare
 * date-only string as UTC midnight, so in any negative-offset timezone
 * `getFullYear()` returns the previous day locally -- which would shift a
 * birthday by one day and flip the 18th-birthday boundary for anyone born on
 * the 1st. Comparing calendar parts as integers has no timezone in it at all.
 */
export function parseIsoDate(value) {
  if (typeof value !== 'string') return null;
  const match = ISO_DATE.exec(value.trim());
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);

  // Rejects 2001-02-30 and friends: round-tripping through UTC normalizes an
  // impossible day into the next month, so a mismatch means it never existed.
  const probe = new Date(Date.UTC(year, month - 1, day));
  if (
    probe.getUTCFullYear() !== year ||
    probe.getUTCMonth() !== month - 1 ||
    probe.getUTCDate() !== day
  ) {
    return null;
  }
  return { year, month, day };
}

/** Today as `YYYY-MM-DD` in the viewer's own timezone, for use as `todayValue`. */
export function todayIso(now = new Date()) {
  const year = String(now.getFullYear()).padStart(4, '0');
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Whole years elapsed from `dobValue` to `todayValue`, or null if either date
 * is unparseable. A birthday later in the current year has not happened yet, so
 * it costs a year. A future date of birth yields a negative age rather than
 * throwing -- callers reject it via the same `>= AGE_MINIMUM` comparison.
 */
export function ageInYears(dobValue, todayValue) {
  const dob = parseIsoDate(dobValue);
  const today = parseIsoDate(todayValue);
  if (!dob || !today) return null;

  let age = today.year - dob.year;
  if (today.month < dob.month || (today.month === dob.month && today.day < dob.day)) {
    age -= 1;
  }
  return age;
}

/**
 * The gate the sign-up form applies BEFORE calling signUp(). An unparseable or
 * missing date is not old enough -- failing closed here means a malformed value
 * can never reach account creation.
 */
export function isOldEnough(dobValue, todayValue) {
  const age = ageInYears(dobValue, todayValue);
  return age !== null && age >= AGE_MINIMUM;
}

/**
 * Validate the whole form. Returns null when submittable, otherwise the single
 * message to show. Order matters: the age rule is checked last so that an
 * empty-date user is told the field is required rather than accused of being
 * underage.
 */
export function validateSignupForm(fields, todayValue) {
  const name = typeof fields.name === 'string' ? fields.name.trim() : '';
  const email = typeof fields.email === 'string' ? fields.email.trim() : '';
  const password = typeof fields.password === 'string' ? fields.password : '';
  const institutionId = typeof fields.institutionId === 'string' ? fields.institutionId : '';
  const dateOfBirth = typeof fields.dateOfBirth === 'string' ? fields.dateOfBirth.trim() : '';

  if (!name) return 'Enter your full name.';
  if (!email) return 'Enter your email address.';
  if (password.length < 6) return 'Choose a password of at least 6 characters.';
  if (!INSTITUTIONS.some((institution) => institution.id === institutionId)) {
    return 'Select your institution.';
  }
  if (!dateOfBirth) return 'Enter your date of birth.';
  if (parseIsoDate(dateOfBirth) === null) return 'Enter your date of birth as a real calendar date.';
  if (!isOldEnough(dateOfBirth, todayValue)) {
    return `You must be at least ${AGE_MINIMUM} to create an account.`;
  }
  return null;
}

/**
 * Read the three fields sign-up wrote into `user_metadata`, or null if this is
 * not a session with a sign-up behind it.
 *
 * This is the load-bearing distinction on the provisioning path: a 404 from
 * /api/v2/student/me/profile means "no students row", which is either a first
 * confirmed login (metadata present -> provision) or a session that never went
 * through this form (metadata absent -> surface "no profile", never guess a
 * name or an institution on the user's behalf).
 *
 * All three must be present -- `students.name` is NOT NULL and
 * student_institutions needs a real institution_id, so a partial bag cannot
 * produce a valid pair of rows. institution_id is shape-checked as a UUID only;
 * the foreign key to institutions(id) remains the actual authority, since
 * user_metadata is client-supplied and a signUp() call made outside this form
 * could put anything there.
 */
export function readSignupMetadata(metadata) {
  if (!metadata || typeof metadata !== 'object') return null;

  const name = typeof metadata.name === 'string' ? metadata.name.trim() : '';
  const institutionId =
    typeof metadata.institution_id === 'string' ? metadata.institution_id.trim() : '';
  const dateOfBirth =
    typeof metadata.date_of_birth === 'string' ? metadata.date_of_birth.trim() : '';

  if (!name || !institutionId || !dateOfBirth) return null;
  if (!UUID.test(institutionId)) return null;
  if (parseIsoDate(dateOfBirth) === null) return null;

  return { name, institutionId, dateOfBirth };
}
