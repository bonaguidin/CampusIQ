import { Navigate } from 'react-router-dom';
import { useAuth } from './useAuth';

interface RequireAuthProps {
  children: React.ReactNode;
}

function Spinner() {
  return (
    <div className="loading-screen">
      <div className="spinner" role="status" aria-label="Loading" />
    </div>
  );
}

/**
 * Gates the dashboard on one of two independent grants:
 *
 *   DEMO PATH  -- a StudentProfile from staticJsonAdapter. Unchanged: if it is
 *                 present, children render, exactly as before. Nothing below
 *                 runs for a demo session.
 *
 *   SESSION PATH -- a Supabase session AND a confirmed `students` row. A
 *                 session on its own is not enough and never was: the row is
 *                 what every /api/v2/student/me/* route resolves the caller
 *                 through, so rendering the dashboard without one produces a
 *                 page of 404s.
 *
 * ON THE TWO LOADING FLAGS: they can differ, and are not collapsed here.
 * `profileLoading` covers the sessionStorage demo restore; `sessionLoading`
 * covers supabase.auth.getSession(). Both must be settled before the *routing*
 * decision, because until then "no demo profile" and "no session" are both
 * merely unknown, and either would bounce a legitimate user to /login. Once
 * they are settled they are never consulted again: everything after that point
 * is driven by `studentAccount.status`, which is the only signal that tracks
 * provisioning. In particular a signed-in user's dashboard access never waits
 * on the demo adapter's own work.
 */
export function RequireAuth({ children }: RequireAuthProps) {
  const {
    profile,
    profileLoading,
    sessionLoading,
    session,
    studentAccount,
    refreshStudentAccount,
    signOutSession,
  } = useAuth();

  // Demo path: identical behavior to before this change.
  if (profile) {
    return <>{children}</>;
  }

  // Neither grant can be ruled out yet.
  if (profileLoading || sessionLoading) {
    return <Spinner />;
  }

  // 1. No session (and no demo profile) -> sign in.
  if (!session) {
    return <Navigate to="/login" replace />;
  }

  // 2. Session exists; the students-row question is still open. 'no-session' is
  //    the one-render gap before the provisioning effect starts, and reads the
  //    same way here.
  if (studentAccount.status === 'checking' || studentAccount.status === 'no-session') {
    return <Spinner />;
  }

  // 3. Session plus a confirmed students row, pre-existing or just provisioned.
  if (studentAccount.status === 'ready') {
    return <>{children}</>;
  }

  // 4. Signed in, but the account is not usable: either nothing to provision
  //    from ('absent') or provisioning failed ('error'). Bouncing to /login
  //    would read as "you're not signed in", which is the wrong problem and
  //    invites a sign-in loop that cannot succeed.
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
            <button
              type="button"
              className="btn btn-primary btn-full"
              onClick={refreshStudentAccount}
            >
              Try again
            </button>
          )}

          <button
            type="button"
            className="btn btn-ghost btn-full"
            onClick={() => {
              void signOutSession();
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
