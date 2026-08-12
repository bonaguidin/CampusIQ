/**
 * The value stored in students.major_intended for "I am not switching majors".
 *
 * MIRRORED, NOT SHARED. The authority for this string is `_NO_INTENDED_MAJOR`
 * in GradusIQ_career/features/fit.py, where FIT resolves around it to decide
 * whether a student is switching or staying. It is module-private Python and
 * crosses to this client only as an opaque string in the PATCH
 * /api/v2/student/me/profile body, so there is nothing here to import -- this
 * file restates it once, in one named place, instead of letting the literal
 * scatter through form code.
 *
 * The duplication is not left to good intentions: profileCompletion.test.mjs
 * reads fit.py and asserts the two still agree, the same way that suite
 * already asserts against shift.py's required_paths. If the Python value ever
 * changes, that test fails rather than FIT silently reclassifying every
 * staying student as switching.
 *
 * Note the API cannot take "" or null for this field -- _clean_profile_text
 * rejects a blank string with a 422, and an omitted key means "leave
 * untouched". Declining to switch majors is therefore a positive write of this
 * sentinel, not an erasure.
 */
export const NO_INTENDED_MAJOR = 'N/A';

/** True when a stored major_intended means "not switching", not a real major. */
export function isNoIntendedMajor(value: string | null | undefined): boolean {
  const trimmed = (value ?? '').trim();
  // fit.py compares with .upper(), so casing is not significant on read.
  return trimmed === '' || trimmed.toUpperCase() === NO_INTENDED_MAJOR;
}
