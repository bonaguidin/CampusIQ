// Shared test-only harness for the resume and transcript flow previews.
//
// WHY IT EXISTS NOW. Both flows used to be mountable bare: a terminal success
// screen with a plain <a href> needed no router and no auth context, which is
// most of why GoToDashboard was a plain anchor. Confirmation now navigates to
// the dashboard and re-reads the canonical profile first, so a preview that
// cannot route and has no account state can no longer exercise the ending at
// all -- and the ending is the part under test.
//
// WHAT IS REAL HERE AND WHAT IS NOT. The account state is resolved by the
// PRODUCTION lib/studentAccount.ts against the preview server's own
// /api/v2/student/me/profile, and the dashboard rendered at /dashboard is the
// production AuthenticatedDashboard. So "the profile was refetched" and "the
// new data is on screen" are properties of the real code, not of this file.
// Only the Supabase session and the demo-picker half of AuthContextValue are
// stubbed, because neither participates in this flow.
//
// WHY HashRouter. The preview entry points are real files
// (/transcript-preview.html), so a BrowserRouter would navigate to a URL the
// dev server cannot serve on reload. Hash routing keeps every reload on the
// same document while still storing history state the way BrowserRouter does --
// which is exactly what makes "the success notice must not survive a refresh"
// testable rather than vacuous.

import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { HashRouter, Route, Routes } from 'react-router-dom';
import type { Session } from '@supabase/supabase-js';
import { AuthContext } from './auth/AuthContext';
import type { AuthContextValue } from './auth/AuthContext';
import { AuthenticatedDashboard } from './pages/AuthenticatedDashboard';
import { resolveStudentAccount, CHECKING_STATE } from './lib/studentAccount';
import type { StudentAccountState } from './lib/studentAccount';

export const PREVIEW_TOKEN = 'preview-session-token';
const PREVIEW_USER_ID = 'preview-user';
const PREVIEW_METADATA = {
  name: 'Preview Student',
  institution_id: '75d68331-91d2-47e8-9671-2a3b065955d0',
  date_of_birth: '2004-01-01',
};

export function PreviewFlowHarness({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<StudentAccountState>(CHECKING_STATE);

  const reloadStudentProfile = useCallback(async (): Promise<void> => {
    setAccount(await resolveStudentAccount(PREVIEW_TOKEN, PREVIEW_USER_ID, PREVIEW_METADATA));
  }, []);

  useEffect(() => {
    void reloadStudentProfile();
  }, [reloadStudentProfile]);

  const value = {
    profile: null,
    slug: null,
    loading: false,
    profileLoading: false,
    sessionLoading: false,
    login: async () => undefined,
    logout: () => undefined,
    updateCareer: async () => undefined,
    resetCareer: async () => undefined,
    session: { access_token: PREVIEW_TOKEN } as Session,
    user: null,
    signInWithPassword: async () => undefined,
    signUpWithPassword: async () => 'authenticated',
    signOutSession: async () => undefined,
    studentAccount: account,
    refreshStudentAccount: () => {
      void reloadStudentProfile();
    },
    reloadStudentProfile,
  } as AuthContextValue;

  return (
    <AuthContext.Provider value={value}>
      <HashRouter>
        <Routes>
          <Route path="/" element={children} />
          <Route path="/dashboard" element={<AuthenticatedDashboard />} />
        </Routes>
      </HashRouter>
    </AuthContext.Provider>
  );
}
