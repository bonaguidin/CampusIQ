import type { Course, Assignment, Submission } from '../types/student';

interface ProfessorCommentListProps {
  courses: Course[];
  assignments: Assignment[];
  submissions: Submission[];
}

export function ProfessorCommentList({
  courses,
  assignments,
  submissions,
}: ProfessorCommentListProps) {
  // Build lookup maps
  const courseById = new Map<number, Course>();
  for (const c of courses) courseById.set(c.id, c);

  const assignmentById = new Map<number, Assignment>();
  for (const a of assignments) assignmentById.set(a.id, a);

  // Collect submissions that have at least one comment
  type CommentEntry = {
    courseName: string;
    courseId: number;
    assignmentName: string;
    authorName: string;
    comment: string;
  };

  const commentsByCourse = new Map<number, CommentEntry[]>();

  for (const sub of submissions) {
    if (!sub.submission_comments || sub.submission_comments.length === 0) continue;
    const assignment = assignmentById.get(sub.assignment_id);
    if (!assignment) continue;
    const course = courseById.get(assignment.course_id);
    const courseName = course?.name ?? `Course ${assignment.course_id}`;
    const courseId = assignment.course_id;

    for (const c of sub.submission_comments) {
      const entry: CommentEntry = {
        courseName,
        courseId,
        assignmentName: assignment.name,
        authorName: c.author_name,
        comment: c.comment,
      };
      const existing = commentsByCourse.get(courseId) ?? [];
      existing.push(entry);
      commentsByCourse.set(courseId, existing);
    }
  }

  if (commentsByCourse.size === 0) {
    return <p className="empty-state">No professor comments available.</p>;
  }

  // Sort course groups by course id for stable ordering
  const groups = Array.from(commentsByCourse.entries()).sort(([a], [b]) => a - b);

  return (
    <div className="comment-list">
      {groups.map(([courseId, entries]) => (
        <div key={courseId} className="comment-group">
          <h4 className="comment-course-name">{entries[0]?.courseName ?? `Course ${courseId}`}</h4>
          <ul className="comment-items">
            {entries.map((entry, idx) => (
              <li key={idx} className="comment-item">
                <span className="comment-author">{entry.authorName}</span>
                {' on '}
                <em>{entry.assignmentName}</em>
                {': '}
                <span className="comment-text">{entry.comment}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
