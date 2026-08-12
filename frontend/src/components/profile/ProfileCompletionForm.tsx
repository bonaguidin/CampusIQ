import { FormEvent, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { updateProfile, type ProfileChanges } from '../../api/profile';
import { NO_INTENDED_MAJOR, isNoIntendedMajor } from '../../lib/majorSentinel';
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
  'student.major_intended': 'Required for FIT. Tick the box above if you are planning to switch majors.',
  'student.expected_graduation': 'Required for GAP so guidance matches your timeline.',
  'career.target_roles': 'Add at least one target role to run this analysis.',
  'career.interests': 'Add at least one career interest to run FIT.',
  'career.ai_anxiety_level': 'Optional context for how guidance discusses AI.',
};

export function ProfileCompletionForm({ profile, accessToken, missingFields = [], feature, onCancel, onSaved, onSavingChange }: Props) {
  const graduation = profile.identity.expected_graduation?.match(/^(Spring|Fall) (20\d{2})$/);
  const storedIntended = profile.academics.summary.major_intended ?? '';
  const initial = useMemo(() => ({
    classification: profile.identity.classification ?? '',
    majorCurrent: profile.academics.summary.major_current ?? '',
    majorIntended: storedIntended,
    // The sentinel is a stored answer ("staying"), never something the student
    // typed, so it drives the checkbox and leaves the text field empty rather
    // than showing "N/A" back as if it were a major they entered.
    switching: !isNoIntendedMajor(storedIntended),
    season: graduation?.[1] ?? '', year: graduation?.[2] ?? '',
    targetRoles: profile.career.target_roles,
    interests: profile.career.interests,
    anxiety: profile.career.ai_anxiety_level ?? '',
  }), [profile, storedIntended, graduation?.[1], graduation?.[2]]);
  const [classification, setClassification] = useState(initial.classification);
  const [majorCurrent, setMajorCurrent] = useState(initial.majorCurrent);
  const [switching, setSwitching] = useState(initial.switching);
  const [majorIntended, setMajorIntended] = useState(initial.switching ? initial.majorIntended : '');
  const [season, setSeason] = useState(initial.season);
  const [year, setYear] = useState(initial.year);
  const [targetRoles, setTargetRoles] = useState(initial.targetRoles);
  const [interests, setInterests] = useState(initial.interests);
  const [anxiety, setAnxiety] = useState(initial.anxiety);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const missing = new Set(missingFields.map((field) => field.path));
  const years = Array.from({ length: 12 }, (_, index) => String(new Date().getFullYear() + index));
  if (year && !years.includes(year)) years.unshift(year);

  // What the save writes for major_intended: the typed major when switching,
  // the sentinel when not. Never "" -- the API 422s on a blank string.
  const intendedToSave = switching ? majorIntended.trim() : NO_INTENDED_MAJOR;

  function validate() {
    const next: Record<string, string> = {};
    // Only a *switching* student owes an intended major. Not switching is a
    // complete answer to this field, so it satisfies the requirement.
    if (switching && !majorIntended.trim()) next['student.major_intended'] = 'Name the major you are switching to, or untick the box.';
    if (missing.has('career.target_roles') && targetRoles.length === 0) next['career.target_roles'] = HELP['career.target_roles'];
    if (missing.has('career.interests') && interests.length === 0) next['career.interests'] = HELP['career.interests'];
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
    if (intendedToSave !== initial.majorIntended) changes.major_intended = intendedToSave;
    const expected = season && year ? `${season} ${year}` : null;
    if (expected !== profile.identity.expected_graduation) changes.expected_graduation = expected;
    if (JSON.stringify(targetRoles) !== JSON.stringify(initial.targetRoles)) changes.target_roles = targetRoles;
    if (JSON.stringify(interests) !== JSON.stringify(initial.interests)) changes.interests = interests;
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

      <section className="profile-form-section">
        <h3 className="editable-section-title">Academic</h3>
        <div className="profile-form-grid">
          <label>Classification<input value={classification} onChange={(e) => setClassification(e.target.value)} /></label>
          <label>Current major<input value={majorCurrent} onChange={(e) => setMajorCurrent(e.target.value)} /></label>
        </div>
        {/* The switch decides whether the field below is answerable at all, so
            it sits above it and gates it, rather than asking the student to
            encode the same answer by typing a sentinel into the field. */}
        <label className="profile-form-check"><input type="checkbox" checked={switching} onChange={(e) => { setSwitching(e.target.checked); if (!e.target.checked) setMajorIntended(''); }} />I'm planning to switch majors</label>
        <label className={fieldClass('student.major_intended')}>Intended major<input value={majorIntended} onChange={(e) => setMajorIntended(e.target.value)} disabled={!switching} placeholder={switching ? 'e.g. Computer Science' : ''} aria-describedby="intended-major-help" /><small id="intended-major-help">{helper('student.major_intended') ?? (switching ? 'The major you are switching to.' : 'Not switching — we will record this as N/A.')}</small></label>
        <div className={fieldClass('student.expected_graduation')}><span className="form-label">Expected graduation</span><div className="profile-graduation"><label>Season<select value={season} onChange={(e) => setSeason(e.target.value)}><option value="">Not set</option><option>Spring</option><option>Fall</option></select></label><label>Year<select value={year} onChange={(e) => setYear(e.target.value)}><option value="">Not set</option>{years.map((value) => <option key={value}>{value}</option>)}</select></label></div>{helper('student.expected_graduation') && <small>{helper('student.expected_graduation')}</small>}</div>
      </section>

      <section className="profile-form-section">
        <h3 className="editable-section-title">Career direction</h3>
        <div className={fieldClass('career.target_roles')}><TagInput label="Target roles" value={targetRoles} onChange={setTargetRoles} placeholder="Add role" />{helper('career.target_roles') && <small>{helper('career.target_roles')}</small>}</div>
        <div className={fieldClass('career.interests')}><TagInput label="Career interests" value={interests} onChange={setInterests} placeholder="Add interest" />{helper('career.interests') && <small>{helper('career.interests')}</small>}</div>
      </section>

      <section className="profile-form-section">
        <h3 className="editable-section-title">AI comfort</h3>
        {/* No option stands for "unanswered". Null means never asked, which is
            a different state from 'not_sure' (asked, does not know) -- see the
            20260812143000 migration. An unselected group is how null looks. */}
        <fieldset className="profile-ai-group"><legend>How comfortable are you working with AI?</legend><div className="profile-ai-options">{AI_OPTIONS.map(([value, label]) => <label key={value}><input type="radio" name="ai-comfort" value={value} checked={anxiety === value} onChange={() => setAnxiety(value)} />{label}</label>)}</div><small>Skip this if you'd rather not say.</small></fieldset>
      </section>

      {/* Skills and experience are owned by the resume review screen, which
          parses them from the uploaded document. This surface used to offer a
          second, competing place to type them; it now says where they live. */}
      <p className="profile-form-note"><span className="profile-form-note-icon" aria-hidden="true">ⓘ</span><span>Skills and work experience are edited in <Link to="/resume">resume review</Link>.</span></p>

      {failure && <p className="profile-form-error" role="alert">{failure}</p>}
      <div className="profile-form-actions"><button type="button" className="btn btn-ghost" onClick={onCancel} disabled={saving}>Cancel</button><button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</button></div>
    </form>
  );
}
