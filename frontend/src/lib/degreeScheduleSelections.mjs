export function selectionFromCandidate(requirementGroupId, candidate) {
  return {
    requirement_group_id: requirementGroupId,
    candidate_id: candidate.candidate_id,
    course_codes: [...candidate.course_codes],
  };
}

export function replaceRequirementSelection(currentSelections, requirementGroupId, candidate) {
  const replacement = selectionFromCandidate(requirementGroupId, candidate);
  const next = currentSelections.filter(
    (selection) => selection.requirement_group_id !== requirementGroupId,
  );
  next.push(replacement);
  return next;
}

export function removeRequirementSelection(currentSelections, requirementGroupId) {
  return currentSelections.filter(
    (selection) => selection.requirement_group_id !== requirementGroupId,
  );
}

export function isCurrentRequirementCandidate(currentSelections, requirementGroupId, candidateId) {
  return currentSelections.some(
    (selection) => selection.requirement_group_id === requirementGroupId
      && selection.candidate_id === candidateId,
  );
}

export function choiceConflictMessage(code) {
  if (code === 'SCHEDULE_VERSION_CONFLICT') return 'Your degree plan changed while you were choosing. Review the updated options and try again.';
  if (code === 'ACADEMIC_REVISION_CONFLICT') return 'Your academic information changed while this choice was being saved. Review the updated plan and try again.';
  if (code === 'LOCK_CANDIDATE_EXCLUDED') return 'That option is no longer academically available. Review the updated alternatives.';
  if (code === 'LOCK_CANDIDATE_NOT_FOUND' || code === 'LOCK_PATH_MISMATCH') return 'That option changed since you opened the plan. Review the updated course choices.';
  if (code === 'LOCK_CHOICE_NO_LONGER_REQUIRED') return 'This requirement changed and no longer needs that choice.';
  if (code === 'LOCK_INCOMPATIBLE') return 'These course choices cannot all be used together in the current degree plan. Review one of your selected requirements and choose a different option.';
  if (code === 'RESELECTION_REQUIRED') return 'Your saved course choice needs attention before continuing.';
  return 'Your course choice could not be saved. Review the current plan and try again.';
}
