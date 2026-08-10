import React from 'react';
import ReactDOM from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import type { Session } from '@supabase/supabase-js';
import { AuthContext, type AuthContextValue } from './auth/AuthContext';
import { StudentAccountProblem } from './auth/AccountStateScreens';
import { AuthenticatedDashboard } from './pages/AuthenticatedDashboard';
import type { StudentIntelligenceProfile } from './types/studentIntelligenceProfile';
import './index.css';

const mode = new URLSearchParams(location.search).get('mode') ?? 'complete';
const institution = new URLSearchParams(location.search).get('institution') === 'smu'
  ? 'Southern Methodist University'
  : 'Texas A&M University';

const base: StudentIntelligenceProfile = {
  contract_version: '1.0',
  identity: { student_id: 'student-real', name: 'Alex Morgan', classification: 'Sophomore', expected_graduation: '2028-05', onboarding_stage: 3 },
  institution: { id: 'institution-real', name: institution, relationship: 'home' },
  academics: {
    summary: { major_current: 'Computer Science', major_intended: 'Data Science', confirmed_course_count: 1, completed_hours: 3, in_progress_hours: 0, earned_hours: 3 },
    terms: [{ id: 'term-1', institution_id: 'institution-real', label: 'Fall 2025', year: 2025, season: 'fall', sequence: 1 }],
    courses: [{ id: 'course-1', term_id: 'term-1', institution_id: 'institution-real', course_code: 'CS 101', title: 'Introduction to Computing', credit_hours: 3, letter_grade: 'A', credit_type: 'resident', status: 'completed', source: 'transcript_parse' }],
    gpa: { official: 4, projected: 4, computable: true, source: 'gpa_service' },
    repeat_exclusions: [],
  },
  career: {
    confirmed: true, target_roles: ['Software Engineer'], interests: ['systems'], career_goals: 'Build reliable software', geographic_preference: null, ai_anxiety_level: null,
    skills: { technical: ['TypeScript'], soft: ['Communication'], ai_exposure: 'Coursework' },
    certifications: [{ name: 'Cloud Fundamentals', issuer: 'Example', source: 'resume_parse' }],
    work_experience: [{ employer: 'Acme', role: 'Intern', source: 'resume_parse' }],
    projects: [{ name: 'Planner', description: 'A planning app', source: 'manual' }],
  },
  completeness: {
    career: { confirmed_profile: true, target_role_present: true, skills_present: true, certifications_present: true, work_experience_present: true, projects_present: true, ready_for_career_features: true },
    academics: { transcript_data_present: true, terms_present: true, gpa_computable: true, ready_for_academic_features: true },
    overall: 'ready',
  },
  provenance: { career_profile: 'resume_parse', certifications: ['resume_parse'], work_experience: ['resume_parse'], projects: ['manual'], academics: ['transcript_parse'], credit_type_limitation: 'Transcript credit classification limitation.' },
};

const profile = structuredClone(base);
if (mode === 'career' || mode === 'minimal') {
  profile.academics.courses = [];
  profile.academics.terms = [];
  profile.academics.gpa = { official: null, projected: null, computable: false, source: 'gpa_service' };
  profile.academics.summary.confirmed_course_count = 0;
  profile.completeness.academics = { transcript_data_present: false, terms_present: false, gpa_computable: false, ready_for_academic_features: false };
}
if (mode === 'academic' || mode === 'minimal') {
  profile.career = { confirmed: false, target_roles: [], interests: [], career_goals: null, geographic_preference: null, ai_anxiety_level: null, skills: { technical: [], soft: [], ai_exposure: null }, certifications: [], work_experience: [], projects: [] };
  profile.completeness.career = { confirmed_profile: false, target_role_present: false, skills_present: false, certifications_present: false, work_experience_present: false, projects_present: false, ready_for_career_features: false };
}
if (mode !== 'complete') profile.completeness.overall = mode === 'minimal' ? 'minimal' : 'partial';

const session = { access_token: 'real-access-token' } as Session;
const context = {
  profile: null, slug: null, loading: false, profileLoading: false, sessionLoading: false,
  login: async () => {}, logout: () => {}, updateCareer: async () => {}, resetCareer: async () => {},
  session, user: null, signInWithPassword: async () => {}, signUpWithPassword: async () => {}, signOutSession: async () => {},
  studentAccount: { status: 'ready', profile: { student: { id: 'student-real', name: profile.identity.name, institution: profile.institution.name }, career: null, intelligence_profile: profile }, message: null },
  refreshStudentAccount: () => {},
} as AuthContextValue;

const app = mode === 'error'
  ? <StudentAccountProblem studentAccount={{ status: 'error', profile: null, message: 'Profile API failed.' }} onRetry={() => document.body.dataset.retried = 'yes'} onSignOut={() => {}} />
  : <AuthContext.Provider value={context}><MemoryRouter><AuthenticatedDashboard /></MemoryRouter></AuthContext.Provider>;

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode>{app}</React.StrictMode>);
