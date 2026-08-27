import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import {
  DegreeScheduleChoiceError,
  fetchDegreeSchedule,
  isSkippedDegreeSchedule,
  updateDegreeScheduleChoices,
  type DegreeScheduleResponse,
  type RequirementCandidate,
} from '../api/degreeSchedule.mjs';
import { useAuth } from '../auth/useAuth';
import { useAnalysisRun } from '../hooks/useAnalysisRun';
import {
  degreeScheduleContentState,
} from '../lib/degreeSchedulePresentation.mjs';
import { CareerOptimizationPanel } from './CareerOptimizationPanel';
import { DegreeScheduleTerms } from './DegreeScheduleTerms';
import { DegreeScheduleYears } from './DegreeScheduleYears';
import { DegreeScheduleDecisionSection } from './DegreeScheduleDecisionSection';
import {
  choiceConflictMessage,
  removeRequirementSelection,
  replaceRequirementSelection,
} from '../lib/degreeScheduleSelections.mjs';

interface CourseRecordLike {
  id: string;
  term_id: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number | string;
  letter_grade: string | null;
  status: string;
}

export function DegreeSchedulePanel({
  targetRole,
  courses = [],
  onResult,
}: {
  targetRole?: string;
  // Only consumed by the authenticated (DegreeScheduleYears) branch below --
  // demo identities render the simpler DegreeScheduleTerms instead and never
  // need this, since DegreeScheduleYears itself calls session-scoped
  // /me/terms and /me/grading-schema with no demo counterpart.
  courses?: CourseRecordLike[];
  onResult?: (result: DegreeScheduleResponse) => void;
}) {
  // Same { slug, session } shared AuthContext CourseDiscoveryPanel already
  // reads: slug is set only for the demo picker, session only for a real
  // signed-in student, so identity here needs no caller-supplied prop.
  const { slug, session } = useAuth();
  const accessToken = session?.access_token ?? null;
  const identity = { slug, accessToken };
  const load = useCallback(() => fetchDegreeSchedule(identity), [slug, accessToken]);
  const { state, trigger, replaceResult } = useAnalysisRun(load);
  const [choiceMutation, setChoiceMutation] = useState<{
    requirementGroupId: string;
    action: 'choose' | 'change' | 'clear';
    candidateId?: string;
  } | null>(null);
  const [choiceMessage, setChoiceMessage] = useState<string | null>(null);
  const mutationInFlight = useRef(false);

  useEffect(() => { trigger(); }, [trigger]);

  useEffect(() => {
    if (state.phase === 'done') onResult?.(state.result);
  }, [onResult, state]);

  const skipped = state.phase === 'done' && isSkippedDegreeSchedule(state.result) ? state.result : null;
  const schedule = state.phase === 'done' && !isSkippedDegreeSchedule(state.result) ? state.result : null;
  const contentState = state.phase === 'done' ? degreeScheduleContentState(state.result) : null;
  const infeasible = contentState === 'infeasible';

  const refreshSchedule = useCallback(async () => {
    const refreshed = await fetchDegreeSchedule(identity);
    replaceResult(refreshed);
    return refreshed;
  }, [slug, accessToken, replaceResult]);

  const saveChoices = useCallback(async (
    requirementGroupId: string,
    action: 'choose' | 'change' | 'clear',
    selections: NonNullable<typeof schedule>['selection_state']['selections'],
    candidateId?: string,
  ) => {
    if (!schedule || !accessToken || mutationInFlight.current) return;
    mutationInFlight.current = true;
    setChoiceMutation({ requirementGroupId, action, candidateId });
    setChoiceMessage(null);
    try {
      await updateDegreeScheduleChoices(accessToken, {
        scheduleVersion: schedule.schedule_version,
        selections,
      });
      await refreshSchedule();
    } catch (error) {
      const code = error instanceof DegreeScheduleChoiceError ? error.code : 'UNKNOWN_ERROR';
      try { await refreshSchedule(); } catch { /* retain the current rendered schedule */ }
      setChoiceMessage(choiceConflictMessage(code));
    } finally {
      mutationInFlight.current = false;
      setChoiceMutation(null);
    }
  }, [schedule, accessToken, choiceMutation, refreshSchedule]);

  const chooseCandidate = useCallback((
    requirementGroupId: string,
    candidate: RequirementCandidate,
    action: 'choose' | 'change' | 'clear',
  ) => {
    if (!schedule) return;
    void saveChoices(
      requirementGroupId,
      action,
      replaceRequirementSelection(
        schedule.selection_state.selections,
        requirementGroupId,
        candidate,
      ),
      candidate.candidate_id,
    );
  }, [schedule, saveChoices]);

  const clearChoice = useCallback((requirementGroupId: string) => {
    if (!schedule) return;
    void saveChoices(
      requirementGroupId,
      'clear',
      removeRequirementSelection(schedule.selection_state.selections, requirementGroupId),
    );
  }, [schedule, saveChoices]);

  return (
    <Fragment>
      <section className="card degree-schedule-panel" aria-labelledby="degree-schedule-title">
      <div className="editable-section-header">
        <div>
          <h3 id="degree-schedule-title" className="editable-section-title">Degree Schedule</h3>
          <p className="degree-schedule-subtitle">Your prerequisite-aware academic schedule for requirements with a fixed course path.</p>
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={trigger}
          disabled={state.phase === 'loading'}
          aria-busy={state.phase === 'loading'}
        >
          {state.phase === 'loading' ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {state.phase === 'idle' && <p className="analysis-empty">Preparing your degree schedule…</p>}

      {state.phase === 'loading' && (
        <div className="analysis-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <p>Retrieving your degree schedule…</p>
        </div>
      )}

      {state.phase === 'transport-error' && (
        <div className="analysis-failed">
          <p>{state.message}</p>
        </div>
      )}

      {skipped && (
        <div className="analysis-skipped">
          <p>{skipped.summary}</p>
        </div>
      )}

      {infeasible && (
        <div className="analysis-failed degree-schedule-infeasible">
          <strong>Schedule needs attention</strong>
          <p>{schedule?.failure?.safe_message ?? 'The remaining courses could not be scheduled safely.'}</p>
        </div>
      )}

      {schedule?.status === 'SCHEDULED' && (
        <>
          <p className="degree-schedule-partial-note">
            Your academic schedule is shown below. Requirements that still need adviser input are listed separately.
          </p>

          {/* Demo identities get the simpler term list: DegreeScheduleYears
              calls session-scoped /me/terms + /me/grading-schema routes
              directly with no demo counterpart, so it can't run without a
              real session. */}
          {identity.slug ? (
            contentState === 'empty' ? (
              <p className="empty-state">No deterministic courses currently need scheduling.</p>
            ) : (
              <DegreeScheduleTerms terms={schedule.terms} ariaLabel="Academic degree schedule" />
            )
          ) : (
            <DegreeScheduleYears accessToken={accessToken ?? ''} scheduleTerms={schedule.terms} courses={courses} />
          )}

          <DegreeScheduleDecisionSection schedule={schedule} mutation={choiceMutation}
            message={choiceMessage} interactive={!identity.slug} onChoose={chooseCandidate} onClear={clearChoice} />
        </>
      )}
      </section>
      {/* Demo identities (identity.slug set) never get Career Optimization: it
          has no durable cache the way GAP/FIT/SHIFT/Course Discovery do, so a
          public, tokenless button in front of it would mean every demo
          visitor's click is a fresh paid AI call. */}
      {schedule?.status === 'SCHEDULED' && !identity.slug && (
        <CareerOptimizationPanel accessToken={identity.accessToken ?? ''} academicSchedule={schedule} confirmedTargetRole={targetRole} />
      )}
    </Fragment>
  );
}
