import { useCallback, useState } from 'react';
import type { FeatureResult } from '../types/analysis';

// Distinguishes transport failures (network/HTTP — "AI call failed, try
// again") from a successful call whose FeatureResult.status is "skipped"
// (profile incomplete) or "failed" (AI ran but errored/parsed badly) —
// the two panels render each of these differently.
export type AnalysisRunState<T> =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'done'; result: FeatureResult<T> }
  | { phase: 'transport-error'; message: string };

/**
 * The sentence to show when a run fails, or undefined when it did not fail.
 *
 * Both failure routes collapse to AnalysisPhase 'failed' -- the phase vocabulary
 * is deliberately left alone, since FIT/GAP/SHIFT's status contract was hardened
 * separately and a new phase would reopen it. What was missing is not a phase
 * but the reason, which existed on both routes and was thrown away at render:
 *
 *   transport-error -- HTTP never returned a FeatureResult (rate limit, busy
 *                      gate, 502). `message` is now the server's own detail.
 *   status 'failed' -- the call succeeded and the analysis itself failed. Its
 *                      summary/errors say why (bad JSON, contract violation).
 *
 * Lives here rather than in each panel so the four of them cannot drift.
 */
export function analysisFailureMessage<T>(state: AnalysisRunState<T>): string | undefined {
  if (state.phase === 'transport-error') return state.message;
  if (state.phase !== 'done' || state.result.status !== 'failed') return undefined;
  const errors = state.result.errors ?? [];
  return errors.length > 0 ? errors.join(' ') : state.result.summary || undefined;
}

export function useAnalysisRun<T>(run: () => Promise<FeatureResult<T>>) {
  const [state, setState] = useState<AnalysisRunState<T>>({ phase: 'idle' });

  const trigger = useCallback(() => {
    setState({ phase: 'loading' });
    run()
      .then((result) => setState({ phase: 'done', result }))
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Request failed.';
        setState({ phase: 'transport-error', message });
      });
  }, [run]);

  return { state, trigger };
}
