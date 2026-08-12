import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../../auth/useAuth';
import type { ProfileCompletionRequest } from './ProfileCompletionContext';
import { ProfileCompletionForm } from './ProfileCompletionForm';

interface Props { request: ProfileCompletionRequest; onClose(): void; onComplete(): void; }

export function ProfileCompletionModal({ request, onClose, onComplete }: Props) {
  const { session, studentAccount, reloadStudentProfile } = useAuth();
  const dialogRef = useRef<HTMLDivElement>(null);
  const savingRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const profile = studentAccount.profile?.intelligence_profile;

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function keydown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !savingRef.current) { event.preventDefault(); onClose(); return; }
      if (event.key !== 'Tab' || !dialog) return;
      const focusable = [...dialog.querySelectorAll<HTMLElement>('button, input, select, a[href], [tabindex]:not([tabindex="-1"])')].filter((node) => !node.hasAttribute('disabled'));
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    window.addEventListener('keydown', keydown);
    return () => { window.removeEventListener('keydown', keydown); document.body.style.overflow = previousOverflow; request.trigger.focus(); };
  }, [onClose, request.trigger]);

  function updateSaving(value: boolean) { savingRef.current = value; setSaving(value); }

  if (!profile || !session) return null;
  return <div className="profile-modal-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}>
    <div className="profile-modal" role="dialog" aria-modal="true" aria-labelledby="profile-modal-title" aria-describedby="profile-modal-description" tabIndex={-1} ref={dialogRef}>
      <header className="profile-modal-header"><div><h2 id="profile-modal-title">Complete your profile</h2><p id="profile-modal-description">Add or update the details CampusIQ uses for personalized guidance.</p></div><button type="button" className="profile-modal-close" aria-label="Close profile completion" onClick={onClose} disabled={saving}>×</button></header>
      <ProfileCompletionForm profile={profile} accessToken={session.access_token} missingFields={request.missingFields} feature={request.feature} onCancel={onClose} onSavingChange={updateSaving} onSaved={async () => { await reloadStudentProfile(); onComplete(); }} />
    </div>
  </div>;
}
