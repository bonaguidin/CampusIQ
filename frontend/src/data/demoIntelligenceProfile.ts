import type { ProfileChanges } from '../api/profile';
import type { StudentProfile } from '../types/student';
import type {
  AcademicCourse,
  CanonicalCareerItem,
  StudentIntelligenceProfile,
} from '../types/studentIntelligenceProfile';

/**
 * Client-side mirror of GradusIQ_career/demo/profile_adapter.py's
 * build_demo_intelligence_profile -- reshapes the raw demo StudentProfile
 * (data/students/student_<slug>.json, loaded via useAuth().profile) into the
 * same StudentIntelligenceProfile shape real accounts get from Postgres, so
 * buildDashboardViewModel/CareerProfile/ProfileChecklist/TermPlanner can all
 * run against demo data unmodified. Field-for-field, this follows the same
 * rules as the Python adapter for cross-consistency -- see that file for the
 * canonical statement of each rule.
 */

const EXCLUDED_WORKFLOW_STATES = new Set(['deleted', 'inactive']);
const COMPLETED_WORKFLOW_STATES = new Set(['completed']);
const COMPLETED_ENROLLMENT_STATES = new Set(['completed']);
const DEMO_SOURCE = 'demo_seed';

function courseStatus(workflowState: string, enrollmentState: string | undefined): string {
  if (COMPLETED_WORKFLOW_STATES.has(workflowState)) return 'completed';
  if (enrollmentState && COMPLETED_ENROLLMENT_STATES.has(enrollmentState)) return 'completed';
  return 'in_progress';
}

function letterGrade(enrollment: StudentProfile['enrollments'][number] | undefined): string | null {
  if (!enrollment) return null;
  return enrollment.grades.final_grade ?? enrollment.grades.current_grade ?? null;
}

function buildAcademicCourses(profile: StudentProfile): AcademicCourse[] {
  const enrollmentsByCourseId = new Map(profile.enrollments.map((e) => [e.course_id, e]));
  const courses: AcademicCourse[] = [];
  for (const course of profile.courses) {
    if (EXCLUDED_WORKFLOW_STATES.has(course.workflow_state)) continue;
    const enrollment = enrollmentsByCourseId.get(course.id);
    courses.push({
      id: String(course.id),
      term_id: null,
      institution_id: null,
      course_code: course.course_code,
      title: course.name,
      credit_hours: Number(course.credit_hours),
      letter_grade: letterGrade(enrollment),
      credit_type: 'resident',
      status: courseStatus(course.workflow_state, enrollment?.enrollment_state),
      source: DEMO_SOURCE,
    });
  }
  return courses;
}

function withSource<T extends object>(items: T[]): CanonicalCareerItem[] {
  return items.map((item) => ({ ...item, source: DEMO_SOURCE }));
}

export function buildDemoIntelligenceProfile(profile: StudentProfile): StudentIntelligenceProfile {
  const { student, career } = profile;
  const courses = buildAcademicCourses(profile);
  const completedHours = courses
    .filter((c) => c.status === 'completed')
    .reduce((sum, c) => sum + c.credit_hours, 0);
  const inProgressHours = courses
    .filter((c) => c.status === 'in_progress')
    .reduce((sum, c) => sum + c.credit_hours, 0);
  const inProgressWithCurrentGradeCount = courses.filter(
    (c) => c.status === 'in_progress' && c.letter_grade !== null,
  ).length;

  const skills = career?.skills_self_reported;

  return {
    contract_version: '1.0',
    identity: {
      student_id: String(student.id),
      name: student.name,
      classification: student.classification,
      expected_graduation: student.expected_graduation,
      onboarding_stage: null,
    },
    institution: {
      id: null,
      name: student.institution,
      relationship: 'home',
    },
    academics: {
      summary: {
        major_current: student.major_current,
        major_intended: student.major_intended,
        confirmed_course_count: courses.length,
        completed_hours: completedHours,
        in_progress_hours: inProgressHours,
        // Same simplification the Python adapter makes: earned_hours ===
        // completed_hours, no separate repeat-aware recompute for demo data.
        earned_hours: completedHours,
      },
      // Always empty for demo, same as the backend adapter -- no term data
      // in the flat fixtures. GPA Calculator's term list comes from
      // demoTermFixtures.ts instead, entirely separate from this.
      terms: [],
      courses,
      gpa: {
        // Same simplification as the Python adapter: no separate projected
        // recompute exists for demo data, so official === projected.
        official: student.gpa_current,
        projected: student.gpa_current,
        computable: student.gpa_current !== null,
        in_progress_with_current_grade_count: inProgressWithCurrentGradeCount,
        source: 'gpa_service',
      },
      repeat_exclusions: [],
    },
    career: {
      // Hardcoded true, same reasoning as the Python adapter: the flat JSON
      // has no confirmed_at concept, and every career-gated surface (target
      // role coverage badges, Course Discovery) requires it.
      confirmed: true,
      target_roles: career?.target_roles ?? [],
      interests: career?.interests ?? [],
      career_goals: career?.career_goals ?? null,
      geographic_preference: career?.geographic_preference ?? null,
      ai_anxiety_level: career?.ai_anxiety_level ?? null,
      skills: {
        technical: skills?.technical ?? [],
        soft: skills?.soft ?? [],
        ai_exposure: skills?.ai_exposure ?? null,
      },
      certifications: withSource(career?.certifications ?? []),
      work_experience: withSource(career?.work_experience ?? []),
      projects: withSource(career?.projects ?? []),
    },
    completeness: {
      career: {
        confirmed_profile: true,
        target_role_present: (career?.target_roles.length ?? 0) > 0,
        skills_present: (skills?.technical.length ?? 0) > 0 || (skills?.soft.length ?? 0) > 0,
        certifications_present: (career?.certifications.length ?? 0) > 0,
        work_experience_present: (career?.work_experience.length ?? 0) > 0,
        projects_present: (career?.projects.length ?? 0) > 0,
        ready_for_career_features: Boolean(
          career && career.target_roles.length > 0
            && ((skills?.technical.length ?? 0) > 0 || (skills?.soft.length ?? 0) > 0),
        ),
      },
      academics: {
        transcript_data_present: courses.length > 0,
        terms_present: false,
        gpa_computable: student.gpa_current !== null,
        ready_for_academic_features: courses.length > 0,
      },
      overall: 'partial',
    },
    provenance: {
      career_profile: DEMO_SOURCE,
      certifications: career && career.certifications.length > 0 ? [DEMO_SOURCE] : [],
      work_experience: career && career.work_experience.length > 0 ? [DEMO_SOURCE] : [],
      projects: career && career.projects.length > 0 ? [DEMO_SOURCE] : [],
      academics: courses.length > 0 ? [DEMO_SOURCE] : [],
      credit_type_limitation: null,
    },
  };
}

/**
 * Merges a CareerProfile edit into the local demo profile -- the local
 * counterpart to what PATCH /api/v2/student/me/profile does for real
 * accounts, except this never leaves the browser tab. Only the six fields
 * CareerProfile can ever produce are handled; anything else in ProfileChanges
 * is ignored rather than guessed at.
 */
export function applyDemoProfileChanges(
  profile: StudentIntelligenceProfile,
  changes: ProfileChanges,
): StudentIntelligenceProfile {
  return {
    ...profile,
    identity: {
      ...profile.identity,
      classification: changes.classification ?? profile.identity.classification,
      expected_graduation:
        changes.expected_graduation !== undefined
          ? changes.expected_graduation
          : profile.identity.expected_graduation,
    },
    academics: {
      ...profile.academics,
      summary: {
        ...profile.academics.summary,
        major_current: changes.major_current ?? profile.academics.summary.major_current,
        major_intended:
          changes.major_intended !== undefined
            ? changes.major_intended
            : profile.academics.summary.major_intended,
      },
    },
    career: {
      ...profile.career,
      target_roles: changes.target_roles ?? profile.career.target_roles,
      interests: changes.interests ?? profile.career.interests,
      ai_anxiety_level:
        changes.ai_anxiety_level !== undefined
          ? changes.ai_anxiety_level
          : profile.career.ai_anxiety_level,
      skills: {
        ...profile.career.skills,
        technical: changes.skills_technical ?? profile.career.skills.technical,
        soft: changes.skills_soft ?? profile.career.skills.soft,
      },
    },
  };
}
