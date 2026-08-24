import type { FitAnalysisData, FitRoleMatch, GapAnalysisData, GapMustHaveGap } from '../types/analysis';

export declare function pickTopRole(fitData: FitAnalysisData | null | undefined): FitRoleMatch | null;

export type BiggestSkillGap = GapMustHaveGap & { priority: 'must' | 'nice' };

export declare function pickBiggestGap(gapData: GapAnalysisData | null | undefined): BiggestSkillGap | null;
