/**
 * Overview's "Top matched role" and "Biggest skill gap" cards each need one
 * entry picked out of a list that carries no priority/severity field to rank
 * by (see FitRoleMatch/GapMustHaveGap in types/analysis.ts -- role_matches,
 * must_have_gaps and nice_to_have_gaps are all unranked). Per product
 * decision, "top"/"biggest" means first in list order -- not a real
 * ranking, just a defined, deterministic pick.
 */

export function pickTopRole(fitData) {
  const matches = Array.isArray(fitData?.role_matches) ? fitData.role_matches : []
  return matches[0] ?? null
}

/**
 * must_have_gaps first, since a must-have outranks a nice-to-have by
 * definition; nice_to_have_gaps only when there are no must-haves at all.
 */
export function pickBiggestGap(gapData) {
  const mustHaves = Array.isArray(gapData?.must_have_gaps) ? gapData.must_have_gaps : []
  if (mustHaves.length > 0) return { ...mustHaves[0], priority: 'must' }
  const niceToHaves = Array.isArray(gapData?.nice_to_have_gaps) ? gapData.nice_to_have_gaps : []
  if (niceToHaves.length > 0) return { ...niceToHaves[0], priority: 'nice' }
  return null
}
