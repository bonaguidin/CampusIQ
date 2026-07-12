import { useState } from 'react';
import type { CareerBlock } from '../types/student';
import { useAuth } from '../auth/useAuth';
import { validateCareer } from '../data/validateCareer';
import { EditableSection } from './EditableSection';
import { CareerSummaryRow } from './CareerSummaryRow';
import { TargetRolesEditor } from './TargetRolesEditor';
import { InterestsEditor } from './InterestsEditor';
import { SkillsEditor } from './SkillsEditor';
import { ExperienceList } from './ExperienceList';
import { ProjectsList } from './ProjectsList';
import { CertificationsList } from './CertificationsList';

type SectionKey =
  | 'summary'
  | 'targetRoles'
  | 'interests'
  | 'skills'
  | 'experience'
  | 'projects'
  | 'certifications';

interface CareerPanelProps {
  career: CareerBlock;
}

export function CareerPanel({ career: initialCareer }: CareerPanelProps) {
  const { updateCareer } = useAuth();

  // Local draft copy — mutated per-section before saving
  const [draft, setDraft] = useState<CareerBlock>(() => structuredClone(initialCareer));

  // Which section is currently in edit mode (only one at a time)
  const [editingSection, setEditingSection] = useState<SectionKey | null>(null);
  const [saving, setSaving] = useState(false);
  const [sectionErrors, setSectionErrors] = useState<Partial<Record<SectionKey, string[]>>>({});

  // When career in context changes (e.g. reset), sync local draft
  // We use a ref-based approach: track the initialCareer reference
  const [lastInitial, setLastInitial] = useState<CareerBlock>(initialCareer);
  if (lastInitial !== initialCareer) {
    setLastInitial(initialCareer);
    setDraft(structuredClone(initialCareer));
    setEditingSection(null);
  }

  function startEdit(section: SectionKey) {
    setEditingSection(section);
    setSectionErrors((prev) => ({ ...prev, [section]: [] }));
  }

  function cancelEdit(section: SectionKey) {
    // Revert draft section from the last saved state in context
    setDraft(structuredClone(lastInitial));
    setEditingSection(null);
    setSectionErrors((prev) => ({ ...prev, [section]: [] }));
  }

  async function saveSection(section: SectionKey) {
    const errors = validateCareer(draft);
    if (errors.length > 0) {
      setSectionErrors((prev) => ({ ...prev, [section]: errors }));
      return;
    }
    setSaving(true);
    try {
      await updateCareer(draft);
      setEditingSection(null);
      setSectionErrors((prev) => ({ ...prev, [section]: [] }));
    } catch {
      setSectionErrors((prev) => ({
        ...prev,
        [section]: ['Failed to save. Please try again.'],
      }));
    } finally {
      setSaving(false);
    }
  }

  function sectionProps(key: SectionKey) {
    return {
      isEditing: editingSection === key,
      onEdit: () => startEdit(key),
      onSave: () => { void saveSection(key); },
      onCancel: () => cancelEdit(key),
      saving,
      errors: sectionErrors[key] ?? [],
    };
  }

  return (
    <div className="career-panel">
      <EditableSection title="Overview" {...sectionProps('summary')}>
        <CareerSummaryRow
          career={draft}
          isEditing={editingSection === 'summary'}
          onChange={(updates) => setDraft((prev) => ({ ...prev, ...updates }))}
        />
      </EditableSection>

      <EditableSection title="Target Roles" {...sectionProps('targetRoles')}>
        <TargetRolesEditor
          roles={draft.target_roles}
          isEditing={editingSection === 'targetRoles'}
          onChange={(target_roles) => setDraft((prev) => ({ ...prev, target_roles }))}
        />
      </EditableSection>

      <EditableSection title="Interests" {...sectionProps('interests')}>
        <InterestsEditor
          interests={draft.interests}
          isEditing={editingSection === 'interests'}
          onChange={(interests) => setDraft((prev) => ({ ...prev, interests }))}
        />
      </EditableSection>

      <EditableSection title="Skills" {...sectionProps('skills')}>
        <SkillsEditor
          skills={draft.skills_self_reported}
          isEditing={editingSection === 'skills'}
          onChange={(skills_self_reported) =>
            setDraft((prev) => ({ ...prev, skills_self_reported }))
          }
        />
      </EditableSection>

      <EditableSection title="Work Experience" {...sectionProps('experience')}>
        <ExperienceList
          experiences={draft.work_experience}
          isEditing={editingSection === 'experience'}
          onChange={(work_experience) => setDraft((prev) => ({ ...prev, work_experience }))}
        />
      </EditableSection>

      <EditableSection title="Projects" {...sectionProps('projects')}>
        <ProjectsList
          projects={draft.projects}
          isEditing={editingSection === 'projects'}
          onChange={(projects) => setDraft((prev) => ({ ...prev, projects }))}
        />
      </EditableSection>

      <EditableSection title="Certifications" {...sectionProps('certifications')}>
        <CertificationsList
          certifications={draft.certifications}
          isEditing={editingSection === 'certifications'}
          onChange={(certifications) => setDraft((prev) => ({ ...prev, certifications }))}
        />
      </EditableSection>
    </div>
  );
}
