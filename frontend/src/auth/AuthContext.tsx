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
import {
  resolveStudentAccount,
  resolveStudentAccountOnce,
  NO_SESSION_STATE,
  CHECKING_STATE,
} from '../lib/studentAccount';
import type { StudentAccountState } from '../lib/studentAccount';
import { signupOutcome } from '../lib/signupRules.mjs';
import type { SignupOutcome } from '../lib/signupRules.mjs';

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
  /** Resolves to whether a session was issued, so the caller can branch
   *  between the authenticated flow and the confirm-your-email screen. */
  signUpWithPassword(
    email: string,
    password: string,
    metadata: { name: string; institution_id: string; date_of_birth: string },
  ): Promise<SignupOutcome>;
  signOutSession(): Promise<void>;
  studentAccount: StudentAccountState;
  refreshStudentAccount(): void;
  /**
   * Re-read the canonical profile in place and resolve once it has landed.
   *
   * Distinct from refreshStudentAccount(), which is the RETRY affordance on the
   * account-problem screen: that one drops `studentAccount` to 'checking', and
   * a caller still rendering behind RequireStudentAccount would be unmounted
   * mid-flight by its own refresh. This one leaves the current state in place
   * until the fresh one is ready, so a review screen can await it and only then
   * hand over to the dashboard. Same canonical state, same endpoint -- there is
   * no second profile cache anywhere in this file.
   *
   * Never rejects: a failed read lands as an 'error' StudentAccountState, the
   * same as any other failed resolution.
   */
  reloadStudentProfile(): Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

const SESSION_KEY = 'gradus_iq_slug';

/** A rejected (not merely unsuccessful) profile read, as account state. */
function loadFailureState(err: unknown): StudentAccountState {
  return {
    status: 'error',
    profile: null,
    message:
      err instanceof Error
        ? `Your profile could not be loaded: ${err.message}`
        : 'Your profile could not be loaded.',
  };
}

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
  // and provision one if this is the first session after sign-up. That session
  // arrives either from signUp() itself (confirmation disabled) or from the
  // first login after confirming (confirmation enabled) -- this effect does not
  // distinguish them, which is what lets one provisioning path serve both.
  //
  // Keyed on the user's id (not the Session object) plus an explicit retry
  // counter, so it runs once per signed-in user and again only when something
  // asks it to.
  const userId = user?.id ?? null;
  const demoProfileActive = profile !== null;

  /**
   * The guards that decide whether the students-row question applies to this
   * session at all, and the inputs for asking it.
   *
   * Extracted from the effect below so the in-place reload can reuse exactly
   * the same admission rules. It stays SEPARATE from the resolution call itself
   * because the effect must only announce 'checking' for a resolution that is
   * actually going to run -- folding the guards into the async call would make
   * a declined session flash a spinner.
   */
  const accountResolutionInputs = useCallback((): {
    accessToken: string;
    metadata: unknown;
  } | null => {
    if (!userId) return null;

    // The demo picker owns the dashboard when it is active. Its profile comes
    // from staticJsonAdapter and has no `students` row by construction (the
    // fixtures live in data/students/*.json and were never inserted), so asking
    // Postgres about it would produce a misleading 404 for a session that is
    // working exactly as intended.
    if (demoProfileActive) {
      // Was once a fully silent return: no log, no state change. If a demo
      // profile is somehow active for a real signed-in user, provisioning
      // never runs and nothing anywhere says so.
      console.warn(
        '[AuthContext] account resolution: SKIPPED -- demo profile is active,',
        'so the students-row question is never asked for userId:',
        userId,
        '| trigger:',
        sessionSourceRef.current,
      );
      return null;
    }

    const current = sessionRef.current;
    const accessToken = current?.access_token;
    if (!accessToken) {
      // Also silent once, and it leaves studentAccount at whatever it was.
      // Reachable when the effect runs before sessionRef caught up.
      console.warn(
        '[AuthContext] account resolution: SKIPPED -- userId present but',
        'sessionRef has no access_token yet. userId:',
        userId,
        '| sessionRef:',
        current ? 'present' : 'null',
        '| trigger:',
        sessionSourceRef.current,
      );
      return null;
    }

    return { accessToken, metadata: current.user.user_metadata };
  }, [userId, demoProfileActive]);

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

    const inputs = accountResolutionInputs();
    if (!inputs) return;

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
      inputs.metadata,
    );

    resolveStudentAccountOnce(inputs.accessToken, userId, inputs.metadata)
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
        setStudentAccount(loadFailureState(err));
      });

    return () => {
      active = false;
    };
  }, [userId, accountResolutionInputs, accountRetry]);

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

  // Deliberately resolveStudentAccount, not resolveStudentAccountOnce: the
  // caller is asking because something it just wrote must now be visible, and
  // joining an already-running read would answer with data from before the
  // write. The dedupe map exists to keep StrictMode's double-effect from
  // duplicating the FIRST resolution, which is a different question.
  const reloadStudentProfile = useCallback(async (): Promise<void> => {
    if (!userId) return;
    const inputs = accountResolutionInputs();
    if (!inputs) return;
    try {
      setStudentAccount(await resolveStudentAccount(inputs.accessToken, userId, inputs.metadata));
    } catch (err: unknown) {
      console.error('[AuthContext] reloadStudentProfile REJECTED | error:', err);
      setStudentAccount(loadFailureState(err));
    }
  }, [userId, accountResolutionInputs]);

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

  // Whether signUp() issues a session depends entirely on the project's
  // "Confirm email" setting, which this code does not control and must not
  // assume: with confirmation ON a user comes back with `session: null`, with
  // it OFF the address is confirmed inline and a session is issued right here.
  // This previously hard-assumed the former and returned void, discarding the
  // only field that tells them apart -- so the caller had nothing to branch on
  // and showed "check your email" for a link that was never sent.
  //
  // Returning the outcome rather than the raw response keeps the Supabase
  // response shape from leaking into the page, and keeps the decision itself
  // in signupRules.mjs where it is directly testable.
  //
  // NOTE ON PROVISIONING: nothing is provisioned here on purpose. A session
  // arriving from signUp() reaches onAuthStateChange like any other, which
  // sets `user`, which runs the provisioning effect above -- the exact same
  // path a normal sign-in takes. Adding a second provisioning call in this
  // callback would race that effect for the same student.
  const signUpWithPassword = useCallback(
    async (
      email: string,
      password: string,
      metadata: { name: string; institution_id: string; date_of_birth: string },
    ): Promise<SignupOutcome> => {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { data: metadata },
      });
      if (error) throw error;

      const outcome = signupOutcome(data);
      console.log(
        '[AuthContext] signUp resolved | outcome:',
        outcome,
        '| user:',
        data.user ? 'present' : 'absent',
        '| session:',
        data.session ? 'present' : 'absent',
      );
      return outcome;
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
    reloadStudentProfile,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
