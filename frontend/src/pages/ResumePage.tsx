import { useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { ResumeUpload } from '../components/ResumeUpload';
import { CareerReview } from '../components/CareerReview';
import type { NormalizedConfirm, NormalizedUpload } from '../lib/resumeApi.mjs';

type Step = 'upload' | 'review' | 'done';

/**
 * The three-step resume flow, held on one route.
 *
 * ON THE TERMINAL STATE: confirming shows a static success screen here rather
 * than navigating anywhere. /dashboard renders blank for a real student today
 * -- DashboardPage reads the demo `profile` and dereferences profile.courses --
 * so sending them there would look like a bug rather than a success. Returning
 * to the upload step would offer another upload as if the flow continues, which
 * it does not. A static confirmation is the honest state until a real next
 * destination exists.
 */
export function ResumePage() {
  const { session } = useAuth();
  const [step, setStep] = useState<Step>('upload');
  const [uploaded, setUploaded] = useState<NormalizedUpload | null>(null);
  const [confirmed, setConfirmed] = useState<NormalizedConfirm | null>(null);

  const accessToken = session?.access_token ?? '';

  // RequireStudentAccount guarantees a session before this renders; this is a
  // belt-and-braces guard, not an expected state.
  if (!accessToken) {
    return (
      <div className="loading-screen">
        <div className="spinner" role="status" aria-label="Loading" />
      </div>
    );
  }

  function handleUploaded(result: NormalizedUpload) {
    setUploaded(result);
    setStep('review');
  }

  function handleConfirmed(result: NormalizedConfirm) {
    setConfirmed(result);
    setStep('done');
  }

  if (step === 'upload') {
    return <ResumeUpload accessToken={accessToken} onUploaded={handleUploaded} />;
  }

  if (step === 'review') {
    return <CareerReview accessToken={accessToken} onConfirmed={handleConfirmed} />;
  }

  const total = confirmed?.totalConfirmed ?? 0;
  const skipped = uploaded?.totals.skipped_duplicate ?? 0;

  return (
    <div className="login-bg">
      <div className="login-card">
        <div className="login-header">
          <h1 className="login-logo">GradusIQ</h1>
          <p className="login-subtitle">Your profile has been saved</p>
        </div>

        <div className="login-form">
          <p className="resume-intro">
            {total === 1
              ? 'One entry has been confirmed and added to your profile.'
              : `${String(total)} entries have been confirmed and added to your profile.`}
          </p>
          {skipped > 0 && (
            <p className="resume-file-note">
              {skipped === 1
                ? 'One entry was already on your profile and was left as it was.'
                : `${String(skipped)} entries were already on your profile and were left as they were.`}
            </p>
          )}
        </div>

        <p className="login-note">
          Nothing else is needed from you right now. You can close this page.
        </p>
      </div>
    </div>
  );
}
