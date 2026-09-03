import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  addPlannedCourse,
  fetchGradingSchema,
  fetchPlannedCourses,
  fetchTerms,
  removePlannedCourse,
} from '../api/planning';
import type { AnalysisIdentity } from '../api/analysisApi.mjs';
import type { CatalogSearchResult, GradingSchema, PlannedCourse, PlanningTerm } from '../lib/termPlanning.mjs';
import { buildDegreeScheduleYears } from '../lib/degreeScheduleYears.mjs';
import type { DegreeScheduleSemester, DegreeScheduleYear } from '../lib/degreeScheduleYears.mjs';
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

interface DegreeScheduleYearsProps {
  accessToken: string;
  scheduleTerms: TermPlan[];
  courses: CourseRecordLike[];
}

function SemesterColumn({ semester, identity, busyCode, onAdd, onRemove }: {
  semester: DegreeScheduleSemester;
  identity: AnalysisIdentity;
  busyCode: string | null;
  onAdd: (semester: DegreeScheduleSemester, result: CatalogSearchResult) => void;
  onRemove: (id: string) => void;
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
          {semester.planned.length === 0 && semester.suggestedCourses.length === 0 && (
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

export function DegreeScheduleYears({ accessToken, scheduleTerms, courses }: DegreeScheduleYearsProps) {
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
    () => buildDegreeScheduleYears({ realTerms: terms, scheduleTerms, courseRecords: courses, gradingSchema, today, plannedCourses: planned }),
    [terms, scheduleTerms, courses, gradingSchema, today, planned],
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
            onAdd={handleAddPlanned}
            onRemove={handleRemovePlanned}
          />
        ))}
      </div>
    </div>
  );
}
