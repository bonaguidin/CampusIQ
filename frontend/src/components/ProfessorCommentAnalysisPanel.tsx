import { useAuth } from '../auth/useAuth';
import { analyzeProfessorComments } from '../api/analysis';
import { useAnalysisRun } from '../hooks/useAnalysisRun';
import type { Theme } from '../types/analysis';
import { AnalysisPanel, type AnalysisPhase } from './AnalysisPanel';

// Professor Comment Analyzer panel — data shape is academic.py's
// output_contract (themes[], overall_summary). PROVISIONAL: unvalidated
// against a real (non-mocked) model response — see
// frontend/src/types/analysis.ts. Also carries the audit's scope assumption:
// this analyzes across ALL of the student's courses at once, not per course.
export function ProfessorCommentAnalysisPanel() {
  const { slug, session } = useAuth();
  const { state, trigger } = useAnalysisRun(() =>
    analyzeProfessorComments({ slug, accessToken: session?.access_token ?? null }),
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
      title="Professor Comment Analyzer"
      invitation="Analyze the feedback your professors have left across all your courses this term for recurring patterns and themes."
      phase={phase}
      onRun={trigger}
      missingFields={missingFields}
    >
      {state.phase === 'done' && state.result.status === 'success' && (
        <ThemeResult themes={state.result.data.themes} overallSummary={state.result.data.overall_summary} />
      )}
    </AnalysisPanel>
  );
}

const CATEGORY_LABEL: Record<Theme['category'], string> = {
  strength: 'Strength',
  concern: 'Concern',
  praise: 'Praise',
  flag: 'Flag',
};

function ThemeResult({ themes, overallSummary }: { themes: Theme[]; overallSummary: string }) {
  if (themes.length === 0) {
    return <p className="empty-state">No recurring themes found in your professor comments.</p>;
  }

  return (
    <div>
      <p className="gap-summary">{overallSummary}</p>

      <div className="theme-list">
        {themes.map((theme, idx) => (
          <div key={idx} className="theme-card">
            <div className="theme-header">
              <span className="theme-name">{theme.theme}</span>
              <span className={`theme-badge theme-badge--${theme.category}`}>
                {CATEGORY_LABEL[theme.category]}
              </span>
            </div>
            <p className="theme-summary">{theme.summary}</p>
            {theme.supporting_references.length > 0 && (
              <ul className="theme-refs">
                {theme.supporting_references.map((ref, refIdx) => (
                  <li key={refIdx} className="theme-ref">
                    <span className="theme-ref-course">{ref.course_code}</span>
                    {' — '}
                    {ref.paraphrase}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
