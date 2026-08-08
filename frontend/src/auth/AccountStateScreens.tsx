// The loading and not-usable-account screens, extracted from RequireAuth so
// RequireStudentAccount renders the identical thing rather than a lookalike.
//
// Nothing here is new UI: both were lifted verbatim out of RequireAuth, which
// now imports them back. A second gate needed the same two states, and two
// copies would have drifted the first time either message changed.

import type { StudentAccountState } from '../lib/studentAccount';

export function Spinner() {
  return (
    <div className="loading-screen">
      <div className="spinner" role="status" aria-label="Loading" />
    </div>
  );
}

interface StudentAccountProblemProps {
  studentAccount: StudentAccountState;
  onRetry(): void;
  onSignOut(): void;
}

/**
 * Shown when a session exists but its student account is not usable: either
 * nothing to provision from ('absent') or provisioning failed ('error').
 *
 * Deliberately not a redirect to /login -- that would read as "you're not
 * signed in", which is the wrong problem and invites a sign-in loop that
 * cannot succeed.
 */
export function StudentAccountProblem({
  studentAccount,
  onRetry,
  onSignOut,
}: StudentAccountProblemProps) {
  const isAbsent = studentAccount.status === 'absent';

  return (
    <div className="login-bg">
      <div className="login-card">
        <div className="login-header">
          <h1 className="login-logo">GradusIQ</h1>
          <p className="login-subtitle">
            {isAbsent ? 'No student profile' : 'Profile setup incomplete'}
          </p>
        </div>

        <div className="login-form">
          <p className="login-error" role="alert">
            {studentAccount.message ??
              'Your account is signed in but its student profile is not ready.'}
          </p>

          {!isAbsent && (
            <button type="button" className="btn btn-primary btn-full" onClick={onRetry}>
              Try again
            </button>
          )}

          <button
            type="button"
            className="btn btn-ghost btn-full"
            onClick={() => {
              void onSignOut();
            }}
          >
            Sign out
          </button>
        </div>

        <p className="login-note">
          {isAbsent
            ? 'Signing up creates the profile this account is missing.'
            : 'Your account exists — only the last setup step did not finish.'}
        </p>
      </div>
    </div>
  );
}
