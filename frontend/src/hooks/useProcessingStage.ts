import { useEffect, useState } from 'react';
import { stageTimeouts } from '../lib/processingStages.mjs';

/**
 * Which presentational stage to show while a document parse is in flight.
 *
 * OWNS TIMERS AND NOTHING ELSE. It cannot report completion, cannot fail, and
 * has no opinion about the request -- `active` is handed to it by whoever owns
 * the upload, and the moment that goes false the schedule stops and the index
 * resets. That separation is the reason a stage can never be mistaken for
 * progress: this hook does not know what progress would be.
 *
 * ON CLEANUP. One timeout is scheduled per threshold rather than a chain, so a
 * slow frame cannot compound into drift across four stages. Every one of them
 * is cleared by the effect's cleanup, which React runs both when `active` flips
 * and when the component unmounts -- so no timer outlives the work it
 * describes, and no setState lands after unmount.
 */
export function useProcessingStage(active: boolean): number {
  const [stage, setStage] = useState(0);

  useEffect(() => {
    if (!active) {
      // Reset rather than freeze: the next upload is a new piece of work and
      // must start its story at the beginning, not resume the last one's.
      setStage(0);
      return;
    }

    const timers = stageTimeouts().map((delay, offset) =>
      window.setTimeout(() => {
        setStage(offset + 1);
      }, delay),
    );

    return () => {
      for (const timer of timers) window.clearTimeout(timer);
    };
  }, [active]);

  return stage;
}
