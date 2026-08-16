import { useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { analyzeCourseDiscovery } from '../api/analysis';
import { analysisFailureMessage, useAnalysisRun } from '../hooks/useAnalysisRun';
import type {
  CourseDiscoveryData,
  VerifiedCourseRecommendation,
  PrerequisiteBlockedCourse,
  UnresolvedCourseCandidate,
  PrerequisiteEvaluation,
  CareerSkillNeed,
} from '../types/analysis';
import { AnalysisPanel, type AnalysisPhase } from './AnalysisPanel';

// Course Discovery panel — data shape is course_discovery/agent_models.py's
// CourseDiscoveryResult, mirrored in ../types/analysis.ts. Three typed
// outcomes (verified_recommendations, prerequisite_blocked,
// requires_verification), rendered as three visually distinct registers —
// see the file header comment in index.css's COURSE DISCOVERY block.
//
// Deliberately does not call /api/v2/student/me/action-plan or render any
// dependency-order/graph data — that is a separate, later unit. This panel
// only makes the Course Discovery result itself understandable.
export function CourseDiscoveryPanel({ targetRoles }: { targetRoles: string[] }) {
  const { slug, session } = useAuth();
  const [selectedRole, setSelectedRole] = useState(targetRoles[0] ?? '');
  const { state, trigger } = useAnalysisRun(() =>
    analyzeCourseDiscovery(
      { slug, accessToken: session?.access_token ?? null },
      targetRoles.length > 1 ? selectedRole : null,
    ),
  );

  const phase: AnalysisPhase =
    state.phase === 'idle'
      ? 'idle'
      : state.phase === 'loading'
        ? 'loading'
        : state.phase === 'transport-error'
          ? 'failed'
          : state.result.status === 'skipped'
            ? 'skipped'
            : state.result.status === 'failed'
              ? 'failed'
              : 'success';

  const missingFields = state.phase === 'done' ? state.result.missing_fields ?? [] : [];

  return (
    <AnalysisPanel
      title="Course Discovery"
      invitation="Find courses at your school that build the skills your target role needs."
      phase={phase}
      onRun={trigger}
      missingFields={missingFields}
      failureMessage={analysisFailureMessage(state)}
      headerExtra={
        targetRoles.length > 1 ? (
          <span className="course-discovery-role-select">
            <label htmlFor="course-discovery-target-role">Target role</label>
            <select
              id="course-discovery-target-role"
              value={selectedRole}
              onChange={(event) => setSelectedRole(event.target.value)}
            >
              {targetRoles.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </span>
        ) : undefined
      }
    >
      {state.phase === 'done' && state.result.status === 'success' && (
        <CourseDiscoveryResults data={state.result.data} summary={state.result.summary} />
      )}
    </AnalysisPanel>
  );
}

function CourseDiscoveryResults({ data, summary }: { data: CourseDiscoveryData; summary: string }) {
  const hasAny =
    data.verified_recommendations.length > 0 ||
    data.prerequisite_blocked.length > 0 ||
    data.requires_verification.length > 0;

  if (!hasAny) {
    return (
      <div>
        <p className="empty-state">No verified course recommendations found from the current evidence.</p>
        {summary && <p className="course-discovery-meta">{summary}</p>}
      </div>
    );
  }

  return (
    <div>
      {data.verified_recommendations.length > 0 && (
        <div className="course-discovery-section">
          <div className="course-discovery-section-title">Recommended courses</div>
          <div className="theme-list">
            {data.verified_recommendations.map((course) => (
              <VerifiedCourseCard key={`${course.institution}:${course.course_code}`} course={course} />
            ))}
          </div>
        </div>
      )}

      {data.prerequisite_blocked.length > 0 && (
        <div className="course-discovery-section">
          <div className="course-discovery-section-title">Courses to work toward</div>
          <div className="theme-list">
            {data.prerequisite_blocked.map((course) => (
              <PrerequisiteBlockedCard key={`${course.institution}:${course.course_code}`} course={course} />
            ))}
          </div>
        </div>
      )}

      {data.requires_verification.length > 0 && (
        <div className="course-discovery-section">
          <div className="course-discovery-section-title">Needs verification</div>
          <div className="theme-list">
            {data.requires_verification.map((course) => (
              <UnresolvedCourseCard key={`${course.institution}:${course.course_code}`} course={course} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MatchedNeeds({ needs }: { needs: CareerSkillNeed[] }) {
  if (needs.length === 0) return null;
  return (
    <div>
      <div className="gap-column-title">Matches</div>
      <ul className="gap-list">
        {needs.map((need) => (
          <li key={need.need_id} className="gap-list-item gap-list-item--strength">
            {need.skill}
          </li>
        ))}
      </ul>
    </div>
  );
}

function creditLabel(min: number, max: number): string {
  const unit = min === 1 && max === 1 ? 'credit hour' : 'credit hours';
  return min === max ? `${min} ${unit}` : `${min}–${max} ${unit}`;
}

function VerifiedCourseCard({ course }: { course: VerifiedCourseRecommendation }) {
  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">
          {course.course_code} — {course.title}
        </span>
        <span className="course-discovery-status-badge course-discovery-status-badge--ready">
          Ready to consider
        </span>
      </div>
      <p className="theme-summary">{course.ranking_reason}</p>
      {course.skill_alignment_explanation && (
        <p className="theme-summary">{course.skill_alignment_explanation}</p>
      )}
      <MatchedNeeds needs={course.matched_needs} />
      <p className="course-discovery-meta">
        {creditLabel(course.credit_min, course.credit_max)}
        {' · '}
        <a href={course.provenance.source_url} target="_blank" rel="noreferrer">
          Catalog source
        </a>
      </p>
    </div>
  );
}

// missing/in_progress/planned/unknown are mutually exclusive per prerequisite
// code (see PrerequisiteEvaluation in GradusIQ_career/course_discovery/models.py)
// — a code appears in at most one of these lists.
const PREREQ_STATUS_LABEL: Record<string, string> = {
  missing: 'Not yet started',
  in_progress: 'In progress',
  planned: 'Planned',
  unknown: 'Status unclear',
};

function prerequisiteStatusFor(evaluation: PrerequisiteEvaluation, code: string): string {
  if (evaluation.missing_courses.includes(code)) return 'missing';
  if (evaluation.in_progress_courses.includes(code)) return 'in_progress';
  if (evaluation.planned_courses.includes(code)) return 'planned';
  if (evaluation.unknown_courses.includes(code)) return 'unknown';
  return 'unknown';
}

function PrerequisiteList({ evaluation }: { evaluation: PrerequisiteEvaluation }) {
  const { requirement } = evaluation;
  const outstanding = [
    ...evaluation.missing_courses,
    ...evaluation.in_progress_courses,
    ...evaluation.planned_courses,
    ...evaluation.unknown_courses,
  ];

  if (outstanding.length === 0) {
    // ANY-mode with every alternative unresolved some other way, or an
    // UNRESOLVED grammar the backend could not safely parse into codes —
    // never invented; falls back to whatever course_codes evidence exists.
    if (requirement.course_codes.length === 0) return null;
    return (
      <p className="course-discovery-meta">
        Prerequisite: {requirement.course_codes.join(requirement.mode === 'ANY' ? ' or ' : ' and ')}
      </p>
    );
  }

  const connector = requirement.mode === 'ANY' && outstanding.length > 1 ? ' — one of the following' : '';

  return (
    <div>
      <p className="course-discovery-meta">Prerequisite needed{connector}:</p>
      <ul className="course-discovery-prereqs">
        {outstanding.map((code) => {
          const status = prerequisiteStatusFor(evaluation, code);
          return (
            <li key={code} className="course-discovery-prereq">
              <span className="course-discovery-prereq-code">{code}</span>
              <span className="course-discovery-prereq-status">{PREREQ_STATUS_LABEL[status]}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function PrerequisiteBlockedCard({ course }: { course: PrerequisiteBlockedCourse }) {
  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">
          {course.course_code} — {course.title}
        </span>
        <span className="course-discovery-status-badge course-discovery-status-badge--blocked">
          Not yet actionable
        </span>
      </div>
      <p className="theme-summary">Relevant to your target role — another course comes first.</p>
      <MatchedNeeds needs={course.matched_needs} />
      {course.prerequisite_evaluation && <PrerequisiteList evaluation={course.prerequisite_evaluation} />}
    </div>
  );
}

function UnresolvedCourseCard({ course }: { course: UnresolvedCourseCandidate }) {
  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">
          {course.course_code} — {course.title}
        </span>
        <span className="course-discovery-status-badge course-discovery-status-badge--verify">
          Needs verification
        </span>
      </div>
      <p className="theme-summary">
        Course Discovery could not safely confirm this course from current evidence.
      </p>
      <MatchedNeeds needs={course.matched_needs} />
    </div>
  );
}
