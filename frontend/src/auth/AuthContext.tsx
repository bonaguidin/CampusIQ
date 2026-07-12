import React, { createContext, useState, useEffect, useCallback } from 'react';
import type { StudentProfile, CareerBlock } from '../types/student';
import { staticJsonAdapter } from '../data/dataAdapter';

// ── Context shape ────────────────────────────────────────────────────────────
// Matches the interface Supabase Auth would use so the adapter can be swapped.

export interface AuthContextValue {
  profile: StudentProfile | null;
  slug: string | null;
  loading: boolean;
  login(slug: string): Promise<void>;
  logout(): void;
  updateCareer(career: CareerBlock): Promise<void>;
  resetCareer(): Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

const SESSION_KEY = 'campus_iq_slug';

// ── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // On mount: restore session from sessionStorage
  useEffect(() => {
    const savedSlug = sessionStorage.getItem(SESSION_KEY);
    if (savedSlug) {
      staticJsonAdapter
        .loadStudent(savedSlug)
        .then((p) => {
          setProfile(p);
          setSlug(savedSlug);
        })
        .catch(() => {
          sessionStorage.removeItem(SESSION_KEY);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (newSlug: string): Promise<void> => {
    setLoading(true);
    try {
      const p = await staticJsonAdapter.loadStudent(newSlug);
      setProfile(p);
      setSlug(newSlug);
      sessionStorage.setItem(SESSION_KEY, newSlug);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback((): void => {
    setProfile(null);
    setSlug(null);
    sessionStorage.removeItem(SESSION_KEY);
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

  const value: AuthContextValue = {
    profile,
    slug,
    loading,
    login,
    logout,
    updateCareer,
    resetCareer,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
