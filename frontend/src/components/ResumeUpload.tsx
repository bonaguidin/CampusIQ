import { useRef, useState } from 'react';
import { uploadResume } from '../api/resume';
import type { NormalizedUpload } from '../lib/resumeApi.mjs';

interface ResumeUploadProps {
  accessToken: string;
  onUploaded(result: NormalizedUpload): void;
}

const ACCEPTED = '.pdf,.docx';

/**
 * Kinds a different file will not fix -- offer "sign in again" or nothing,
 * rather than inviting the student to retry the same upload pointlessly.
 */
const NOT_RETRYABLE = new Set(['unauthenticated', 'no_student_profile', 'not_configured']);

/** Kinds where retrying the SAME file is the right advice. */
const RETRY_SAME_FILE = new Set([
  'parse_failed',
  'rate_limited',
  'ai_busy',
  'backend_unavailable',
  'network',
]);

function hintFor(kind: string): string | null {
  switch (kind) {
    case 'not_a_resume':
      return 'Check you picked the right file — this looked like a different kind of document.';
    case 'unparseable':
    case 'empty':
      return 'Scanned or photographed resumes have no text layer. Export a PDF from the original document instead.';
    case 'unsupported_format':
      return 'Only PDF and .docx are supported. Older .doc files need to be re-saved.';
    case 'file_too_large':
      return 'Most resumes are well under a megabyte — check you did not attach a portfolio.';
    case 'rate_limited':
      return 'Wait about a minute before trying again.';
    case 'ai_busy':
      return 'This usually clears in a few seconds.';
    case 'parse_failed':
      return 'Nothing was saved, so uploading again is safe.';
    default:
      return null;
  }
}

export function ResumeUpload({ accessToken, onUploaded }: ResumeUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedUpload | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!file || busy) return;

    setBusy(true);
    setFailure(null);
    try {
      const result = await uploadResume(accessToken, file);
      if (result.ok) {
        onUploaded(result);
        return;
      }
      setFailure(result);
    } finally {
      setBusy(false);
    }
  }

  function clearSelection() {
    setFile(null);
    setFailure(null);
    if (inputRef.current) inputRef.current.value = '';
  }

  const hint = failure ? hintFor(failure.kind) : null;

  return (
    <div className="login-bg">
      <div className="login-card resume-card">
        <div className="login-header">
          <h1 className="login-logo">GradusIQ</h1>
          <p className="login-subtitle">Add your resume</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <p className="resume-intro">
            Upload your resume and we will pull out your experience, projects, and
            certifications. You will get to review and correct everything before anything is
            saved to your profile.
          </p>

          <div className="form-group">
            <label className="form-label" htmlFor="resume-file">
              Resume file
            </label>
            <input
              id="resume-file"
              ref={inputRef}
              className="form-input resume-file-input"
              type="file"
              accept={ACCEPTED}
              disabled={busy}
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setFailure(null);
              }}
            />
            <p className="resume-file-note">PDF or Word (.docx), up to 10 MB.</p>
          </div>

          {failure && (
            <div className="login-error" role="alert">
              <p>{failure.message}</p>
              {hint && <p className="resume-error-hint">{hint}</p>}
              {failure.kind === 'parse_failed' && failure.errors.length > 0 && (
                <p className="resume-error-detail">{failure.errors[0]}</p>
              )}
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary btn-full"
            disabled={!file || busy}
          >
            {busy ? <span className="btn-loading">Reading your resume…</span> : 'Upload resume'}
          </button>

          {failure && !NOT_RETRYABLE.has(failure.kind) && (
            <button
              type="button"
              className="btn btn-ghost btn-full"
              onClick={clearSelection}
              disabled={busy}
            >
              {RETRY_SAME_FILE.has(failure.kind) ? 'Start over' : 'Choose a different file'}
            </button>
          )}
        </form>

        <p className="login-note">
          Reading a resume takes a few seconds. Nothing is saved to your profile until you
          confirm it on the next screen.
        </p>
      </div>
    </div>
  );
}
