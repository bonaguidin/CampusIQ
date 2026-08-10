import { useEffect, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { fetchTranscriptReview } from '../api/transcript';
import { TranscriptUpload } from '../components/TranscriptUpload';
import { TranscriptReview } from '../components/TranscriptReview';
import type {
  TranscriptConfirmResult,
  TranscriptReviewResult,
  TranscriptUploadResult,
} from '../lib/transcriptApi.mjs';

type Step = 'checking' | 'upload' | 'review' | 'error' | 'done';

export function TranscriptPage() {
  const { session } = useAuth();
  return session?.access_token ? (
    <TranscriptFlow accessToken={session.access_token} />
  ) : (
    <TranscriptLoading />
  );
}

export function TranscriptFlow({ accessToken }: { accessToken: string }) {
  const [step, setStep] = useState<Step>('checking');
  const [review, setReview] = useState<TranscriptReviewResult | null>(null);
  const [sourceName, setSourceName] = useState<string>();
  const [uploadResult, setUploadResult] = useState<TranscriptUploadResult | null>(null);
  const [confirmed, setConfirmed] = useState<TranscriptConfirmResult | null>(null);
  const [attempt, setAttempt] = useState(0);

  async function load() {
    setStep('checking');
    const result = await fetchTranscriptReview(accessToken);
    setReview(result);
    setStep(result.ok ? (result.records.length ? 'review' : 'upload') : 'error');
  }

  useEffect(() => {
    let active = true;
    setStep('checking');
    void fetchTranscriptReview(accessToken).then((result) => {
      if (!active) return;
      setReview(result);
      setStep(result.ok ? (result.records.length ? 'review' : 'upload') : 'error');
    });
    return () => {
      active = false;
    };
  }, [accessToken, attempt]);

  if (step === 'checking') return <TranscriptLoading />;

  if (step === 'error') {
    return (
      <div className="login-bg">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Could not check your transcript</p>
          </div>
          <div className="login-form">
            <p className="login-error" role="alert">
              {review?.message ?? 'Your saved transcript review could not be loaded.'}
            </p>
            <button
              type="button"
              className="btn btn-primary btn-full"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (step === 'upload') {
    return (
      <TranscriptUpload
        accessToken={accessToken}
        onUploaded={async (upload: TranscriptUploadResult, fileName: string) => {
          setUploadResult(upload);
          setSourceName(fileName);
          await load();
        }}
      />
    );
  }

  if (step === 'review' && review?.ok) {
    return (
      <TranscriptReview
        accessToken={accessToken}
        review={review}
        uploadResult={uploadResult}
        sourceName={sourceName}
        onConfirmed={(result) => {
          setConfirmed(result);
          setStep('done');
        }}
      />
    );
  }

  const count = confirmed?.confirmed ?? 0;
  return (
    <div className="login-bg">
      <div className="login-card">
        <div className="login-header">
          <h1 className="login-logo">GradusIQ</h1>
          <p className="login-subtitle">Your transcript is saved</p>
        </div>
        <div className="login-form">
          <p className="resume-intro">
            {count === 1
              ? 'One course has been confirmed and added to your academic record.'
              : `${String(count)} courses have been confirmed and added to your academic record.`}
          </p>
        </div>
        <p className="login-note">
          Your GPA is calculated from these records. A refresh will not restore this completed
          review.
        </p>
      </div>
    </div>
  );
}

function TranscriptLoading() {
  return (
    <div className="loading-screen">
      <div className="spinner" role="status" aria-label="Checking for a saved transcript review" />
    </div>
  );
}
