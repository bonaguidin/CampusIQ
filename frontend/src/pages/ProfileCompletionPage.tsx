import { FormEvent, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { updateProfile } from '../api/profile';
import { useAuth } from '../auth/useAuth';

const seasons = ['Spring', 'Fall'] as const;
const splitList = (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean);

export function ProfileCompletionPage() {
  const { session, studentAccount, reloadStudentProfile } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const profile = studentAccount.profile?.intelligence_profile;
  const accessToken = session?.access_token;
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const graduation = profile?.identity.expected_graduation?.match(/^(Spring|Fall) (20\d{2})$/);
  const [classification, setClassification] = useState(profile?.identity.classification ?? '');
  const [majorCurrent, setMajorCurrent] = useState(profile?.academics.summary.major_current ?? '');
  const [majorIntended, setMajorIntended] = useState(profile?.academics.summary.major_intended ?? '');
  const [season, setSeason] = useState(graduation?.[1] ?? 'Spring');
  const [year, setYear] = useState(graduation?.[2] ?? String(new Date().getFullYear() + 2));
  const [anxiety, setAnxiety] = useState(profile?.career.ai_anxiety_level ?? '');
  const [targetRoles, setTargetRoles] = useState(profile?.career.target_roles.join(', ') ?? '');
  const [interests, setInterests] = useState(profile?.career.interests.join(', ') ?? '');
  const [technicalSkills, setTechnicalSkills] = useState(profile?.career.skills.technical.join(', ') ?? '');
  const [softSkills, setSoftSkills] = useState(profile?.career.skills.soft.join(', ') ?? '');
  const highlighted = params.get('field');
  const returnTo = useMemo(() => {
    const candidate = (location.state as { from?: unknown } | null)?.from;
    return typeof candidate === 'string' && candidate.startsWith('/') ? candidate : '/dashboard';
  }, [location.state]);

  if (!profile || !accessToken) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!accessToken) return;
    setSaving(true);
    setMessage(null);
    try {
      await updateProfile(accessToken, {
        classification,
        major_current: majorCurrent,
        major_intended: majorIntended,
        expected_graduation: `${season} ${year}`,
        ai_anxiety_level: anxiety
          ? anxiety as 'low' | 'moderate' | 'high' | 'not_sure'
          : null,
        target_roles: splitList(targetRoles),
        interests: splitList(interests),
        skills_technical: splitList(technicalSkills),
        skills_soft: splitList(softSkills),
      });
      await reloadStudentProfile();
      setMessage('Profile saved. Your confirmed profile is up to date.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Your profile could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="profile-page">
      <div className="profile-card">
        <Link to={returnTo} className="profile-back">← Back to dashboard</Link>
        <h1>Complete your profile</h1>
        <p>Keep these details accurate so your FIT and GAP guidance uses the right context.</p>
        <form onSubmit={(event) => { void submit(event); }}>
          <label>Classification<input value={classification} onChange={(e) => setClassification(e.target.value)} required /></label>
          <label>Current major<input value={majorCurrent} onChange={(e) => setMajorCurrent(e.target.value)} required /></label>
          <label>Intended major<input value={majorIntended} onChange={(e) => setMajorIntended(e.target.value)} required aria-describedby="major-help" /></label>
          <small id="major-help">Use N/A if you intentionally do not have a different intended major.</small>
          <label className={highlighted === 'career.target_roles' ? 'profile-highlight' : ''}>Target roles<input value={targetRoles} onChange={(e) => setTargetRoles(e.target.value)} placeholder="Software Engineer, Product Manager" required /></label>
          <label className={highlighted === 'career.interests' ? 'profile-highlight' : ''}>Career interests<input value={interests} onChange={(e) => setInterests(e.target.value)} placeholder="Robotics, healthcare technology" required /></label>
          <label>Technical skills<input value={technicalSkills} onChange={(e) => setTechnicalSkills(e.target.value)} placeholder="Python, SQL" /></label>
          <label className={highlighted === 'career.skills_self_reported' ? 'profile-highlight' : ''}>Professional skills<input value={softSkills} onChange={(e) => setSoftSkills(e.target.value)} placeholder="Communication, leadership" /></label>
          <fieldset className={highlighted === 'student.expected_graduation' ? 'profile-highlight' : ''}>
            <legend>Expected graduation</legend>
            <label>Season<select value={season} onChange={(e) => setSeason(e.target.value)}>{seasons.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label>Year<input type="number" min="2000" max="2099" value={year} onChange={(e) => setYear(e.target.value)} required /></label>
          </fieldset>
          <label className={highlighted === 'career.ai_anxiety_level' ? 'profile-highlight' : ''}>AI comfort level
            <select value={anxiety} onChange={(e) => setAnxiety(e.target.value)}>
              <option value="">Not answered</option><option value="low">Low concern</option><option value="moderate">Moderate concern</option><option value="high">High concern</option><option value="not_sure">Not sure</option>
            </select>
          </label>
          {highlighted === 'career.work_experience' && <p className="profile-highlight">Work experience is maintained with your resume record. <Link to="/resume">Review or upload your resume</Link>.</p>}
          {message && <p role="status" className="profile-message">{message}</p>}
          <div className="profile-actions"><button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</button><button type="button" className="btn" onClick={() => void navigate(returnTo)}>Done</button></div>
        </form>
      </div>
    </main>
  );
}
