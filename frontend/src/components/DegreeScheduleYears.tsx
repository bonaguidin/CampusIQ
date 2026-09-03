import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  addPlannedCourse,
  fetchGradingSchema,
  fetchPlannedCourses,
  fetchTerms,
  removePlannedCourse,
} from '../api/planning';
import type { AnalysisIdentity } from '../api/analysisApi.mjs';
import type {
  RequirementCandidate,
  RequirementCandidateSet,
  RequirementDecision,
} from '../api/degreeSchedule.mjs';
import type { CatalogSearchResult, GradingSchema, PlannedCourse, PlanningTerm } from '../lib/termPlanning.mjs';
import { buildDegreeScheduleYears } from '../lib/degreeScheduleYears.mjs';
import type { DegreeScheduleSemester, DegreeScheduleTermDecision, DegreeScheduleYear } from '../lib/degreeScheduleYears.mjs';
import { displayTermKey, formatCredits } from '../lib/degreeSchedulePresentation.mjs';
import type { TermPlan } from '../api/degreeSchedule.mjs';
import { CourseSearchAdd } from './CourseSearchAdd';

interface CourseRecordLike {
  id: string;
  term_id: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number | string;
  letter_grade: string | null;
  status: string;
}

type DecisionAction = 'choose' | 'change' | 'clear' | 'restore';

export interface DegreeScheduleChoiceMutation {
  requirementGroupId: string;
  action: DecisionAction;
  candidateId?: string;
}

interface DegreeScheduleYearsProps {
  accessToken: string;
  scheduleTerms: TermPlan[];
  courses: CourseRecordLike[];
  // Phase 3: the decision evidence the backend serializes alongside the
  // schedule. LOCKED/CHOICE_REQUIRED/EXCLUDED decisions render on the term
  // card the backend resolved for each; everything else is ignored here.
  decisions: RequirementDecision[];
  candidateSets: RequirementCandidateSet[];
  mutation: DegreeScheduleChoiceMutation | null;
  onChoose: (requirementGroupId: string, candidate: RequirementCandidate, action: 'choose' | 'change') => void;
  onClear: (requirementGroupId: string) => void;
  onRestore: (requirementGroupId: string) => void;
}

// One grouped academic path inside a decision card. Trimmed from the retired
// DegreeScheduleDecisionSection's CandidatePath -- same markup/classes so the
// existing candidate-path CSS carries over unchanged.
function DecisionCandidatePath({ candidate, optionNumber, requirementName, selected, changing, busy, loading, onChoose }: {
  candidate: RequirementCandidate;
  optionNumber: number;
  requirementName: string;
  selected: boolean;
  changing: boolean;
  busy: boolean;
  loading: boolean;
  onChoose: () => void;
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
      {!selected && (
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

// A single relocated decision, rendered inside its resolved term column
// alongside the scheduled/planned/suggested rows.
function TermDecisionCard({ decision, mutation, onChoose, onClear, onRestore }: {
  decision: DegreeScheduleTermDecision;
  mutation: DegreeScheduleChoiceMutation | null;
  onChoose: (requirementGroupId: string, candidate: RequirementCandidate, action: 'choose' | 'change') => void;
  onClear: (requirementGroupId: string) => void;
  onRestore: (requirementGroupId: string) => void;
}) {
  const [changing, setChanging] = useState(false);
  const busy = mutation !== null;
  const rgid = decision.requirementGroupId;
  const rowBusy = mutation?.requirementGroupId === rgid;
  const { requirementName, candidates, selectedCandidateId } = decision;

  if (decision.state === 'LOCKED') {
    const selected = candidates.find((candidate) => candidate.candidate_id === selectedCandidateId) ?? candidates[0] ?? null;
    const shown = changing ? candidates : selected ? [selected] : [];
    return (
      <li className="degree-schedule-decision-card is-locked degree-schedule-term-decision">
        <div className="degree-schedule-decision-heading"><h6>{requirementName}</h6><strong>Selected</strong></div>
        <ol className="degree-schedule-candidate-list">
          {shown.map((candidate, index) => (
            <DecisionCandidatePath key={candidate.candidate_id} candidate={candidate} optionNumber={index + 1}
              requirementName={requirementName} selected={candidate.candidate_id === selectedCandidateId}
              changing busy={busy} loading={mutation?.candidateId === candidate.candidate_id}
              onChoose={() => onChoose(rgid, candidate, 'change')} />
          ))}
        </ol>
        <div className="degree-schedule-choice-actions">
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
            onClick={() => setChanging((value) => !value)}>
            {changing ? 'Cancel change' : 'Change choice'}
          </button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
            aria-busy={rowBusy && mutation?.action === 'clear'}
            onClick={() => onClear(rgid)}>
            {rowBusy && mutation?.action === 'clear' ? 'Clearing…' : 'Clear choice'}
          </button>
        </div>
      </li>
    );
  }

  if (decision.state === 'EXCLUDED') {
    const codes = [...new Set(candidates.flatMap((candidate) => candidate.course_codes))];
    return (
      <li className="degree-schedule-decision-card degree-schedule-term-decision">
        <div className="degree-schedule-decision-heading">
          <h6>{requirementName}</h6>
          <div><strong>Set aside</strong><span>{`Est. ${displayTermKey(decision.termKey)}`}</span></div>
        </div>
        {codes.length > 0 && <p className="degree-schedule-term-decision-codes">{codes.join(', ')}</p>}
        <p>You set this requirement aside. It's still required. The term shown is an estimate of where it would land, not a confirmed placement — add it back to schedule it.</p>
        <div className="degree-schedule-choice-actions">
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
            aria-busy={rowBusy && mutation?.action === 'restore'}
            onClick={() => onRestore(rgid)}>
            {rowBusy && mutation?.action === 'restore' ? 'Adding…' : 'Add it back'}
          </button>
        </div>
      </li>
    );
  }

  // CHOICE_REQUIRED
  return (
    <li className="degree-schedule-decision-card degree-schedule-term-decision">
      <div className="degree-schedule-decision-heading">
        <h6>{requirementName}</h6>
        <div><strong>Choice required</strong><span>{`${candidates.length} valid option${candidates.length === 1 ? '' : 's'}`}</span></div>
      </div>
      <p>Pick an option to schedule this requirement. This term is an estimate — it may shift depending on which option you choose.</p>
      <ol className="degree-schedule-candidate-list">
        {candidates.map((candidate, index) => (
          <DecisionCandidatePath key={candidate.candidate_id} candidate={candidate} optionNumber={index + 1}
            requirementName={requirementName} selected={false} changing={false}
            busy={busy} loading={mutation?.candidateId === candidate.candidate_id}
            onChoose={() => onChoose(rgid, candidate, 'choose')} />
        ))}
      </ol>
    </li>
  );
}

function SemesterColumn({ semester, identity, busyCode, mutation, onAdd, onRemove, onChoose, onClear, onRestore }: {
  semester: DegreeScheduleSemester;
  identity: AnalysisIdentity;
  busyCode: string | null;
  mutation: DegreeScheduleChoiceMutation | null;
  onAdd: (semester: DegreeScheduleSemester, result: CatalogSearchResult) => void;
  onRemove: (id: string) => void;
  onChoose: (requirementGroupId: string, candidate: RequirementCandidate, action: 'choose' | 'change') => void;
  onClear: (requirementGroupId: string) => void;
  onRestore: (requirementGroupId: string) => void;
}) {
  const addedCodes = useMemo(
    () => new Set(semester.planned.map((course) => course.course_code.toUpperCase())),
    [semester.planned],
  );

  return (
    <section className="degree-schedule-semester" aria-label={`${semester.season} ${semester.termKey.split('-')[0]}`}>
      <div className="degree-schedule-semester-header">
        <h5>{semester.season}</h5>
        <span>{semester.totalCreditsLabel ?? '—'}</span>
      </div>

      {(semester.state === 'past' || semester.state === 'in_progress') && (
        semester.courses.length === 0 ? (
          <p className="empty-state">No confirmed coursework this term.</p>
        ) : (
          <ul className="degree-schedule-semester-courses">
            {semester.courses.map((course) => (
              <li key={course.course_code} className="degree-schedule-semester-course">
                <div className="degree-schedule-course-row">
                  <span>
                    <strong>{course.course_code}</strong>
                    {course.title && <small>{course.title}</small>}
                  </span>
                  <span>{course.credit_hours} credits</span>
                </div>
                {semester.state === 'in_progress' ? (
                  <span className="degree-schedule-badge degree-schedule-badge--in-progress">In progress</span>
                ) : (
                  course.gradeBadge && (
                    <span className="degree-schedule-badge degree-schedule-badge--grade">{course.gradeBadge}</span>
                  )
                )}
              </li>
            ))}
          </ul>
        )
      )}

      {semester.state === 'future' && (
        <>
          {semester.decisions.length > 0 && (
            <ul className="degree-schedule-term-decisions">
              {semester.decisions.map((decision) => (
                <TermDecisionCard
                  key={decision.requirementGroupId}
                  decision={decision}
                  mutation={mutation}
                  onChoose={onChoose}
                  onClear={onClear}
                  onRestore={onRestore}
                />
              ))}
            </ul>
          )}

          {semester.planned.length === 0 && semester.suggestedCourses.length === 0 && semester.decisions.length === 0 && (
            <p className="empty-state">No courses confirmed yet.</p>
          )}

          {semester.planned.length > 0 && (
            <ul className="degree-schedule-semester-courses">
              {semester.planned.map((course) => (
                <li key={course.id} className="degree-schedule-semester-course">
                  <div className="degree-schedule-course-row">
                    <span>
                      <strong>{course.course_code}</strong>
                      {course.title && <small>{course.title}</small>}
                    </span>
                    <span>{course.credit_hours === null ? 'Credits TBD' : `${course.credit_hours} credits`}</span>
                  </div>
                  <div className="degree-schedule-course-row">
                    <span className="degree-schedule-badge degree-schedule-badge--added">Added</span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => onRemove(course.id)}
                      aria-label={`Remove ${course.course_code} from your plan`}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {semester.suggestedCourses.length > 0 && (
            <div className="degree-schedule-suggested">
              <h6>Suggested courses</h6>
              <ul className="degree-schedule-semester-courses">
                {semester.suggestedCourses.map((course) => (
                  <li key={course.course_code} className="degree-schedule-semester-course">
                    <div className="degree-schedule-course-row">
                      <span><strong>{course.course_code}</strong></span>
                      <span>{course.credit_hours} credits</span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="degree-schedule-suggested degree-schedule-add">
            <h6>Plan a course</h6>
            <CourseSearchAdd
              identity={identity}
              alreadyAddedCodes={addedCodes}
              onAdd={(result) => onAdd(semester, result)}
              busyCode={busyCode}
              inputId={`degree-schedule-course-search-${semester.termKey}`}
            />
          </div>
        </>
      )}
    </section>
  );
}

export function DegreeScheduleYears({
  accessToken,
  scheduleTerms,
  courses,
  decisions,
  candidateSets,
  mutation,
  onChoose,
  onClear,
  onRestore,
}: DegreeScheduleYearsProps) {
  const [terms, setTerms] = useState<PlanningTerm[]>([]);
  const [gradingSchema, setGradingSchema] = useState<GradingSchema | null>(null);
  const [planned, setPlanned] = useState<PlannedCourse[]>([]);
  const [busyCode, setBusyCode] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [activeYearKey, setActiveYearKey] = useState<number | null>(null);

  const identity = useMemo<AnalysisIdentity>(() => ({ slug: null, accessToken }), [accessToken]);

  // Real academic terms and the institution's grade map -- the two pieces
  // of context TermPlanner already self-fetches for the same purpose.
  // schedule.terms and course_records both arrive as props: they are
  // already loaded by DegreeSchedulePanel and the dashboard respectively,
  // so fetching them again here would just be a second copy of the same
  // request in flight. planned_courses has no such prop, so it is fetched
  // here (full list, no term filter), matching realTerms/gradingSchema.
  const loadTerms = useCallback(async () => {
    const result = await fetchTerms(identity);
    setTerms(result.terms);
  }, [identity]);

  const loadPlanned = useCallback(async () => {
    const result = await fetchPlannedCourses(identity);
    setPlanned(result.plannedCourses);
  }, [identity]);

  useEffect(() => { void loadTerms(); }, [loadTerms]);
  useEffect(() => { void loadPlanned(); }, [loadPlanned]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await fetchGradingSchema(identity);
      if (!cancelled) setGradingSchema(result.schema);
    })();
    return () => { cancelled = true; };
  }, [identity]);

  // Captured once per mount, matching TermPlanner's reasoning: a semester's
  // state must not change mid-render as the clock ticks past midnight.
  const today = useMemo(() => new Date(), []);

  const years: DegreeScheduleYear[] = useMemo(
    () => buildDegreeScheduleYears({
      realTerms: terms,
      scheduleTerms,
      courseRecords: courses,
      gradingSchema,
      today,
      plannedCourses: planned,
      decisions,
      candidateSets,
    }),
    [terms, scheduleTerms, courses, gradingSchema, today, planned, decisions, candidateSets],
  );

  const handleAddPlanned = useCallback(async (semester: DegreeScheduleSemester, result: CatalogSearchResult) => {
    setBusyCode(result.code);
    setAddError(null);
    const year = Number(semester.termKey.split('-')[0]);
    const response = await addPlannedCourse(identity, {
      course_code: result.code,
      year,
      season: semester.season,
      term_label: `${semester.season} ${year}`,
      title: result.title,
      // Only a fixed-credit course carries its hours across, matching
      // TermPlanner: a variable-credit course is left null rather than
      // guessing which end of the range the student registers for.
      credit_hours:
        result.credit_min !== null && result.credit_min === result.credit_max
          ? result.credit_min
          : null,
      catalog_course_id: result.id,
      force_planned: true,
    });
    setBusyCode(null);
    if (!response.ok) {
      setAddError(response.message ?? 'Could not add that course to your plan.');
      return;
    }
    // Adding to a term the student had never enrolled in creates its
    // academic_terms row, so refetch terms too -- the planned row is matched
    // against realTerm.id, which may only now exist.
    await Promise.all([loadPlanned(), loadTerms()]);
  }, [identity, loadPlanned, loadTerms]);

  const handleRemovePlanned = useCallback(async (id: string) => {
    setAddError(null);
    const response = await removePlannedCourse(identity, id);
    if (!response.ok) {
      setAddError('Could not remove that course.');
      return;
    }
    await loadPlanned();
  }, [identity, loadPlanned]);

  const inProgressYearKey = useMemo(() => {
    const withCurrentTerm = years.find((year) => year.semesters.some((s) => s.state === 'in_progress'));
    return withCurrentTerm?.yearKey ?? null;
  }, [years]);

  useEffect(() => {
    if (years.length === 0) return;
    const stillValid = years.some((year) => year.yearKey === activeYearKey);
    if (stillValid) return;
    setActiveYearKey(inProgressYearKey ?? years[0].yearKey);
    // Only re-picks when the current selection stops existing (e.g. first
    // load) -- a student clicking between tabs must not get bounced back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [years, inProgressYearKey]);

  if (years.length === 0) {
    return <p className="empty-state">No academic years on record or scheduled yet.</p>;
  }

  const activeYear = years.find((year) => year.yearKey === activeYearKey) ?? years[0];

  return (
    <div className="degree-schedule-years">
      <div className="academic-tabs" role="tablist" aria-label="Academic years">
        {years.map((year) => (
          <button
            key={year.yearKey}
            type="button"
            role="tab"
            id={`degree-schedule-year-tab-${year.yearKey}`}
            aria-selected={activeYear.yearKey === year.yearKey}
            aria-controls={`degree-schedule-year-panel-${year.yearKey}`}
            className={`academic-tab${activeYear.yearKey === year.yearKey ? ' academic-tab--active' : ''}`}
            onClick={() => setActiveYearKey(year.yearKey)}
          >
            {year.label}
          </button>
        ))}
      </div>

      {addError && <p className="term-planner-error" role="alert">{addError}</p>}

      <div
        role="tabpanel"
        id={`degree-schedule-year-panel-${activeYear.yearKey}`}
        aria-labelledby={`degree-schedule-year-tab-${activeYear.yearKey}`}
        className="degree-schedule-year-columns"
      >
        {activeYear.semesters.map((semester) => (
          <SemesterColumn
            key={semester.termKey}
            semester={semester}
            identity={identity}
            busyCode={busyCode}
            mutation={mutation}
            onAdd={handleAddPlanned}
            onRemove={handleRemovePlanned}
            onChoose={onChoose}
            onClear={onClear}
            onRestore={onRestore}
          />
        ))}
      </div>
    </div>
  );
}
