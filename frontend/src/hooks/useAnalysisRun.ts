import { useCallback, useState } from 'react';

// Distinguishes transport failures (network/HTTP — "AI call failed, try
// again") from a successful call whose result.status is "skipped" (profile
// incomplete) or "failed" (AI ran but errored/parsed badly) — panels render
// each of these differently.
//
// TResult is the whole resolved value, not a payload nested inside it. Every
// existing caller passes a function returning Promise<FeatureResult<X>>, so
// TResult is inferred as FeatureResult<X> there and nothing about those call
// sites changes. This exists so a result shape that is NOT a FeatureResult
// (the Action Plan preview response has action_plan/dependency_order in
// place of FeatureResult's data/errors/missing_fields) can use the same run
// state machine without a parallel hook.
export type AnalysisRunState<TResult> =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'done'; result: TResult }
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
interface FailableResult {
  status: string;
  summary: string;
  errors?: string[];
}

export function analysisFailureMessage<TResult extends FailableResult>(
  state: AnalysisRunState<TResult>,
): string | undefined {
  if (state.phase === 'transport-error') return state.message;
  if (state.phase !== 'done' || state.result.status !== 'failed') return undefined;
  const errors = state.result.errors ?? [];
  return errors.length > 0 ? errors.join(' ') : state.result.summary || undefined;
}

export function useAnalysisRun<TResult>(run: () => Promise<TResult>) {
  const [state, setState] = useState<AnalysisRunState<TResult>>({ phase: 'idle' });

  const trigger = useCallback(() => {
    setState({ phase: 'loading' });
    run()
      .then((result) => setState({ phase: 'done', result }))
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Request failed.';
        setState({ phase: 'transport-error', message });
      });
  }, [run]);

  const replaceResult = useCallback((result: TResult) => {
    setState({ phase: 'done', result });
  }, []);

  return { state, trigger, replaceResult };
}
