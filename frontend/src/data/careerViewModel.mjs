// Presentation shaping for the authenticated Career profile.
//
// EVERY VALUE HERE COMES OUT OF THE CANONICAL PROFILE. Nothing is scored,
// ranked, predicted, or classified. The only things this module manufactures
// are (a) counts of arrays the profile already contains and (b) a truncation of
// a description the profile already contains -- both of which are facts about
// the data rather than claims about the student. The canonical
// StudentIntelligenceProfile remains authoritative for everything else.
//
// WHY IT EXISTS AT ALL. `CanonicalCareer`'s child items are deliberately loose
// (`{ source?: string | null, [key: string]: unknown }`) because they are
// pass-through database rows -- profile_builder.py strips the DB bookkeeping
// columns and validates nothing else. Reading `item.employer` straight in JSX
// therefore means every component re-implements "is this a usable string or is
// it null/''/undefined/a number", and they will not all agree. This does it
// once, so a missing field is uniformly an absence rather than the string
// "undefined" on someone's screen.
//
// The field names below mirror resume/review.py's EDITABLE_FIELDS exactly (see
// REVIEW_SECTIONS in resumeApi.mjs, which is the same list): certifications
// carry name/issuer/status/date, work_experience carries employer/role/
// duration/location/description/skills_gained, projects carry name/timeframe/
// description/tools. Nothing outside those lists is read, because nothing
// outside them is guaranteed to exist.

/**
 * How much of a description to show before offering "View details".
 *
 * A PRESENTATIONAL TRUNCATION OF THE STUDENT'S OWN TEXT -- never a summary.
 * Resume descriptions routinely run several hundred characters, and pasting
 * them whole into the dashboard is what made the old Career page read as a
 * résumé dump. The full original is always one button away and byte-identical;
 * nothing is rewritten, condensed, or regenerated.
 */
export const DESCRIPTION_PREVIEW_LIMIT = 180;

/** How many skills to show before collapsing the rest behind "Show N more". */
export const SKILL_PREVIEW_COUNT = 18;

/** A usable string from a loose canonical row, or null. */
export function text(item, key) {
  const value = item?.[key];
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
}

/** A list of usable strings from a loose canonical row. Always an array. */
export function list(item, key) {
  const value = item?.[key];
  if (!Array.isArray(value)) return [];
  return value
    .filter((entry) => typeof entry === 'string')
    .map((entry) => entry.trim())
    .filter((entry) => entry !== '');
}

/**
 * Cut `body` to a whole word at or under the limit.
 *
 * Returns the original when it already fits, so a short description is never
 * given a misleading ellipsis, and `truncated` says which happened rather than
 * leaving callers to compare lengths themselves.
 */
export function previewOf(body, limit = DESCRIPTION_PREVIEW_LIMIT) {
  if (typeof body !== 'string') return { preview: null, truncated: false };
  const trimmed = body.trim();
  if (trimmed === '') return { preview: null, truncated: false };
  if (trimmed.length <= limit) return { preview: trimmed, truncated: false };

  const cut = trimmed.slice(0, limit);
  const lastSpace = cut.lastIndexOf(' ');
  // Fall back to the hard cut for text with no spaces in range (a URL, say)
  // rather than emitting an empty preview.
  const head = (lastSpace > limit * 0.6 ? cut.slice(0, lastSpace) : cut).replace(/[\s,;:.–—-]+$/, '');
  return { preview: `${head}…`, truncated: true };
}

/**
 * Skill groups.
 *
 * THE SPLIT IS CANONICAL, NOT INVENTED. `skills_technical` and `skills_soft`
 * are two separate columns on career_profiles and two separate fields on the
 * contract, so grouping by them is reporting what the data already says.
 *
 * Deliberately NOT grouped any further. Sorting names into "AI & Machine
 * Learning" or "Data / Analytics" would require classifying skill strings, and
 * a keyword table that decides "Python is Engineering, PyTorch is AI" is a
 * judgement the profile never made -- it would look canonical on screen while
 * being a guess in the source. Within each real group the chips are a flat,
 * scannable set, which solves the comma-wall problem without inventing
 * taxonomy.
 */
export function skillGroups(career) {
  const technical = list(career?.skills, 'technical');
  const soft = list(career?.skills, 'soft');
  return [
    { key: 'technical', label: 'Technical', skills: technical },
    { key: 'soft', label: 'Soft skills', skills: soft },
  ].filter((group) => group.skills.length > 0);
}

/** Experience entries, in canonical order, carrying only fields present. */
export function experienceEntries(career) {
  return (career?.work_experience ?? []).map((item, index) => {
    const description = text(item, 'description');
    const { preview, truncated } = previewOf(description);
    return {
      key: `${text(item, 'employer') ?? 'experience'}-${String(index)}`,
      employer: text(item, 'employer'),
      role: text(item, 'role'),
      // Never substituted. A missing duration renders nothing at all rather
      // than "Dates unknown", which would look like a fact we established.
      duration: text(item, 'duration'),
      location: text(item, 'location'),
      description,
      preview,
      truncated,
      skills: list(item, 'skills_gained'),
    };
  });
}

/** Project entries, in canonical order. `tools` is a real structured field. */
export function projectEntries(career) {
  return (career?.projects ?? []).map((item, index) => {
    const description = text(item, 'description');
    const { preview, truncated } = previewOf(description);
    return {
      key: `${text(item, 'name') ?? 'project'}-${String(index)}`,
      name: text(item, 'name'),
      timeframe: text(item, 'timeframe'),
      description,
      preview,
      truncated,
      tools: list(item, 'tools'),
    };
  });
}

/**
 * Certification entries.
 *
 * `status` is constrained to 'completed' | 'in_progress' by a live CHECK on the
 * table, so rendering it as a credential state reports a real column rather
 * than inferring anything. Any other value is passed through untouched.
 */
export function certificationEntries(career) {
  return (career?.certifications ?? []).map((item, index) => {
    const status = text(item, 'status');
    return {
      key: `${text(item, 'name') ?? 'certification'}-${String(index)}`,
      name: text(item, 'name'),
      issuer: text(item, 'issuer'),
      date: text(item, 'date'),
      status,
      statusLabel: status === 'in_progress' ? 'In progress' : status === 'completed' ? 'Completed' : status,
    };
  });
}

/**
 * Career direction, field by field.
 *
 * PRESENCE IS PER FIELD, NOT PER SECTION. `present` used to be the only answer
 * this returned, and the page gated the whole of Career direction on it: a
 * student with interests but no target roles satisfied the boolean, so the
 * page rendered the interests and said nothing whatsoever about the roles --
 * the one field FIT, GAP and SHIFT all require went missing silently, and the
 * absence treatment only ever appeared for someone who had provided none of
 * the four. `hasTargetRoles` and `hasInterests` let each field state its own
 * absence.
 *
 * `present` is kept, unchanged, because `empty` below is a claim about the
 * whole profile rather than about any one field, and that is still the
 * question it answers. Goals and location are deliberately not given their own
 * flags: they render when they exist and are silent when they do not, which is
 * what they already did.
 */
export function careerDirection(career) {
  const targetRoles = Array.isArray(career?.target_roles)
    ? career.target_roles.filter((r) => typeof r === 'string' && r.trim()).map((r) => r.trim())
    : [];
  const interests = Array.isArray(career?.interests)
    ? career.interests.filter((i) => typeof i === 'string' && i.trim()).map((i) => i.trim())
    : [];
  const goals = text(career, 'career_goals');
  const location = text(career, 'geographic_preference');
  return {
    targetRoles,
    interests,
    goals,
    location,
    hasTargetRoles: targetRoles.length > 0,
    hasInterests: interests.length > 0,
    present: targetRoles.length > 0 || interests.length > 0 || goals !== null || location !== null,
  };
}

/**
 * The whole Career page, shaped.
 *
 * `counts` are array lengths and nothing more -- there is no weighting, no
 * score, and no percentage anywhere in this module.
 */
export function buildCareerViewModel(career) {
  const groups = skillGroups(career);
  const experience = experienceEntries(career);
  const projects = projectEntries(career);
  const certifications = certificationEntries(career);
  const direction = careerDirection(career);
  const skillTotal = groups.reduce((total, group) => total + group.skills.length, 0);

  return {
    confirmed: career?.confirmed === true,
    direction,
    skillGroups: groups,
    experience,
    projects,
    certifications,
    counts: {
      skills: skillTotal,
      experience: experience.length,
      projects: projects.length,
      certifications: certifications.length,
    },
    /** Whether anything at all was confirmed, so the page can say so plainly. */
    empty:
      !direction.present &&
      skillTotal === 0 &&
      experience.length === 0 &&
      projects.length === 0 &&
      certifications.length === 0,
  };
}
