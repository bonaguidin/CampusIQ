// To swap to Supabase: implement DataAdapter with supabase.from('students')
// reads and a career PATCH; swap staticJsonAdapter for the new impl in AuthContext

import type { StudentProfile, CareerBlock } from '../types/student';

export function emptyCareerBlock(): CareerBlock {
  return {
    target_roles: [],
    interests: [],
    career_goals: '',
    geographic_preference: '',
    ai_anxiety_level: '',
    skills_self_reported: { technical: [], soft: [], ai_exposure: '' },
    certifications: [],
    work_experience: [],
    projects: [],
  };
}

// ── Adapter interface ────────────────────────────────────────────────────────

export interface DataAdapter {
  loadStudent(slug: string): Promise<StudentProfile>;
  saveCareer(studentId: number, career: CareerBlock): Promise<void>;
  resetCareer(studentId: number): Promise<void>;
}

// ── localStorage key helper ──────────────────────────────────────────────────

function careerKey(studentId: number): string {
  return `campus_iq_career_${studentId}`;
}

// ── Static JSON + localStorage overlay implementation ────────────────────────

export const staticJsonAdapter: DataAdapter = {
  async loadStudent(slug: string): Promise<StudentProfile> {
    const response = await fetch(`/data/student_${slug}.json`);
    if (!response.ok) {
      throw new Error(`Failed to load student profile for slug "${slug}": ${response.status}`);
    }
    const data = (await response.json()) as StudentProfile;

    if (data.career === null) {
      data.career = emptyCareerBlock();
    }

    // Apply localStorage overlay for career edits
    const stored = localStorage.getItem(careerKey(data.student.id));
    if (stored) {
      try {
        const career = JSON.parse(stored) as CareerBlock;
        return { ...data, career };
      } catch {
        // Corrupt localStorage data — ignore overlay and return raw
        localStorage.removeItem(careerKey(data.student.id));
      }
    }

    return data;
  },

  async saveCareer(studentId: number, career: CareerBlock): Promise<void> {
    localStorage.setItem(careerKey(studentId), JSON.stringify(career));
  },

  async resetCareer(studentId: number): Promise<void> {
    localStorage.removeItem(careerKey(studentId));
  },
};
