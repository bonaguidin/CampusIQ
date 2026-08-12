import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { ProfileCompletionForm } from '../components/profile/ProfileCompletionForm';

/**
 * The fields this page can focus -- i.e. exactly the fields its form owns.
 *
 * career.skills_self_reported and career.work_experience are absent on
 * purpose: they belong to /resume (see RESUME_OWNED_PATHS in AnalysisPanel),
 * and naming them here would let ?field= highlight something the form no
 * longer renders. An unknown path already falls through to no highlight.
 */
const LABELS: Record<string, string> = {
  'student.major_intended': 'Intended major', 'student.expected_graduation': 'Expected graduation',
  'career.target_roles': 'Target roles', 'career.interests': 'Career interests',
  'career.ai_anxiety_level': 'AI comfort level',
};

export function ProfileCompletionPage() {
  const { session, studentAccount, reloadStudentProfile } = useAuth();
  const navigate = useNavigate(); const [params] = useSearchParams();
  const profile = studentAccount.profile?.intelligence_profile; const path = params.get('field');
  if (!profile || !session) return null;
  const missingFields = path && LABELS[path] ? [{ path, label: LABELS[path] }] : [];
  return <main className="profile-page"><div className="profile-card"><header className="profile-modal-header"><div><h1>Complete your profile</h1><p>Add or update the details GradusIQ uses for personalized guidance.</p></div></header><ProfileCompletionForm profile={profile} accessToken={session.access_token} missingFields={missingFields} onCancel={() => void navigate('/dashboard')} onSaved={async () => { await reloadStudentProfile(); void navigate('/dashboard'); }} /></div></main>;
}
