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
