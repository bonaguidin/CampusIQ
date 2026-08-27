import type { AcademicCourse, AcademicTerm } from '../types/studentIntelligenceProfile';

export interface CurrentTermSnapshot {
  termLabel: string | null;
  courses: AcademicCourse[];
  totalCredits: number;
}

export declare function currentTermSnapshot(input: {
  courses: AcademicCourse[];
  terms: AcademicTerm[];
}): CurrentTermSnapshot | null;
