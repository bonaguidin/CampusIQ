import type { RequirementGroupResult } from '../api/requirementSatisfaction.mjs';

export interface RequirementProgressCount {
  satisfied: number;
  total: number;
}

export declare function countSatisfiedLeafGroups(
  groups: RequirementGroupResult[],
): RequirementProgressCount;
