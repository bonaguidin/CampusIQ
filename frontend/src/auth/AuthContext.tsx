import React, { createContext, useState, useEffect, useCallback } from 'react';
import type { Session, User } from '@supabase/supabase-js';
import type { StudentProfile, CareerBlock } from '../types/student';
import { staticJsonAdapter } from '../data/dataAdapter';
import { supabase } from '../lib/supabase';
import {
  applyInstitutionTheme,
  clearInstitutionTheme,
  fetchInstitutionThemeByName,
} from '../lib/institutionTheme';

// ── Context shape ────────────────────────────────────────────────────────────
// Two auth paths coexist for now: the original slug-based demo picker
// (profile/slug/login/logout/updateCareer/resetCareer) and the new
// Supabase session (session/user/signInWithPassword/signOutSession).
// Part 2 will connect a signed-in session to real student data; today
// signing in with a password does not load a profile.

export interface AuthContextValue {
  profile: StudentProfile | null;
  slug: string | null;
  loading: boolean;
  login(slug: string): Promise<void>;
  logout(): void;
  updateCareer(career: CareerBlock): Promise<void>;
  resetCareer(): Promise<void>;
  session: Session | null;
  user: User | null;
  signInWithPassword(email: string, password: string): Promise<void>;
  signOutSession(): Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

const SESSION_KEY = 'campus_iq_slug';

// ── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [profileLoading, setProfileLoading] = useState<boolean>(true);

  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [sessionLoading, setSessionLoading] = useState<boolean>(true);

  // On mount: restore demo session from sessionStorage
  useEffect(() => {
    const savedSlug = sessionStorage.getItem(SESSION_KEY);
    if (savedSlug) {
      staticJsonAdapter
        .loadStudent(savedSlug)
        .then((p) => {
          setProfile(p);
          setSlug(savedSlug);
          // TEMPORARY: name-based lookup, see institutionTheme.ts.
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
      setSession(data.session);
      setUser(data.session?.user ?? null);
      setSessionLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
      setUser(newSession?.user ?? null);
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  const login = useCallback(async (newSlug: string): Promise<void> => {
    setProfileLoading(true);
    try {
      const p = await staticJsonAdapter.loadStudent(newSlug);
      setProfile(p);
      setSlug(newSlug);
      sessionStorage.setItem(SESSION_KEY, newSlug);
      // TEMPORARY: name-based lookup, see institutionTheme.ts.
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
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
  }, []);

  const signOutSession = useCallback(async (): Promise<void> => {
    const { error } = await supabase.auth.signOut();
    clearInstitutionTheme();
    if (error) throw error;
  }, []);

  const value: AuthContextValue = {
    profile,
    slug,
    loading: profileLoading || sessionLoading,
    login,
    logout,
    updateCareer,
    resetCareer,
    session,
    user,
    signInWithPassword,
    signOutSession,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
