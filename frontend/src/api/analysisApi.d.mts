import type {
  ActionPlanPreviewResponse,
  CourseDiscoveryData,
  FeatureResult,
  FitAnalysisData,
  GapAnalysisData,
  ProfessorCommentAnalysisData,
  ShiftAnalysisData,
} from '../types/analysis';

export interface AnalysisIdentity {
  slug: string | null;
  accessToken: string | null;
}

export declare function getCachedAnalysis<T>(
  feature: 'gap' | 'fit' | 'shift',
  accessToken: string,
): Promise<FeatureResult<T> | null>;

export declare function analyzeGap(identity: AnalysisIdentity): Promise<FeatureResult<GapAnalysisData>>;
export declare function analyzeFit(identity: AnalysisIdentity): Promise<FeatureResult<FitAnalysisData>>;
export declare function analyzeShift(identity: AnalysisIdentity): Promise<FeatureResult<ShiftAnalysisData>>;
export declare function analyzeProfessorComments(
  identity: AnalysisIdentity,
): Promise<FeatureResult<ProfessorCommentAnalysisData>>;
export declare function analyzeCourseDiscovery(
  identity: AnalysisIdentity,
  targetRole?: string | null,
): Promise<FeatureResult<CourseDiscoveryData>>;
export declare function analyzeActionPlan(
  identity: AnalysisIdentity,
  targetRole?: string | null,
): Promise<ActionPlanPreviewResponse>;
