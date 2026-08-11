// Types for signupRules.mjs. The implementation is plain .mjs so the existing
// `node --test tests/*.test.mjs` runner can import it directly; this file is
// what lets TS callers under src/ consume it with full checking.

export declare const AGE_MINIMUM: number;

export interface Institution {
  id: string;
  name: string;
}

export declare const INSTITUTIONS: readonly Institution[];

export interface CalendarDate {
  year: number;
  month: number;
  day: number;
}

export interface SignupFormFields {
  name: string;
  email: string;
  password: string;
  institutionId: string;
  dateOfBirth: string;
}

export interface SignupMetadata {
  name: string;
  institutionId: string;
  dateOfBirth: string;
}

export declare function parseIsoDate(value: unknown): CalendarDate | null;
export declare function todayIso(now?: Date): string;
export declare function ageInYears(dobValue: unknown, todayValue: unknown): number | null;
export declare function isOldEnough(dobValue: unknown, todayValue: unknown): boolean;
export declare function validateSignupForm(
  fields: Partial<SignupFormFields>,
  todayValue: string,
): string | null;
export declare function readSignupMetadata(metadata: unknown): SignupMetadata | null;

/**
 * 'authenticated'          -- signUp() issued a session; the user is signed in.
 * 'confirmation-required'  -- a user exists but no session; email must be
 *                             confirmed before they can sign in.
 */
export type SignupOutcome = 'authenticated' | 'confirmation-required';

export declare function signupOutcome(result: { session?: unknown } | null | undefined): SignupOutcome;
