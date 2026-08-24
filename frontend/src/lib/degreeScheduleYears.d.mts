import type { PlanningTerm, GradingSchema } from './termPlanning.mjs';
import type { TermPlan } from '../api/degreeSchedule.mjs';

export type SemesterSeason = 'Fall' | 'Spring';
export type SemesterState = 'past' | 'in_progress' | 'future';

export interface CourseRecordLike {
  id: string;
  term_id: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number | string;
  letter_grade: string | null;
  status: string;
}

export interface DegreeScheduleYearCourse {
  course_code: string;
  title: string | null;
  credit_hours: number | string;
  gradeBadge: string | null;
}

export interface DegreeScheduleSuggestedCourse {
  course_code: string;
  credit_hours: number;
}

export interface DegreeScheduleSemester {
  season: SemesterSeason;
  termKey: string;
  state: SemesterState;
  totalCreditsLabel: string | null;
  courses: DegreeScheduleYearCourse[];
  suggestedCourses: DegreeScheduleSuggestedCourse[];
}

export interface DegreeScheduleYear {
  yearKey: number;
  label: string;
  semesters: DegreeScheduleSemester[];
}

export declare const YEAR_SEMESTER_SEASONS: SemesterSeason[];

export declare function academicYearLabel(index: number): string;
export declare function academicYearKey(year: number, season: string): number | null;
export declare function formatGradeBadge(
  letterGrade: string | null,
  gradingSchema: GradingSchema | null | undefined,
): string | null;
export declare function semesterState(
  realTerm: PlanningTerm | null | undefined,
  today: Date,
): SemesterState;
export declare function buildDegreeScheduleYears(input: {
  realTerms: PlanningTerm[];
  scheduleTerms: TermPlan[];
  courseRecords: CourseRecordLike[];
  gradingSchema: GradingSchema | null;
  today: Date;
}): DegreeScheduleYear[];
