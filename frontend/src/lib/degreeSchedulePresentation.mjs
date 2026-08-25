import { isSkippedDegreeSchedule } from '../api/degreeSchedule.mjs';

export function displayTermKey(termKey) {
  const match = /^(\d{4})-(Fall|Spring)$/.exec(termKey);
  return match ? `${match[2]} ${match[1]}` : termKey;
}

export function formatCredits(value) {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} credit${value === 1 ? '' : 's'}`;
}

// The backend order is authoritative. This helper deliberately maps without
// sorting so presentation tests can lock that contract down.
export function termPresentation(terms) {
  return terms.map((term) => ({
    ...term,
    displayName: displayTermKey(term.term_key),
    totalLabel: formatCredits(term.total_credit_hours),
  }));
}

export function degreeScheduleContentState(result) {
  if (isSkippedDegreeSchedule(result)) return 'skipped';
  if (result.status === 'ERROR') return 'infeasible';
  return result.terms.length === 0 ? 'empty' : 'scheduled';
}

export function nextPlannedTerm(schedule) {
  if (!schedule || isSkippedDegreeSchedule(schedule) || schedule.status !== 'SCHEDULED') return null;
  return termPresentation(schedule.terms)[0] ?? null;
}

export function adviserReviewCount(schedule) {
  if (!schedule || isSkippedDegreeSchedule(schedule) || schedule.status !== 'SCHEDULED') return null;
  return schedule.unscheduled.filter((item) => item.reason === 'FREEFORM_MANUAL_REVIEW').length;
}

const DECISION_ORDER = {
  LOCKED: 0,
  CHOICE_REQUIRED: 1,
  ADVISER_REVIEW: 2,
  DATA_UNRESOLVED: 3,
};

export function buildDegreeScheduleDecisions(schedule) {
  if (!schedule || isSkippedDegreeSchedule(schedule) || schedule.status !== 'SCHEDULED') {
    return { decisions: [], legacyRequirements: [] };
  }

  const candidateSets = new Map(
    (schedule.candidate_sets ?? []).map((candidateSet) => [candidateSet.requirement_group_id, candidateSet]),
  );
  const structuredIds = new Set((schedule.decisions ?? []).map((decision) => decision.requirement_group_id));

  const decisions = (schedule.decisions ?? [])
    .map((decision, index) => ({ decision, index }))
    .filter(({ decision }) => decision.state !== 'AUTO_SELECTED')
    .sort((left, right) => {
      const stateOrder = (DECISION_ORDER[left.decision.state] ?? 99) - (DECISION_ORDER[right.decision.state] ?? 99);
      return stateOrder || left.index - right.index;
    })
    .map(({ decision }) => {
      const candidateSet = candidateSets.get(decision.requirement_group_id);
      const feasibleById = new Map(
        (candidateSet?.feasible_candidates ?? []).map((candidate) => [candidate.candidate_id, candidate]),
      );
      const candidates = decision.feasible_candidate_ids
        .map((candidateId) => feasibleById.get(candidateId))
        .filter(Boolean);
      return {
        requirementGroupId: decision.requirement_group_id,
        requirementName: decision.requirement_name,
        state: decision.state,
        selectedCandidateId: decision.selected_candidate_id,
        candidates,
        validOptionLabel: `${candidates.length} valid option${candidates.length === 1 ? '' : 's'}`,
      };
    });

  const legacyRequirements = schedule.unscheduled.filter(
    (requirement) => !structuredIds.has(requirement.requirement_group_id),
  );

  return { decisions, legacyRequirements };
}
