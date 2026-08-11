// Types for careerViewModel.mjs. The implementation is plain .mjs so the
// existing `node --test tests/` runner can import it directly; this file is
// what lets TS callers under src/ consume it with full checking.

import type { CanonicalCareer, CanonicalCareerItem } from '../types/studentIntelligenceProfile';

export declare const DESCRIPTION_PREVIEW_LIMIT: number;
export declare const SKILL_PREVIEW_COUNT: number;

export interface SkillGroup {
  key: 'technical' | 'soft';
  label: string;
  skills: string[];
}

export interface ExperienceEntry {
  key: string;
  employer: string | null;
  role: string | null;
  duration: string | null;
  location: string | null;
  description: string | null;
  preview: string | null;
  truncated: boolean;
  skills: string[];
}

export interface ProjectEntry {
  key: string;
  name: string | null;
  timeframe: string | null;
  description: string | null;
  preview: string | null;
  truncated: boolean;
  tools: string[];
}

export interface CertificationEntry {
  key: string;
  name: string | null;
  issuer: string | null;
  date: string | null;
  status: string | null;
  statusLabel: string | null;
}

export interface CareerDirection {
  targetRoles: string[];
  interests: string[];
  goals: string | null;
  location: string | null;
  present: boolean;
}

export interface CareerCounts {
  skills: number;
  experience: number;
  projects: number;
  certifications: number;
}

export interface CareerViewModel {
  confirmed: boolean;
  direction: CareerDirection;
  skillGroups: SkillGroup[];
  experience: ExperienceEntry[];
  projects: ProjectEntry[];
  certifications: CertificationEntry[];
  counts: CareerCounts;
  empty: boolean;
}

export declare function text(item: CanonicalCareerItem | null | undefined, key: string): string | null;
export declare function list(item: CanonicalCareerItem | null | undefined, key: string): string[];
export declare function previewOf(
  body: unknown,
  limit?: number,
): { preview: string | null; truncated: boolean };
export declare function skillGroups(career: CanonicalCareer): SkillGroup[];
export declare function experienceEntries(career: CanonicalCareer): ExperienceEntry[];
export declare function projectEntries(career: CanonicalCareer): ProjectEntry[];
export declare function certificationEntries(career: CanonicalCareer): CertificationEntry[];
export declare function careerDirection(career: CanonicalCareer): CareerDirection;
export declare function buildCareerViewModel(career: CanonicalCareer): CareerViewModel;
