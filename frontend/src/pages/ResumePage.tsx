import { useEffect, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { ResumeUpload } from '../components/ResumeUpload';
import { CareerReview } from '../components/CareerReview';
import { GoToDashboard } from '../components/GoToDashboard';
import { fetchCareerReview } from '../api/resume';
import type {
  NormalizedConfirm,
  NormalizedReview,
  NormalizedUpload,
  ReviewSections,
} from '../lib/resumeApi.mjs';

type Step = 'checking' | 'upload' | 'review' | 'recovery_error' | 'done';

/**
 * The three-step resume flow, held on one route.
 *
 * ON THE TERMINAL STATE: confirming shows a static success screen here rather
 * than AUTO-navigating anywhere. This page remains the focused resume
 * onboarding workflow and keeps the static confirmation so the student can
 * review the completed step at their own pace.
 *
 * What that reasoning never justified was leaving them with no exit: the
 * screen used to end on "you can close this page", which is not an answer to
 * "what now". It now offers an explicit link to /dashboard (GoToDashboard,
 * shared with the transcript flow's identical ending). Not navigating FOR them
 * and giving them nowhere to go were always two different decisions; only the
 * first one was intended.
 */
export function ResumePage() {
  const { session } = useAuth();
  const accessToken = session?.access_token ?? '';

  return accessToken ? <ResumeFlow accessToken={accessToken} /> : <ResumeLoading />;
}

export function ResumeFlow({ accessToken }: { accessToken: string }) {
  const [step, setStep] = useState<Step>('checking');
  const [uploaded, setUploaded] = useState<NormalizedUpload | null>(null);
  const [confirmed, setConfirmed] = useState<NormalizedConfirm | null>(null);
  const [recoveredSections, setRecoveredSections] = useState<ReviewSections | null>(null);
  const [recoveryFailure, setRecoveryFailure] = useState<NormalizedReview | null>(null);
  const [recoveryAttempt, setRecoveryAttempt] = useState(0);
  // Provenance for the review masthead. Held here because it is the only place
  // that sees both the upload and the review step.
  const [source, setSource] = useState<{ name: string; at: Date } | null>(null);

  useEffect(() => {
    let active = true;
    setStep('checking');
    setRecoveryFailure(null);
    void fetchCareerReview(accessToken).then((result) => {
      if (!active) return;
      if (!result.ok) {
        setRecoveryFailure(result);
        setStep('recovery_error');
        return;
      }
      if (result.pendingCount > 0) {
        setRecoveredSections(result.sections);
        setStep('review');
      } else {
        setRecoveredSections(null);
        setStep('upload');
      }
    });
    return () => {
      active = false;
    };
  }, [accessToken, recoveryAttempt]);

  function handleUploaded(result: NormalizedUpload, fileName: string) {
    setUploaded(result);
    setRecoveredSections(null);
    setSource({ name: fileName, at: new Date() });
    setStep('review');
  }

  function handleConfirmed(result: NormalizedConfirm) {
    setConfirmed(result);
    setStep('done');
  }

  if (step === 'checking') return <ResumeLoading />;

  if (step === 'recovery_error') {
    return (
      <div className="login-bg">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Could not check your resume</p>
          </div>
          <div className="login-form">
            <p className="login-error" role="alert">
              {recoveryFailure?.message ?? 'Your saved review could not be checked.'}
            </p>
            <button
              type="button"
              className="btn btn-primary btn-full"
              onClick={() => setRecoveryAttempt((attempt) => attempt + 1)}
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (step === 'upload') {
    return <ResumeUpload accessToken={accessToken} onUploaded={handleUploaded} />;
  }

  if (step === 'review') {
    return (
      <CareerReview
        accessToken={accessToken}
        onConfirmed={handleConfirmed}
        initialSections={recoveredSections ?? undefined}
        sourceName={source?.name}
        parsedAt={source?.at}
      />
    );
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
          <GoToDashboard />
        </div>

        <p className="login-note">Nothing else is needed from you right now.</p>
      </div>
    </div>
  );
}

function ResumeLoading() {
  return (
    <div className="loading-screen">
      <div className="spinner" role="status" aria-label="Checking for a saved resume review" />
    </div>
  );
}
