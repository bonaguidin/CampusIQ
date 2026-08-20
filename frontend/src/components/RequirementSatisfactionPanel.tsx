import { useAuth } from '../auth/useAuth';
import {
  fetchRequirementSatisfaction,
  isSkippedRequirementSatisfaction,
} from '../api/requirementSatisfaction';
import { useAnalysisRun } from '../hooks/useAnalysisRun';
import { AnalysisPanel, type AnalysisPhase } from './AnalysisPanel';
import { RequirementGroupNode } from './RequirementGroupNode';

// Sits directly under CourseDiscoveryPanel in the same Course Discovery
// sub-tab (see AuthenticatedDashboard.tsx) rather than a separate tab --
// requirement progress is read alongside course recommendations, not
// navigated to separately. Same useAnalysisRun/AnalysisPanel shell
// CourseDiscoveryPanel uses, so both panels behave identically on load,
// re-run, and error.
export function RequirementSatisfactionPanel() {
  const { session } = useAuth();
  const { state, trigger } = useAnalysisRun(() =>
    fetchRequirementSatisfaction(session?.access_token ?? ''),
  );

  // The success payload has no `status` field at all (see
  // api/requirementSatisfaction.ts) -- only the skipped path does, so phase
  // is derived from that rather than a uniform result.status check.
  const phase: AnalysisPhase =
    state.phase === 'idle'
      ? 'idle'
      : state.phase === 'loading'
        ? 'loading'
        : state.phase === 'transport-error'
          ? 'failed'
          : isSkippedRequirementSatisfaction(state.result)
            ? 'skipped'
            : 'success';

  const missingFields =
    state.phase === 'done' && isSkippedRequirementSatisfaction(state.result)
      ? state.result.missing_fields ?? []
      : [];

  // This route never returns a status: 'failed' FeatureResult (evaluation is
  // pure and has nothing analogous to a bad AI response to fail on) -- the
  // only failure phase this panel can reach is a transport error.
  const failureMessage = state.phase === 'transport-error' ? state.message : undefined;

  return (
    <AnalysisPanel
      title="Degree Requirements"
      invitation="See how your completed and in-progress courses stack up against your degree requirements."
      phase={phase}
      onRun={trigger}
      missingFields={missingFields}
      failureMessage={failureMessage}
    >
      {state.phase === 'done' && !isSkippedRequirementSatisfaction(state.result) && (
        state.result.groups.length > 0 ? (
          <ul className="requirement-tree">
            {state.result.groups.map((group) => (
              <RequirementGroupNode key={group.id} group={group} />
            ))}
          </ul>
        ) : (
          <p className="empty-state">No requirement groups are on record for your program yet.</p>
        )
      )}
    </AnalysisPanel>
  );
}
