import { Navigate } from 'react-router-dom';
import { useAuth } from './useAuth';
import { Spinner, StudentAccountProblem } from './AccountStateScreens';

interface RequireAuthProps {
  children: React.ReactNode;
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
 * The session path renders the same route through its authenticated dashboard
 * boundary. DashboardPage adapts `studentAccount.profile.intelligence_profile`
 * and never substitutes demo data for a real account.
 *
 * ON THE TWO LOADING FLAGS: they can differ, and are not collapsed here.
 * `profileLoading` covers the sessionStorage demo restore; `sessionLoading`
 * covers supabase.auth.getSession(). Both must be settled before the *routing*
 * decision, because until then "no demo profile" and "no session" are both
 * merely unknown, and either would bounce a legitimate user to /login. Once
 * they are settled they are never consulted again: everything after that point
 * is driven by `studentAccount.status`, which is the only signal that tracks
 * provisioning.
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

  // 3. Session plus a confirmed students row -> authenticated dashboard.
  if (studentAccount.status === 'ready') {
    return <>{children}</>;
  }

  // 4. Signed in, but the account is not usable: either nothing to provision
  //    from ('absent') or provisioning failed ('error').
  return (
    <StudentAccountProblem
      studentAccount={studentAccount}
      onRetry={refreshStudentAccount}
      onSignOut={signOutSession}
    />
  );
}
