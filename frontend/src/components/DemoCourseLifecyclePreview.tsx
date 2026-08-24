import type { CourseLifecyclePreviewRow } from '../types/student';

interface DemoCourseLifecyclePreviewProps {
  rows: CourseLifecyclePreviewRow[];
}

const STATUS_LABEL: Record<CourseLifecyclePreviewRow['status'], string> = {
  planned: 'Planned',
  in_progress: 'In progress',
  completed: 'Completed',
  dropped: 'Dropped',
};

// Purely static -- no fetch, no session. Real students see this as a live,
// editable planner (TermPlanner.tsx, backed by Postgres terms/course_records);
// demo students have no such rows, so this shows one hand-authored example
// per lifecycle state instead. The note below exists so it is never mistaken
// for TermPlanner's real, editable surface.
export function DemoCourseLifecyclePreview({ rows }: DemoCourseLifecyclePreviewProps) {
  if (rows.length === 0) return null;

  return (
    <section className="demo-lifecycle-preview">
      <h3 className="demo-lifecycle-heading">Course Planning</h3>
      <p className="demo-lifecycle-note">
        Illustrative example — not connected to a real enrollment.
      </p>
      <div className="demo-lifecycle-rows" role="table" aria-label="Example course lifecycle states">
        {rows.map((row) => (
          <div className="demo-lifecycle-row" role="row" key={`${row.status}-${row.course_code}`}>
            <span role="cell">
              <span className={`course-status-badge demo-lifecycle-badge--${row.status}`}>
                {STATUS_LABEL[row.status]}
              </span>
              <strong>{row.course_code}</strong>
              <small>{row.title}</small>
            </span>
            <span role="cell">{row.term_label}</span>
            <span role="cell">{row.letter_grade ?? '—'}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
