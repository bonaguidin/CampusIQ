import { Navigate } from 'react-router-dom';
import { useAuth } from './useAuth';
import { Spinner, StudentAccountProblem } from './AccountStateScreens';

interface RequireStudentAccountProps {
  children: React.ReactNode;
}

/**
 * Gates a route on a REAL, Postgres-backed student account -- nothing else.
 *
 * WHY NOT RequireAuth: its first branch is `if (profile) return children`, the
 * demo short-circuit, which admits a demo session before any session logic
 * runs. Demo students exist only as JSON fixtures under data/students/ and have
 * no rows in Postgres by construction, so every /api/v2/student/me/* call they
 * make 404s. Letting one into the resume flow would produce a screen of
 * failures that look like bugs rather than the "this feature isn't for the
 * demo" it actually is.
 *
 * So this gate reads studentAccount.status directly and ignores `profile`
 * entirely. It is deliberately narrower than RequireAuth, not a replacement:
 * /dashboard still uses RequireAuth and still serves the demo path unchanged.
 */
export function RequireStudentAccount({ children }: RequireStudentAccountProps) {
  const { sessionLoading, session, studentAccount, refreshStudentAccount, signOutSession } =
    useAuth();

  // Only the session flag is consulted. profileLoading covers the demo restore,
  // which this route does not depend on -- waiting on it would stall a real
  // student behind work that cannot affect the outcome.
  if (sessionLoading) {
    return <Spinner />;
  }

  if (!session) {
    return <Navigate to="/login" replace />;
  }

  // 'no-session' is the one-render gap before the provisioning effect starts
  // and reads the same as 'checking' here.
  if (studentAccount.status === 'checking' || studentAccount.status === 'no-session') {
    return <Spinner />;
  }

  if (studentAccount.status === 'ready') {
    return <>{children}</>;
  }

  // 'absent' | 'error' -- same screen RequireAuth shows, imported rather than
  // reimplemented.
  return (
    <StudentAccountProblem
      studentAccount={studentAccount}
      onRetry={refreshStudentAccount}
      onSignOut={signOutSession}
    />
  );
}
