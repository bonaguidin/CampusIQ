import { createContext, useContext } from 'react';
import type { AnalysisRunState } from '../hooks/useAnalysisRun';
import type { TechnicalElectiveCandidateResponse } from '../api/technicalElectives.mjs';

/**
 * The shared technical-elective fetch result, read by any node in the
 * requirement tree that might be one of the matched elective-shaped groups.
 *
 * Fetched once at RequirementSatisfactionPanel (not per-node): SMU has one
 * matched group, TAMU has three sharing one pool, and neither is knowable
 * from a group's own fields (see technical_elective_group_matches() on the
 * backend -- TAMU's match depends on an institution-specific name allowlist
 * with no equivalent signal serialized to the frontend). A node can only
 * tell whether it participates by checking this fetched result's own
 * requirement_group_id / also_satisfies_requirement_groups.
 *
 * null is a supported value, same reasoning as ProfileCompletionContext:
 * it means "no provider above this node" (should not happen in practice,
 * RequirementSatisfactionPanel always provides one) or "not started yet" --
 * either way, every consumer already has to handle "nothing to show".
 */
export const TechnicalElectiveContext = createContext<
  AnalysisRunState<TechnicalElectiveCandidateResponse> | null
>(null);

export function useTechnicalElectiveMatch() {
  return useContext(TechnicalElectiveContext);
}
