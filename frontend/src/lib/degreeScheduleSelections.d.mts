import type {
  PersistedRequirementSelectionIdentity,
  RequirementCandidate,
} from '../api/degreeSchedule.mjs';

export declare function selectionFromCandidate(
  requirementGroupId: string,
  candidate: RequirementCandidate,
): PersistedRequirementSelectionIdentity;

export declare function replaceRequirementSelection(
  currentSelections: PersistedRequirementSelectionIdentity[],
  requirementGroupId: string,
  candidate: RequirementCandidate,
): PersistedRequirementSelectionIdentity[];

export declare function removeRequirementSelection(
  currentSelections: PersistedRequirementSelectionIdentity[],
  requirementGroupId: string,
): PersistedRequirementSelectionIdentity[];

export declare function isCurrentRequirementCandidate(
  currentSelections: PersistedRequirementSelectionIdentity[],
  requirementGroupId: string,
  candidateId: string,
): boolean;

export declare function choiceConflictMessage(code: string): string;
