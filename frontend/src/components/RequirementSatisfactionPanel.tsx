import { useCallback, useEffect, useRef } from 'react';
import { useAuth } from '../auth/useAuth';
import {
  fetchRequirementSatisfaction,
  isSkippedRequirementSatisfaction,
  type RequirementSatisfactionResponse,
} from '../api/requirementSatisfaction.mjs';
import { fetchTechnicalElectiveCandidates } from '../api/technicalElectives.mjs';
import { useAnalysisRun } from '../hooks/useAnalysisRun';
import { RequirementGroupNode } from './RequirementGroupNode';
import { TechnicalElectiveContext } from './TechnicalElectiveContext';

// Sits directly under CourseDiscoveryPanel in the same Course Discovery
// sub-tab (see AuthenticatedDashboard.tsx) rather than a separate tab --
// requirement progress is read alongside course recommendations, not
// navigated to separately. Same useAnalysisRun/AnalysisPanel shell
// CourseDiscoveryPanel uses, so both panels behave identically on load,
// re-run, and error.
export function RequirementSatisfactionPanel({
  onResult,
}: {
  onResult?: (result: RequirementSatisfactionResponse) => void;
}) {
  // Same { slug, session } shared AuthContext CourseDiscoveryPanel already
  // reads -- no caller-supplied identity prop needed.
  const { slug, session } = useAuth();
  const accessToken = session?.access_token ?? null;
  const load = useCallback(
    () => fetchRequirementSatisfaction({ slug, accessToken }),
    [slug, accessToken],
  );
  const { state, trigger } = useAnalysisRun(load);

  // Fetched once here rather than per-node (TechnicalElectiveSlot, mounted
  // under every group in the tree below): which group(s) this pool belongs
  // to is only knowable from the fetched result itself (institution-specific
  // matching happens server-side), so nodes cannot each decide independently
  // without each re-fetching the identical answer. Loading/error states are
  // handled here, not per-node -- see TechnicalElectiveSlot's own comment.
  const loadTechnicalElectives = useCallback(
    () => fetchTechnicalElectiveCandidates({ slug, accessToken }),
    [slug, accessToken],
  );
  const technicalElectives = useAnalysisRun(loadTechnicalElectives);

  const technicalElectivesTrigger = technicalElectives.trigger;
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    trigger();
    technicalElectivesTrigger();
  }, [trigger, technicalElectivesTrigger]);

  // The panel's existing refresh button now retries both fetches together --
  // one control, not two, and it means a failed technical-electives fetch
  // is recoverable the same way a failed requirement-satisfaction fetch
  // already was, without a second retry affordance buried in the tree.
  const refresh = useCallback(() => {
    trigger();
    technicalElectivesTrigger();
  }, [trigger, technicalElectivesTrigger]);

  useEffect(() => {
    if (state.phase === 'done') onResult?.(state.result);
  }, [onResult, state]);

  const skipped = state.phase === 'done' && isSkippedRequirementSatisfaction(state.result)
    ? state.result
    : null;

  return (
    <section className="card requirement-satisfaction-panel" aria-labelledby="degree-requirements-title">
      <div className="editable-section-header">
        <div>
          <h3 id="degree-requirements-title" className="editable-section-title">Degree Requirements</h3>
          <p className="requirement-satisfaction-subtitle">Completed and in-progress coursework counted toward your degree.</p>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={refresh} disabled={state.phase === 'loading'} aria-busy={state.phase === 'loading'}>
          {state.phase === 'loading' ? 'Checking…' : 'Refresh degree progress'}
        </button>
      </div>

      {(state.phase === 'idle' || state.phase === 'loading') && (
        <div className="analysis-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <p>Checking degree requirements…</p>
        </div>
      )}

      {state.phase === 'transport-error' && (
        <div className="analysis-failed"><p>{state.message}</p></div>
      )}

      {skipped && <div className="analysis-skipped"><p>{skipped.summary}</p></div>}

      {state.phase === 'done' && !isSkippedRequirementSatisfaction(state.result) && (
        state.result.groups.length > 0 ? (
          <TechnicalElectiveContext.Provider value={technicalElectives.state}>
            <ul className="requirement-tree">
              {state.result.groups.map((group) => (
                <RequirementGroupNode key={group.id} group={group} />
              ))}
            </ul>
          </TechnicalElectiveContext.Provider>
        ) : (
          <p className="empty-state">No requirement groups are on record for your program yet.</p>
        )
      )}
    </section>
  );
}
