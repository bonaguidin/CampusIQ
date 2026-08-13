import { useAuth } from '../auth/useAuth';
import { analyzeFit } from '../api/analysis';
import { analysisFailureMessage, useAnalysisRun } from '../hooks/useAnalysisRun';
import type { FitAnalysisData, FitLevel, FitRoleMatch } from '../types/analysis';
import { AnalysisPanel, type AnalysisPhase } from './AnalysisPanel';

// FIT role-fit panel — data shape is fit.py's output_contract (role_matches[],
// overall_fit_summary). Confirmed against real (non-mocked) DeepSeek R1 output —
// see frontend/src/types/analysis.ts.
export function FitAnalysisPanel() {
  const { slug, session } = useAuth();
  const { state, trigger } = useAnalysisRun(() =>
    analyzeFit({ slug, accessToken: session?.access_token ?? null }),
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
      title="Role Fit (FIT)"
      invitation="See how well your profile matches your target roles — a fit level per role, why it fits, and what's still missing."
      phase={phase}
      onRun={trigger}
      missingFields={missingFields}
      failureMessage={analysisFailureMessage(state)}
    >
      {state.phase === 'done' && state.result.status === 'success' && (
        <FitResult data={state.result.data} summary={state.result.summary} />
      )}
    </AnalysisPanel>
  );
}

const FIT_LEVEL_LABEL: Record<FitLevel, string> = {
  high: 'High Fit',
  medium: 'Medium Fit',
  low: 'Low Fit',
};

function FitResult({ data, summary }: { data: FitAnalysisData; summary: string }) {
  if (data.role_matches.length === 0) {
    return <p className="empty-state">No role matches identified.</p>;
  }

  return (
    <div>
      <p className="gap-summary">{data.overall_fit_summary || summary}</p>

      <div className="theme-list">
        {data.role_matches.map((match, idx) => (
          <RoleMatchCard key={idx} match={match} />
        ))}
      </div>
    </div>
  );
}

function RoleMatchCard({ match }: { match: FitRoleMatch }) {
  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">{match.role}</span>
        <span className={`fit-badge fit-badge--${match.fit_level}`}>
          {FIT_LEVEL_LABEL[match.fit_level]}
        </span>
      </div>
      <p className="theme-summary">{match.rationale}</p>

      <div className="gap-columns">
        <div>
          <div className="gap-column-title">Why this fits</div>
          {match.supporting_signals.length > 0 ? (
            <ul className="gap-list">
              {match.supporting_signals.map((signal, idx) => (
                <li key={idx} className="gap-list-item gap-list-item--strength">
                  {signal}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-state">None identified.</p>
          )}
        </div>

        <div>
          <div className="gap-column-title">What's missing</div>
          {match.missing_signals.length > 0 ? (
            <ul className="gap-list">
              {match.missing_signals.map((signal, idx) => (
                <li key={idx} className="gap-list-item gap-list-item--must">
                  {signal}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-state">None identified.</p>
          )}
        </div>
      </div>
    </div>
  );
}
