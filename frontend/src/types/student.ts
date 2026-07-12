// TypeScript interfaces matching the Campus IQ unified student profile schema.
// canvas_derived blocks are READ-ONLY; student_entered (career) is editable.

// ── canvas_derived ──────────────────────────────────────────────────────────

export interface StudentBlock {
  id: number;
  name: string;
  major_current: string;
  major_intended: string; // READ-ONLY, display only
  classification: string;
  institution: string;
  gpa_current: number;
  expected_graduation: string;
}

export interface Course {
  id: number;
  name: string;
  course_code: string;
  workflow_state: string;
}

export interface EnrollmentGrades {
  html_url: string;
  current_grade: string | null;
  current_score: number | null;
  final_grade: string | null;
  final_score: number | null;
}

export interface Enrollment {
  id: number;
  course_id: number;
  course_section_id: number;
  user_id: number;
  type: string;
  role: string;
  role_id: number;
  enrollment_state: string;
  created_at: string;
  updated_at: string;
  grades: EnrollmentGrades;
}

export interface Assignment {
  id: number;
  name: string;
  course_id: number;
  due_at: string | null;
  points_possible: number;
  submission_types: string[];
  grading_type: string;
  published: boolean;
  workflow_state: string;
}

export interface SubmissionComment {
  id: number;
  author_id: number;
  author_name: string;
  comment: string;
  created_at: string;
}

export interface Submission {
  assignment_id: number;
  user_id: number;
  score: number | null;
  grade: string | null;
  grade_matches_current_submission: boolean;
  submitted_at: string | null;
  graded_at: string | null;
  grader_id: number | null;
  workflow_state: string;
  late: boolean;
  missing: boolean;
  submission_type: string;
  submission_comments: SubmissionComment[];
}

// ── campus_iq_layer ─────────────────────────────────────────────────────────

export interface ExamTopicTag {
  question_id: string;
  topic: string;
  score: number;
  max_score: number;
}

// keyed by assignment_id as string
export type ExamTopicTags = Record<string, ExamTopicTag[]>;

// ── student_entered (EDITABLE) ───────────────────────────────────────────────

export interface SkillsSelfReported {
  technical: string[];
  soft: string[];
  ai_exposure: string;
}

export interface Certification {
  name: string;
  issuer: string;
  status: string;
  date?: string;
}

export interface WorkExperience {
  employer: string;
  role: string;
  duration: string;
  location: string;
  description: string;
  skills_gained: string[];
}

export interface Project {
  name: string;
  timeframe: string;
  description: string;
  tools: string[];
}

export interface CareerBlock {
  target_roles: string[];
  interests: string[];
  career_goals: string;
  geographic_preference: string;
  ai_anxiety_level: string;
  skills_self_reported: SkillsSelfReported;
  certifications: Certification[];
  work_experience: WorkExperience[];
  projects: Project[];
}

// ── ai_written (READ-ONLY, display only) ────────────────────────────────────

export interface FeatureReadiness {
  ready: boolean;
  required: Record<string, boolean>;
}

export interface ProfileCompleteness {
  academic: number; // 0–1
  career: number;   // 0–1
  overall: number;  // 0–1
  by_feature: {
    FIT: FeatureReadiness;
    GAP: FeatureReadiness;
    SHIFT: FeatureReadiness;
  };
}

// ── Top-level unified profile ────────────────────────────────────────────────

export interface StudentProfile {
  student: StudentBlock;
  courses: Course[];
  enrollments: Enrollment[];
  assignments: Assignment[];
  submissions: Submission[];
  examTopicTags: ExamTopicTags;
  career: CareerBlock | null;
  profile_completeness: ProfileCompleteness;
  // _notes, _schema_notes, onboarding_stage intentionally omitted (not shown to user)
}
