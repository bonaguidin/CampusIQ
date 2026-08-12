import { FormEvent, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { updateProfile, type ProfileChanges } from '../../api/profile';
import type { MissingField } from '../../types/analysis';
import type { StudentIntelligenceProfile } from '../../types/studentIntelligenceProfile';
import { TagInput } from '../TagInput';

interface Props {
  profile: StudentIntelligenceProfile;
  accessToken: string;
  missingFields?: MissingField[];
  feature?: string;
  onCancel(): void;
  onSaved(): Promise<void>;
  onSavingChange?(saving: boolean): void;
}

const AI_OPTIONS = [
  ['low', 'Low'], ['moderate', 'Moderate'], ['high', 'High'], ['not_sure', 'Not sure'],
] as const;

const HELP: Record<string, string> = {
  'student.major_intended': 'Required for FIT. Use N/A if you are staying in your current major.',
  'student.expected_graduation': 'Required for GAP so guidance matches your timeline.',
  'career.target_roles': 'Add at least one target role to run this analysis.',
  'career.interests': 'Add at least one career interest to run FIT.',
  'career.skills_self_reported': 'Add at least one technical or professional skill.',
  'career.ai_anxiety_level': 'Optional context for how guidance discusses AI.',
};

export function ProfileCompletionForm({ profile, accessToken, missingFields = [], feature, onCancel, onSaved, onSavingChange }: Props) {
  const graduation = profile.identity.expected_graduation?.match(/^(Spring|Fall) (20\d{2})$/);
  const initial = useMemo(() => ({
    classification: profile.identity.classification ?? '',
    majorCurrent: profile.academics.summary.major_current ?? '',
    majorIntended: profile.academics.summary.major_intended ?? '',
    season: graduation?.[1] ?? '', year: graduation?.[2] ?? '',
    targetRoles: profile.career.target_roles,
    interests: profile.career.interests,
    technical: profile.career.skills.technical,
    professional: profile.career.skills.soft,
    anxiety: profile.career.ai_anxiety_level ?? '',
  }), [profile, graduation?.[1], graduation?.[2]]);
  const [classification, setClassification] = useState(initial.classification);
  const [majorCurrent, setMajorCurrent] = useState(initial.majorCurrent);
  const [majorIntended, setMajorIntended] = useState(initial.majorIntended);
  const [season, setSeason] = useState(initial.season);
  const [year, setYear] = useState(initial.year);
  const [targetRoles, setTargetRoles] = useState(initial.targetRoles);
  const [interests, setInterests] = useState(initial.interests);
  const [technical, setTechnical] = useState(initial.technical);
  const [professional, setProfessional] = useState(initial.professional);
  const [anxiety, setAnxiety] = useState(initial.anxiety);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const missing = new Set(missingFields.map((field) => field.path));
  const years = Array.from({ length: 12 }, (_, index) => String(new Date().getFullYear() + index));
  if (year && !years.includes(year)) years.unshift(year);

  function validate() {
    const next: Record<string, string> = {};
    if (missing.has('student.major_intended') && !majorIntended.trim()) next['student.major_intended'] = HELP['student.major_intended'];
    if (missing.has('career.target_roles') && targetRoles.length === 0) next['career.target_roles'] = HELP['career.target_roles'];
    if (missing.has('career.interests') && interests.length === 0) next['career.interests'] = HELP['career.interests'];
    if (missing.has('career.skills_self_reported') && technical.length + professional.length === 0) next['career.skills_self_reported'] = HELP['career.skills_self_reported'];
    if (missing.has('student.expected_graduation') && (!season || !year)) next['student.expected_graduation'] = HELP['student.expected_graduation'];
    if ((season && !year) || (!season && year)) next['student.expected_graduation'] = 'Choose both a graduation season and year, or leave both blank.';
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!validate()) return;
    const changes: ProfileChanges = {};
    if (classification.trim() !== initial.classification) changes.classification = classification.trim();
    if (majorCurrent.trim() !== initial.majorCurrent) changes.major_current = majorCurrent.trim();
    if (majorIntended.trim() !== initial.majorIntended) changes.major_intended = majorIntended.trim();
    const expected = season && year ? `${season} ${year}` : null;
    if (expected !== profile.identity.expected_graduation) changes.expected_graduation = expected;
    if (JSON.stringify(targetRoles) !== JSON.stringify(initial.targetRoles)) changes.target_roles = targetRoles;
    if (JSON.stringify(interests) !== JSON.stringify(initial.interests)) changes.interests = interests;
    if (JSON.stringify(technical) !== JSON.stringify(initial.technical)) changes.skills_technical = technical;
    if (JSON.stringify(professional) !== JSON.stringify(initial.professional)) changes.skills_soft = professional;
    if (anxiety !== initial.anxiety) changes.ai_anxiety_level = anxiety ? anxiety as NonNullable<ProfileChanges['ai_anxiety_level']> : null;
    setSaving(true); onSavingChange?.(true); setFailure(null);
    try {
      if (Object.keys(changes).length > 0) await updateProfile(accessToken, changes);
      await onSaved();
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'Your profile could not be saved.');
    } finally {
      setSaving(false); onSavingChange?.(false);
    }
  }

  const fieldClass = (path: string) => `profile-form-field${missing.has(path) ? ' profile-form-field--needed' : ''}`;
  const helper = (path: string) => errors[path] ?? (missing.has(path) ? HELP[path] : null);
  return (
    <form className="profile-completion-form" onSubmit={(event) => { void submit(event); }} noValidate>
      {feature && missingFields.length > 0 && <p className="profile-context"><strong>{missingFields.length} {missingFields.length === 1 ? 'detail' : 'details'} needed for {feature}</strong></p>}
      <section className="profile-form-section"><h3>Academic</h3><div className="profile-form-grid">
        <label>Classification<input value={classification} onChange={(e) => setClassification(e.target.value)} /></label>
        <label>Current major<input value={majorCurrent} onChange={(e) => setMajorCurrent(e.target.value)} /></label>
        <label className={fieldClass('student.major_intended')}>Intended major<input value={majorIntended} onChange={(e) => setMajorIntended(e.target.value)} aria-describedby="intended-major-help" /><small id="intended-major-help">{helper('student.major_intended') ?? 'Use N/A if you are staying in your current major.'}</small></label>
        <div className={fieldClass('student.expected_graduation')}><span className="form-label">Expected graduation</span><div className="profile-graduation"><label>Season<select value={season} onChange={(e) => setSeason(e.target.value)}><option value="">Not set</option><option>Spring</option><option>Fall</option></select></label><label>Year<select value={year} onChange={(e) => setYear(e.target.value)}><option value="">Not set</option>{years.map((value) => <option key={value}>{value}</option>)}</select></label></div>{helper('student.expected_graduation') && <small>{helper('student.expected_graduation')}</small>}</div>
      </div></section>
      <section className="profile-form-section"><h3>Career Direction</h3><div className={fieldClass('career.target_roles')}><TagInput label="Target roles" value={targetRoles} onChange={setTargetRoles} placeholder="Add role" />{helper('career.target_roles') && <small>{helper('career.target_roles')}</small>}</div><div className={fieldClass('career.interests')}><TagInput label="Career interests" value={interests} onChange={setInterests} placeholder="Add interest" />{helper('career.interests') && <small>{helper('career.interests')}</small>}</div></section>
      <section className="profile-form-section"><h3>Skills</h3><div className={fieldClass('career.skills_self_reported')}><TagInput label="Technical skills" value={technical} onChange={setTechnical} placeholder="Add skill" /><TagInput label="Professional skills" value={professional} onChange={setProfessional} placeholder="Add skill" />{helper('career.skills_self_reported') && <small>{helper('career.skills_self_reported')}</small>}</div></section>
      <section className="profile-form-section"><h3>AI &amp; Career Readiness</h3><fieldset className="profile-ai-group"><legend>How comfortable are you working with AI?</legend><div className="profile-ai-options">{AI_OPTIONS.map(([value, label]) => <label key={value}><input type="radio" name="ai-comfort" value={value} checked={anxiety === value} onChange={() => setAnxiety(value)} />{label}</label>)}<label><input type="radio" name="ai-comfort" value="" checked={anxiety === ''} onChange={() => setAnxiety('')} />Not answered</label></div></fieldset></section>
      {missing.has('career.work_experience') && <p className="profile-form-field--needed">Work experience is maintained with your resume record. <Link to="/resume">Review or upload your resume</Link>.</p>}
      {failure && <p className="profile-form-error" role="alert">{failure}</p>}
      <div className="profile-form-actions"><button type="button" className="btn btn-ghost" onClick={onCancel} disabled={saving}>Cancel</button><button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</button></div>
    </form>
  );
}
