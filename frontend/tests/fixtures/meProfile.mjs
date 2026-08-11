// A canonical /api/v2/student/me/profile body for the flow previews.
//
// The point of parameterising it on `confirmed` is the freshness assertion:
// before a confirm the preview server answers with an empty academic/career
// profile, after one it answers with the confirmed rows. Whether the dashboard
// shows the new data therefore depends entirely on whether the frontend
// re-read this endpoint, which is the behaviour under test.

const INSTITUTION_ID = '75d68331-91d2-47e8-9671-2a3b065955d0'
const TERM_ID = '33333333-3333-4333-8333-333333333333'

const EMPTY_CAREER = {
  confirmed: false, target_roles: [], interests: [], career_goals: null,
  geographic_preference: null, ai_anxiety_level: null,
  skills: { technical: [], soft: [], ai_exposure: null },
  certifications: [], work_experience: [], projects: [],
}

const CONFIRMED_CAREER = {
  confirmed: true, target_roles: ['Software Engineer'], interests: ['systems'],
  career_goals: 'Build reliable software', geographic_preference: null, ai_anxiety_level: null,
  skills: { technical: ['TypeScript'], soft: [], ai_exposure: null },
  certifications: [],
  work_experience: [{ employer: 'Acme', role: 'Intern', source: 'resume_parse' }],
  projects: [],
}

const COURSE = {
  id: 'course-confirmed-1', term_id: TERM_ID, institution_id: INSTITUTION_ID,
  course_code: 'MATH 251', title: 'Engineering Mathematics III', credit_hours: 3,
  letter_grade: 'B', credit_type: 'resident', status: 'completed', source: 'transcript_parse',
}

/**
 * @param {{ academics?: boolean, career?: boolean }} confirmed
 */
export function meProfile(confirmed = {}) {
  const academics = confirmed.academics === true
  const career = confirmed.career === true
  return {
    student: { id: 'student-preview', name: 'Preview Student', institution: 'Texas A&M University' },
    career: null,
    intelligence_profile: {
      contract_version: '1.0',
      identity: {
        student_id: 'student-preview', name: 'Preview Student', classification: 'Sophomore',
        expected_graduation: '2028-05', onboarding_stage: 3,
      },
      institution: { id: INSTITUTION_ID, name: 'Texas A&M University', relationship: 'home' },
      academics: {
        summary: {
          major_current: 'Computer Science', major_intended: null,
          confirmed_course_count: academics ? 1 : 0,
          completed_hours: academics ? 3 : 0, in_progress_hours: 0, earned_hours: academics ? 3 : 0,
        },
        terms: academics
          ? [{ id: TERM_ID, institution_id: INSTITUTION_ID, label: 'Fall 2025', year: 2025, season: 'fall', sequence: 1 }]
          : [],
        courses: academics ? [COURSE] : [],
        gpa: academics
          ? { official: 3, projected: 3, computable: true, source: 'gpa_service' }
          : { official: null, projected: null, computable: false, source: 'gpa_service' },
        repeat_exclusions: [],
      },
      career: career ? CONFIRMED_CAREER : EMPTY_CAREER,
      completeness: {
        career: {
          confirmed_profile: career, target_role_present: career, skills_present: career,
          certifications_present: false, work_experience_present: career, projects_present: false,
          ready_for_career_features: career,
        },
        academics: {
          transcript_data_present: academics, terms_present: academics,
          gpa_computable: academics, ready_for_academic_features: academics,
        },
        overall: academics && career ? 'ready' : academics || career ? 'partial' : 'minimal',
      },
      provenance: {
        career_profile: career ? 'resume_parse' : null, certifications: [],
        work_experience: career ? ['resume_parse'] : [], projects: [],
        academics: academics ? ['transcript_parse'] : [], credit_type_limitation: null,
      },
    },
  }
}
