import { useState } from 'react';
import type { DegreeScheduleResult, RequirementCandidate } from '../api/degreeSchedule.mjs';
import { buildDegreeScheduleDecisions, formatCredits } from '../lib/degreeSchedulePresentation.mjs';

type SelectionAction = 'choose' | 'change' | 'clear';

function CandidatePath({ candidate, optionNumber, requirementName, selected, changing, busy, loading, interactive, onChoose }: {
  candidate: RequirementCandidate; optionNumber: number; requirementName: string;
  selected: boolean; changing: boolean; busy: boolean; loading: boolean; interactive: boolean; onChoose: () => void;
}) {
  const isMultiCourse = candidate.candidate_courses.length > 1;
  return (
    <li className={`degree-schedule-candidate-path${selected ? ' is-selected' : ''}`}>
      <div className="degree-schedule-candidate-header">
        <strong>Option {optionNumber}</strong>
        {selected && <span className="degree-schedule-selected-label">Selected</span>}
        {isMultiCourse && candidate.additional_credits !== null && <span>{formatCredits(candidate.additional_credits)} total</span>}
      </div>
      <ul className="degree-schedule-candidate-courses" aria-label={`Courses included in option ${optionNumber}`}>
        {candidate.candidate_courses.map((course) => (
          <li key={course.course_code}>
            <div><strong>{course.course_code}</strong>{course.title !== null && <span>{course.title}</span>}</div>
            {course.credits !== null && <span>{formatCredits(course.credits)}</span>}
          </li>
        ))}
      </ul>
      {interactive && !selected && (
        <div className="degree-schedule-candidate-action">
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} aria-busy={loading}
            aria-label={`${changing ? 'Change to' : 'Choose'} ${candidate.course_codes.join(' and ')} for ${requirementName}`}
            onClick={onChoose}>
            {loading ? `${changing ? 'Changing' : 'Choosing'}…` : `${changing ? 'Change to' : 'Choose'} option`}
          </button>
        </div>
      )}
    </li>
  );
}

export function DegreeScheduleDecisionSection({ schedule, mutation, message, interactive, onChoose, onClear }: {
  schedule: DegreeScheduleResult;
  mutation: { requirementGroupId: string; action: SelectionAction; candidateId?: string } | null;
  message: string | null;
  interactive: boolean;
  onChoose: (requirementGroupId: string, candidate: RequirementCandidate, action: SelectionAction) => void;
  onClear: (requirementGroupId: string) => void;
}) {
  const presentation = buildDegreeScheduleDecisions(schedule);
  const [editingRequirementId, setEditingRequirementId] = useState<string | null>(null);
  const locked = presentation.decisions.filter((item) => item.state === 'LOCKED');
  const needed = presentation.decisions.filter((item) => item.state !== 'LOCKED');
  const hasNeeded = needed.length > 0 || presentation.legacyRequirements.length > 0;
  const busy = mutation !== null;
  const selectionState = schedule.selection_state ?? { status: 'NONE', selections: [], failure: null };

  const candidates = (item: (typeof presentation.decisions)[number], changing: boolean, selectedOnly = false) => (
    <ol className="degree-schedule-candidate-list">
      {item.candidates.filter((candidate) => !selectedOnly || candidate.candidate_id === item.selectedCandidateId).map((candidate, index) => (
        <CandidatePath candidate={candidate} optionNumber={index + 1} requirementName={item.requirementName}
          selected={item.selectedCandidateId === candidate.candidate_id} changing={changing}
          busy={busy} loading={mutation?.candidateId === candidate.candidate_id} interactive={interactive}
          onChoose={() => onChoose(item.requirementGroupId, candidate, changing ? 'change' : 'choose')}
          key={candidate.candidate_id} />
      ))}
    </ol>
  );

  return (
    <section className="degree-schedule-decisions" aria-labelledby="degree-schedule-decisions-title" aria-busy={busy}>
      {message && <div className="degree-schedule-choice-message" role="status" aria-live="polite">{message}</div>}
      {selectionState.status === 'RESELECTION_REQUIRED' && (
        <div className="degree-schedule-reselection" role="alert">
          <strong>Your saved course choice needs attention</strong>
          <p>Your degree requirements changed since this choice was saved. Choose a current option or clear the saved choice.</p>
          <div className="degree-schedule-choice-actions">
            {selectionState.selections.map((selection) => (
              <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
                aria-busy={mutation?.requirementGroupId === selection.requirement_group_id}
                onClick={() => onClear(selection.requirement_group_id)} key={selection.requirement_group_id}>
                {mutation?.requirementGroupId === selection.requirement_group_id ? 'Clearing…' : 'Clear saved choice'}
              </button>
            ))}
          </div>
        </div>
      )}

      {locked.length > 0 && (
        <section className="degree-schedule-selected-choices" aria-labelledby="degree-schedule-selected-title">
          <h4 id="degree-schedule-selected-title">Your academic choices</h4>
          <ul className="degree-schedule-decision-list">
            {locked.map((item) => {
              const editing = editingRequirementId === item.requirementGroupId;
              return (
                <li className="degree-schedule-decision-card is-locked" key={item.requirementGroupId}>
                  <div className="degree-schedule-decision-heading"><h5>{item.requirementName}</h5><strong>Selected</strong></div>
                  {candidates(item, editing, !editing)}
                  {interactive && <div className="degree-schedule-choice-actions">
                    <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
                      onClick={() => setEditingRequirementId(editing ? null : item.requirementGroupId)}>
                      {editing ? 'Cancel change' : 'Change choice'}
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
                      aria-busy={mutation?.requirementGroupId === item.requirementGroupId && mutation.action === 'clear'}
                      onClick={() => onClear(item.requirementGroupId)}>
                      {mutation?.requirementGroupId === item.requirementGroupId && mutation.action === 'clear' ? 'Clearing…' : 'Clear choice'}
                    </button>
                  </div>}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <h4 id="degree-schedule-decisions-title">Decisions needed to complete your plan</h4>
      {!hasNeeded ? <p className="empty-state">No academic decisions currently need your attention.</p> : (
        <ul className="degree-schedule-decision-list">
          {needed.map((item) => (
            <li className="degree-schedule-decision-card" key={item.requirementGroupId}>
              <div className="degree-schedule-decision-heading"><h5>{item.requirementName}</h5><div><strong>
                {item.state === 'CHOICE_REQUIRED' && 'Choice required'}
                {item.state === 'ADVISER_REVIEW' && "Can't auto-verify"}
                {item.state === 'DATA_UNRESOLVED' && 'Course data unavailable'}
              </strong>{item.state === 'CHOICE_REQUIRED' && <span>{item.validOptionLabel}</span>}</div></div>
              {item.state === 'CHOICE_REQUIRED' && candidates(item, false)}
              {item.state === 'ADVISER_REVIEW' && <p>We can't automatically verify this requirement is satisfied — check with your adviser.</p>}
              {item.state === 'DATA_UNRESOLVED' && <p>CampusIQ does not yet have enough structured course data to resolve this requirement.</p>}
            </li>
          ))}
          {presentation.legacyRequirements.map((requirement) => (
            <li className="degree-schedule-decision-card" key={requirement.requirement_group_id}>
              <div className="degree-schedule-decision-heading"><h5>{requirement.name}</h5><strong>Can't auto-verify</strong></div>
              <p>We can't automatically verify this requirement is satisfied — check with your adviser.</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
