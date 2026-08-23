import { isSkippedDegreeSchedule } from '../api/degreeSchedule.mjs';

export const DEFERRED_REASON_LABEL = {
  SELECTION_DEFERRED: 'Course selection needed',
  FREEFORM_MANUAL_REVIEW: 'Adviser review needed',
};

export const DEFERRED_REASON_DESCRIPTION = {
  SELECTION_DEFERRED: 'This requirement has multiple valid paths and is not selected automatically yet.',
  FREEFORM_MANUAL_REVIEW: 'Course options for this requirement are not automatically selected yet.',
};

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
