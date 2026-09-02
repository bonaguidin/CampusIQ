import { useEffect, useMemo, useState } from 'react';
import { fetchGradingSchema, fetchTerms } from '../api/planning';
import type { GradingSchema, PlanningTerm } from '../lib/termPlanning.mjs';
import { buildDegreeScheduleYears } from '../lib/degreeScheduleYears.mjs';
import type { DegreeScheduleSemester, DegreeScheduleYear } from '../lib/degreeScheduleYears.mjs';
import type { TermPlan } from '../api/degreeSchedule.mjs';

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

function SemesterColumn({ semester }: { semester: DegreeScheduleSemester }) {
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
          <p className="empty-state">No courses confirmed yet.</p>
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
        </>
      )}
    </section>
  );
}

export function DegreeScheduleYears({ accessToken, scheduleTerms, courses }: DegreeScheduleYearsProps) {
  const [terms, setTerms] = useState<PlanningTerm[]>([]);
  const [gradingSchema, setGradingSchema] = useState<GradingSchema | null>(null);
  const [activeYearKey, setActiveYearKey] = useState<number | null>(null);

  // Real academic terms and the institution's grade map -- the two pieces
  // of context TermPlanner already self-fetches for the same purpose.
  // schedule.terms and course_records both arrive as props: they are
  // already loaded by DegreeSchedulePanel and the dashboard respectively,
  // so fetching them again here would just be a second copy of the same
  // request in flight.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await fetchTerms({ slug: null, accessToken });
      if (!cancelled) setTerms(result.terms);
    })();
    return () => { cancelled = true; };
  }, [accessToken]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await fetchGradingSchema({ slug: null, accessToken });
      if (!cancelled) setGradingSchema(result.schema);
    })();
    return () => { cancelled = true; };
  }, [accessToken]);

  // Captured once per mount, matching TermPlanner's reasoning: a semester's
  // state must not change mid-render as the clock ticks past midnight.
  const today = useMemo(() => new Date(), []);

  const years: DegreeScheduleYear[] = useMemo(
    () => buildDegreeScheduleYears({ realTerms: terms, scheduleTerms, courseRecords: courses, gradingSchema, today }),
    [terms, scheduleTerms, courses, gradingSchema, today],
  );

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

      <div
        role="tabpanel"
        id={`degree-schedule-year-panel-${activeYear.yearKey}`}
        aria-labelledby={`degree-schedule-year-tab-${activeYear.yearKey}`}
        className="degree-schedule-year-columns"
      >
        {activeYear.semesters.map((semester) => (
          <SemesterColumn key={semester.termKey} semester={semester} />
        ))}
      </div>
    </div>
  );
}
