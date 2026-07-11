import { useState } from 'react';
import type { Course, Enrollment, Assignment, Submission, ExamTopicTags } from '../types/student';
import { CourseGradeTable } from './CourseGradeTable';
import { ProfessorCommentList } from './ProfessorCommentList';
import { ExamTopicBreakdown } from './ExamTopicBreakdown';
import { ProfessorCommentAnalysisPanel } from './ProfessorCommentAnalysisPanel';

type AcademicTab = 'grades' | 'comments' | 'analysis' | 'topics';

interface AcademicSnapshotProps {
  courses: Course[];
  enrollments: Enrollment[];
  assignments: Assignment[];
  submissions: Submission[];
  examTopicTags: ExamTopicTags;
}

const TABS: { key: AcademicTab; label: string }[] = [
  { key: 'grades',   label: 'Grades'            },
  { key: 'comments', label: 'Professor Comments' },
  { key: 'analysis', label: 'AI Analysis'        },
  { key: 'topics',   label: 'Exam Topics'        },
];

export function AcademicSnapshot({
  courses,
  enrollments,
  assignments,
  submissions,
  examTopicTags,
}: AcademicSnapshotProps) {
  const [activeTab, setActiveTab] = useState<AcademicTab>('grades');

  return (
    <div className="academic-snapshot">
      {/* Segmented control — underline indicator, not pill box */}
      <div className="academic-tabs" role="tablist" aria-label="Academic views">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="tab"
            id={`academic-tab-${key}`}
            aria-selected={activeTab === key}
            aria-controls={`academic-panel-${key}`}
            className={`academic-tab${activeTab === key ? ' academic-tab--active' : ''}`}
            onClick={() => setActiveTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab panels — only one visible at a time */}
      <div
        role="tabpanel"
        id={`academic-panel-${activeTab}`}
        aria-labelledby={`academic-tab-${activeTab}`}
      >
        {activeTab === 'grades' && (
          <CourseGradeTable courses={courses} enrollments={enrollments} />
        )}
        {activeTab === 'comments' && (
          <ProfessorCommentList
            courses={courses}
            assignments={assignments}
            submissions={submissions}
          />
        )}
        {activeTab === 'analysis' && <ProfessorCommentAnalysisPanel />}
        {activeTab === 'topics' && (
          <ExamTopicBreakdown
            assignments={assignments}
            examTopicTags={examTopicTags}
          />
        )}
      </div>
    </div>
  );
}
