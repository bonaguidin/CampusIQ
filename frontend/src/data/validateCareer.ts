// Validation rules ported from data/students/validate_students.py (career block only).
// Returns an array of error message strings. Empty array = valid.

import type { CareerBlock } from '../types/student';

function isNonEmptyString(value: unknown): boolean {
  return typeof value === 'string' && value.trim().length > 0;
}

function validateStringList(
  value: unknown,
  fieldName: string,
  errors: string[],
  allowEmpty = false,
): void {
  if (!Array.isArray(value)) {
    errors.push(`${fieldName}: expected list`);
    return;
  }
  if (!allowEmpty && value.length === 0) {
    errors.push(`${fieldName}: expected non-empty list`);
    return;
  }
  const badItems = value.filter((item) => !isNonEmptyString(item));
  if (badItems.length > 0) {
    errors.push(`${fieldName}: all items must be non-empty strings`);
  }
}

export function validateCareer(career: CareerBlock): string[] {
  const errors: string[] = [];

  // target_roles
  if (!Array.isArray(career.target_roles) || career.target_roles.length === 0) {
    errors.push('target_roles: must have at least one role');
  } else {
    const bad = career.target_roles.filter((r) => !isNonEmptyString(r));
    if (bad.length > 0) {
      errors.push('target_roles: must have at least one role');
    }
  }

  // interests
  if (!Array.isArray(career.interests) || career.interests.length === 0) {
    errors.push('interests: must have at least one interest');
  } else {
    const bad = career.interests.filter((r) => !isNonEmptyString(r));
    if (bad.length > 0) {
      errors.push('interests: must have at least one interest');
    }
  }

  // scalar string fields
  if (!isNonEmptyString(career.career_goals)) {
    errors.push('career_goals: required');
  }
  if (!isNonEmptyString(career.geographic_preference)) {
    errors.push('geographic_preference: required');
  }
  if (!isNonEmptyString(career.ai_anxiety_level)) {
    errors.push('ai_anxiety_level: required');
  }

  // skills_self_reported
  const skills = career.skills_self_reported;
  if (!skills || typeof skills !== 'object') {
    errors.push('skills_self_reported: required');
  } else {
    validateStringList(skills.technical, 'technical skills', errors);
    if (errors[errors.length - 1] === 'technical skills: expected non-empty list') {
      errors[errors.length - 1] = 'technical skills: at least one required';
    }
    validateStringList(skills.soft, 'soft skills', errors);
    if (errors[errors.length - 1] === 'soft skills: expected non-empty list') {
      errors[errors.length - 1] = 'soft skills: at least one required';
    }
    if (!isNonEmptyString(skills.ai_exposure)) {
      errors.push('ai_exposure: required');
    }
  }

  // work_experience
  if (!Array.isArray(career.work_experience) || career.work_experience.length === 0) {
    errors.push('work_experience: at least one entry required');
  } else {
    career.work_experience.forEach((exp, idx) => {
      const prefix = `work_experience[${idx}]`;
      if (!isNonEmptyString(exp.employer)) errors.push(`${prefix}: employer required`);
      if (!isNonEmptyString(exp.role)) errors.push(`${prefix}: role required`);
      if (!isNonEmptyString(exp.duration)) errors.push(`${prefix}: duration required`);
      if (!isNonEmptyString(exp.location)) errors.push(`${prefix}: location required`);
      if (!isNonEmptyString(exp.description)) errors.push(`${prefix}: description required`);
      if (!Array.isArray(exp.skills_gained) || exp.skills_gained.length === 0) {
        errors.push(`${prefix}: skills_gained required`);
      }
    });
  }

  // projects
  if (!Array.isArray(career.projects) || career.projects.length === 0) {
    errors.push('projects: at least one entry required');
  } else {
    career.projects.forEach((proj, idx) => {
      const prefix = `projects[${idx}]`;
      if (!isNonEmptyString(proj.name)) errors.push(`${prefix}: name required`);
      if (!isNonEmptyString(proj.timeframe)) errors.push(`${prefix}: timeframe required`);
      if (!isNonEmptyString(proj.description)) errors.push(`${prefix}: description required`);
      if (!Array.isArray(proj.tools) || proj.tools.length === 0) {
        errors.push(`${prefix}: tools required`);
      }
    });
  }

  // certifications — may be empty; if not empty each entry needs name, issuer, status
  if (Array.isArray(career.certifications) && career.certifications.length > 0) {
    career.certifications.forEach((cert, idx) => {
      const prefix = `certifications[${idx}]`;
      if (!isNonEmptyString(cert.name)) errors.push(`${prefix}: name required`);
      if (!isNonEmptyString(cert.issuer)) errors.push(`${prefix}: issuer required`);
      if (!isNonEmptyString(cert.status)) errors.push(`${prefix}: status required`);
    });
  }

  return errors;
}
