import React, { createContext, useState, useEffect, useCallback, useRef } from 'react';
import type { Session, User } from '@supabase/supabase-js';
import type { StudentProfile, CareerBlock } from '../types/student';
import { staticJsonAdapter } from '../data/dataAdapter';
import { supabase } from '../lib/supabase';
import {
  applyInstitutionTheme,
  clearInstitutionTheme,
  fetchInstitutionThemeById,
  fetchInstitutionThemeByName,
} from '../lib/institutionTheme';
import { resolveStudentAccountOnce, NO_SESSION_STATE, CHECKING_STATE } from '../lib/studentAccount';
import type { StudentAccountState } from '../lib/studentAccount';

// ── Context shape ────────────────────────────────────────────────────────────
// Two auth paths coexist for now: the original slug-based demo picker
// (profile/slug/login/logout/updateCareer/resetCareer) and the new
// Supabase session (session/user/signInWithPassword/signUpWithPassword/
// signOutSession).
//
// The Supabase path now carries a third piece of state, `studentAccount`:
// whether a `students` row actually exists behind the session, and if not
// whether one could be provisioned from the sign-up metadata. A session alone
// was never enough to render the dashboard -- the demo `profile` field cannot
// answer that question, because it is only ever populated by the slug picker.

export interface AuthContextValue {
  profile: StudentProfile | null;
  slug: string | null;
  /** Demo-profile restore OR session restore still outstanding. Kept as-is for
   *  existing callers; the two halves are also exposed separately below,
   *  because a consumer gating the Supabase path must not wait on the demo
   *  path's flag or vice versa. */
  loading: boolean;
  profileLoading: boolean;
  sessionLoading: boolean;
  login(slug: string): Promise<void>;
  logout(): void;
  updateCareer(career: CareerBlock): Promise<void>;
  resetCareer(): Promise<void>;
  session: Session | null;
  user: User | null;
  signInWithPassword(email: string, password: string): Promise<void>;
  signUpWithPassword(
    email: string,
    password: string,
    metadata: { name: string; institution_id: string; date_of_birth: string },
  ): Promise<void>;
  signOutSession(): Promise<void>;
  studentAccount: StudentAccountState;
  refreshStudentAccount(): void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

const SESSION_KEY = 'gradus_iq_slug';

// ── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [profileLoading, setProfileLoading] = useState<boolean>(true);

  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [sessionLoading, setSessionLoading] = useState<boolean>(true);

  const [studentAccount, setStudentAccount] = useState<StudentAccountState>(NO_SESSION_STATE);
  const [accountRetry, setAccountRetry] = useState<number>(0);

  // Read inside the provisioning effect rather than listed as a dependency: the
  // Session object identity changes on every token refresh, and depending on it
  // would re-run provisioning roughly hourly for no reason. The user's id is
  // the thing that actually decides whether the question needs asking again.
  const sessionRef = useRef<Session | null>(null);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  // DIAGNOSTIC ONLY. Records which of the two session sources most recently
  // set `session`, so the provisioning log below can name its trigger. Nothing
  // reads this for control flow -- it is a label, not state.
  const sessionSourceRef = useRef<string>('none');

  // On mount: restore demo session from sessionStorage
  useEffect(() => {
    const savedSlug = sessionStorage.getItem(SESSION_KEY);
    if (savedSlug) {
      staticJsonAdapter
        .loadStudent(savedSlug)
        .then((p) => {
          setProfile(p);
          setSlug(savedSlug);
          // Demo fixtures have no canonical institution foreign key.
          void fetchInstitutionThemeByName(p.student.institution).then(applyInstitutionTheme);
        })
        .catch(() => {
          sessionStorage.removeItem(SESSION_KEY);
        })
        .finally(() => setProfileLoading(false));
    } else {
      setProfileLoading(false);
    }
  }, []);

  // On mount: restore Supabase session and subscribe to auth changes
  useEffect(() => {
    let active = true;

    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      sessionSourceRef.current = 'mount:getSession';
      console.log(
        '[AuthContext] mount getSession resolved | session:',
        data.session ? 'present' : 'absent',
        '| userId:',
        data.session?.user.id ?? null,
      );
      setSession(data.session);
      setUser(data.session?.user ?? null);
      setSessionLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, newSession) => {
      const previousUserId = sessionRef.current?.user.id ?? null;
      const nextUserId = newSession?.user.id ?? null;
      if (previousUserId !== nextUserId) {
        setStudentAccount(newSession ? CHECKING_STATE : NO_SESSION_STATE);
        clearInstitutionTheme();
      }
      sessionRef.current = newSession;
      sessionSourceRef.current = `onAuthStateChange:${_event}`;
      console.log(
        '[AuthContext] onAuthStateChange |',
        _event,
        '| session:',
        newSession ? 'present' : 'absent',
        '| userId:',
        newSession?.user.id ?? null,
      );
      setSession(newSession);
      setUser(newSession?.user ?? null);
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  // On a session becoming non-null: find out whether a `students` row exists,
  // and provision one if this is a first confirmed login after sign-up.
  //
  // Keyed on the user's id (not the Session object) plus an explicit retry
  // counter, so it runs once per signed-in user and again only when something
  // asks it to.
  const userId = user?.id ?? null;
  const demoProfileActive = profile !== null;

  useEffect(() => {
    if (!userId) {
      console.log(
        '[AuthContext] provisioning effect: SKIPPED -- no userId (state reset to no-session).',
        '| trigger:',
        sessionSourceRef.current,
      );
      setStudentAccount(NO_SESSION_STATE);
      return;
    }

    // The demo picker owns the dashboard when it is active. Its profile comes
    // from staticJsonAdapter and has no `students` row by construction (the
    // fixtures live in data/students/*.json and were never inserted), so asking
    // Postgres about it would produce a misleading 404 for a session that is
    // working exactly as intended.
    if (demoProfileActive) {
      // Currently a fully silent return: no log, no state change. If a demo
      // profile is somehow active for a real signed-in user, provisioning
      // never runs and nothing anywhere says so.
      console.warn(
        '[AuthContext] provisioning effect: SKIPPED -- demo profile is active,',
        'so the students-row question is never asked for userId:',
        userId,
        '| trigger:',
        sessionSourceRef.current,
      );
      return;
    }

    const current = sessionRef.current;
    const accessToken = current?.access_token;
    if (!accessToken) {
      // Also fully silent today, and it leaves studentAccount at whatever it
      // was. Reachable when the effect runs before sessionRef caught up.
      console.warn(
        '[AuthContext] provisioning effect: SKIPPED -- userId present but',
        'sessionRef has no access_token yet. userId:',
        userId,
        '| sessionRef:',
        current ? 'present' : 'null',
        '| trigger:',
        sessionSourceRef.current,
      );
      return;
    }

    let active = true;
    setStudentAccount(CHECKING_STATE);

    console.log(
      '[AuthContext] calling resolveStudentAccountOnce | session:',
      sessionRef.current ? 'present' : 'absent',
      '| trigger:',
      sessionSourceRef.current,
      '| retryCount:',
      accountRetry,
      '| userId:',
      userId,
      '| user_metadata:',
      current.user.user_metadata,
    );

    resolveStudentAccountOnce(accessToken, userId, current.user.user_metadata)
      .then((next) => {
        console.log(
          '[AuthContext] resolveStudentAccountOnce resolved | status:',
          next.status,
          '| message:',
          next.message,
          '| applied:',
          active,
        );
        if (active) setStudentAccount(next);
      })
      .catch((err: unknown) => {
        console.error('[AuthContext] resolveStudentAccountOnce REJECTED | error:', err);
        if (!active) return;
        setStudentAccount({
          status: 'error',
          profile: null,
          message:
            err instanceof Error
              ? `Your profile could not be loaded: ${err.message}`
              : 'Your profile could not be loaded.',
        });
      });

    return () => {
      active = false;
    };
  }, [userId, demoProfileActive, accountRetry]);

  useEffect(() => {
    const institutionId = studentAccount.profile?.intelligence_profile.institution.id;
    if (profile || studentAccount.status !== 'ready') return;

    // Clear first so a newly ready account never displays the previous user's
    // colors while its own database-backed theme is loading (or if it has no
    // canonical home institution yet).
    clearInstitutionTheme();
    if (!institutionId) return;

    let active = true;
    void fetchInstitutionThemeById(institutionId).then((theme) => {
      if (active) applyInstitutionTheme(theme);
    });
    return () => {
      active = false;
    };
  }, [profile, studentAccount]);

  const refreshStudentAccount = useCallback((): void => {
    setAccountRetry((n) => n + 1);
  }, []);

  const login = useCallback(async (newSlug: string): Promise<void> => {
    setProfileLoading(true);
    try {
      const p = await staticJsonAdapter.loadStudent(newSlug);
      setProfile(p);
      setSlug(newSlug);
      sessionStorage.setItem(SESSION_KEY, newSlug);
      // Demo fixtures have no canonical institution foreign key.
      const theme = await fetchInstitutionThemeByName(p.student.institution);
      applyInstitutionTheme(theme);
    } finally {
      setProfileLoading(false);
    }
  }, []);

  const logout = useCallback((): void => {
    setProfile(null);
    setSlug(null);
    sessionStorage.removeItem(SESSION_KEY);
    clearInstitutionTheme();
  }, []);

  const updateCareer = useCallback(
    async (career: CareerBlock): Promise<void> => {
      if (!profile) return;
      await staticJsonAdapter.saveCareer(profile.student.id, career);
      setProfile((prev) => (prev ? { ...prev, career } : prev));
    },
    [profile],
  );

  const resetCareer = useCallback(async (): Promise<void> => {
    if (!profile || !slug) return;
    await staticJsonAdapter.resetCareer(profile.student.id);
    // Re-load from raw JSON (no overlay)
    const fresh = await staticJsonAdapter.loadStudent(slug);
    setProfile(fresh);
  }, [profile, slug]);

  const signInWithPassword = useCallback(async (email: string, password: string): Promise<void> => {
    setProfile(null);
    setSlug(null);
    sessionStorage.removeItem(SESSION_KEY);
    clearInstitutionTheme();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
  }, []);

  // Email confirmation is required on this project (mailer_autoconfirm is
  // false, verified live), so signUp() returns no usable session -- callers must
  // show a "check your email" screen, never navigate to the dashboard. The
  // three metadata fields are what the provisioning step later reads back to
  // build the students and student_institutions rows.
  const signUpWithPassword = useCallback(
    async (
      email: string,
      password: string,
      metadata: { name: string; institution_id: string; date_of_birth: string },
    ): Promise<void> => {
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: { data: metadata },
      });
      if (error) throw error;
    },
    [],
  );

  const signOutSession = useCallback(async (): Promise<void> => {
    const { error } = await supabase.auth.signOut();
    clearInstitutionTheme();
    if (error) throw error;
  }, []);

  const value: AuthContextValue = {
    profile,
    slug,
    loading: profileLoading || sessionLoading,
    profileLoading,
    sessionLoading,
    login,
    logout,
    updateCareer,
    resetCareer,
    session,
    user,
    signInWithPassword,
    signUpWithPassword,
    signOutSession,
    studentAccount,
    refreshStudentAccount,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
