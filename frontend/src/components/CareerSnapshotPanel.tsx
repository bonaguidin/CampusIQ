import { analysisFailureMessage } from '../hooks/useAnalysisRun';
import { AnalysisPanel, type AnalysisPhase } from './AnalysisPanel';
import type { GapAnalysisRun } from './GapAnalysisPanel';
import type { FitAnalysisRun } from './FitAnalysisPanel';
import type { ShiftAnalysisRun } from './ShiftAnalysisPanel';

// Condensed cross-feature view for the Career tab's Snapshot sub-tab.
//
// Deliberately re-renders AnalysisPanel (not a copy of it) for the
// idle/loading/skipped/failed states, so a profile that's missing a field or
// mid-run looks and reads identically here and on its own sub-tab — only the
// 'success' state gets a condensed body instead of the full result view.
// gap/fit/shift are the same AnalysisRunState instances the Readiness/Role
// Fit/Trend Guidance sub-tabs render, lifted by the caller, so running an
// analysis from either place updates both.
interface CareerSnapshotPanelProps {
  gap: GapAnalysisRun;
  fit: FitAnalysisRun;
  shift: ShiftAnalysisRun;
  onViewFull(tab: 'gap' | 'fit' | 'shift'): void;
}

function phaseOf(state: { phase: string; result?: { status: string } }): AnalysisPhase {
  if (state.phase === 'idle') return 'idle';
  if (state.phase === 'loading') return 'loading';
  if (state.phase === 'transport-error') return 'failed';
  if (state.result?.status === 'skipped') return 'skipped';
  if (state.result?.status === 'failed') return 'failed';
  return 'success';
}

export function CareerSnapshotPanel({ gap, fit, shift, onViewFull }: CareerSnapshotPanelProps) {
  const gapMissing = gap.state.phase === 'done' ? gap.state.result.missing_fields ?? [] : [];
  const fitMissing = fit.state.phase === 'done' ? fit.state.result.missing_fields ?? [] : [];
  const shiftMissing = shift.state.phase === 'done' ? shift.state.result.missing_fields ?? [] : [];

  return (
    <div className="career-snapshot">
      <AnalysisPanel
        title="Readiness Check (GAP)"
        invitation="Run a readiness check against your target roles — see your GAP score, what's missing, and what to do next."
        phase={phaseOf(gap.state)}
        onRun={gap.trigger}
        missingFields={gapMissing}
        failureMessage={analysisFailureMessage(gap.state)}
      >
        {gap.state.phase === 'done' && gap.state.result.status === 'success' && (
          <SnapshotCardBody
            score={`${gap.state.result.data.readiness_score} / 10`}
            summary={gap.state.result.summary}
            onViewFull={() => onViewFull('gap')}
          />
        )}
      </AnalysisPanel>

      <AnalysisPanel
        title="Role Fit (FIT)"
        invitation="See how well your profile matches your target roles — a fit level per role, why it fits, and what's still missing."
        phase={phaseOf(fit.state)}
        onRun={fit.trigger}
        missingFields={fitMissing}
        failureMessage={analysisFailureMessage(fit.state)}
      >
        {fit.state.phase === 'done' && fit.state.result.status === 'success' && (
          <SnapshotCardBody
            summary={fit.state.result.data.overall_fit_summary || fit.state.result.summary}
            onViewFull={() => onViewFull('fit')}
          />
        )}
      </AnalysisPanel>

      <AnalysisPanel
        title="Trend Guidance (SHIFT)"
        invitation="See how your target roles are evolving — what's changing, what stays durable, and adjacent paths worth exploring."
        phase={phaseOf(shift.state)}
        onRun={shift.trigger}
        missingFields={shiftMissing}
        failureMessage={analysisFailureMessage(shift.state)}
      >
        {shift.state.phase === 'done' && shift.state.result.status === 'success' && (
          <SnapshotCardBody
            summary={shift.state.result.data.role_evolution_summary || shift.state.result.summary}
            onViewFull={() => onViewFull('shift')}
          />
        )}
      </AnalysisPanel>
    </div>
  );
}

function SnapshotCardBody({
  score,
  summary,
  onViewFull,
}: {
  score?: string;
  summary: string;
  onViewFull(): void;
}) {
  return (
    <div className="snapshot-card-body">
      {score && <div className="snapshot-score">{score}</div>}
      <p className="gap-summary">{summary}</p>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onViewFull}>
        View full analysis
      </button>
    </div>
  );
}
