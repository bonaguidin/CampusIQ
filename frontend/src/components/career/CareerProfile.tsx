import { Link } from 'react-router-dom';
import { buildCareerViewModel } from '../../data/careerViewModel.mjs';
import { isNoIntendedMajor } from '../../lib/majorSentinel';
import type { CanonicalCareer } from '../../types/studentIntelligenceProfile';
import type { CertificationEntry, ExperienceEntry } from '../../data/careerViewModel.mjs';
import { ProjectCard } from './ProjectCard';
import { SkillCloud } from './SkillCloud';

/**
 * The identity facts the Career tab reports but does not own.
 *
 * Expected graduation and the majors live on `identity` and
 * `academics.summary`, not on `career` -- they are academic record, and this
 * component is not going to reach across the profile to find them. The
 * dashboard already holds all three (see dashboardViewModel) and hands them
 * down, so this stays a props-in component and no new fetch exists anywhere.
 */
export interface CareerDetails {
  expectedGraduation: string | null;
  majorCurrent: string | null;
  majorIntended: string | null;
}

/**
 * The authenticated Career profile.
 *
 * WHAT THIS REPLACED AND WHY. Five equal cards in a rigid two-column grid, each
 * a fixed-height rectangle regardless of what it held: skills as one
 * comma-separated paragraph, experience as employer/role database rows,
 * projects as whole résumé descriptions pasted in, and three sibling sentences
 * ("No career goal provided." / "No target roles provided." / "No interests
 * provided.") occupying a full card to say nothing was there. The layout gave
 * a 300-word project and an empty certifications list identical space.
 *
 * The hierarchy now follows information weight rather than the grid: a compact
 * summary strip, then direction beside skills (direction is short, skills are
 * long, so they are not the same width), then experience beside certifications,
 * then projects across the full measure because they hold the most text.
 *
 * EMPTY SECTIONS COLLAPSE TO A LINE. An absence is worth one sentence, not a
 * rectangle -- and where there is a real way to fix the absence, it links to
 * /resume, which is the only career-editing path an authenticated student
 * actually has. The demo profile's inline editors (CareerPanel) are not
 * reachable from here, so no button pretends otherwise.
 */
export function CareerProfile({
  career,
  details,
}: {
  career: CanonicalCareer;
  details: CareerDetails;
}) {
  const model = buildCareerViewModel(career);
  const { direction, counts } = model;

  return (
    <div className="cp">
      <CareerSummary model={model} />

      <DetailsSection details={details} aiComfort={career.ai_anxiety_level} />

      <div className="cp-grid cp-grid--split">
        {/* Each field below answers for itself. The section used to be gated on
            one boolean covering all four, which meant a student with interests
            and no target roles saw the interests and heard nothing at all about
            the roles -- the field every analysis requires. */}
        <Section title="Career direction" count={null}>
          <div className="cp-direction">
            <div className="cp-field">
              <h4 className="cp-subhead">Target roles</h4>
              {direction.hasTargetRoles ? (
                <ul className="cp-roles">
                  {direction.targetRoles.map((role) => (
                    <li key={role}>{role}</li>
                  ))}
                </ul>
              ) : (
                <Absence
                  line="No target roles added yet."
                  // Stated because it is true of this product, not as
                  // encouragement: FIT, GAP and SHIFT read target roles
                  // directly. This is where the page's single /resume route
                  // now lives -- see Absence.
                  help="FIT, GAP and SHIFT all read your target roles. Adding them to your resume and confirming it fills this in."
                  action
                />
              )}
            </div>
            <div className="cp-field">
              <h4 className="cp-subhead">Interests</h4>
              {direction.hasInterests ? (
                <p className="cp-inline-list">{direction.interests.join(' · ')}</p>
              ) : (
                <Absence line="No interests added yet." />
              )}
            </div>
            {/* Goals and location keep the treatment they had: present or
                silent. Neither is required by any analysis, so neither earns
                an absence line arguing for itself. */}
            {direction.goals && (
              <div className="cp-field">
                <h4 className="cp-subhead">Goal</h4>
                <p className="cp-prose">{direction.goals}</p>
              </div>
            )}
            {direction.location && (
              <div className="cp-field">
                <h4 className="cp-subhead">Location preference</h4>
                <p className="cp-prose">{direction.location}</p>
              </div>
            )}
          </div>
        </Section>

        <Section title="Skills" count={counts.skills}>
          {counts.skills > 0 ? (
            <SkillCloud groups={model.skillGroups} total={counts.skills} />
          ) : (
            <Absence line="No skills confirmed yet." />
          )}
        </Section>
      </div>

      <div className="cp-grid cp-grid--split cp-grid--reverse">
        <Section title="Experience" count={counts.experience}>
          {counts.experience > 0 ? (
            <ol className="cp-timeline">
              {model.experience.map((entry) => (
                <ExperienceRow entry={entry} key={entry.key} />
              ))}
            </ol>
          ) : (
            <Absence line="No experience confirmed yet." />
          )}
        </Section>

        <Section title="Certifications" count={counts.certifications}>
          {counts.certifications > 0 ? (
            <ul className="cp-certs">
              {model.certifications.map((entry) => (
                <CertificationRow entry={entry} key={entry.key} />
              ))}
            </ul>
          ) : (
            <Absence line="No certifications yet." />
          )}
        </Section>
      </div>

      <Section title="Projects" count={counts.projects}>
        {counts.projects > 0 ? (
          <div className="cp-projects">
            {model.projects.map((project) => (
              <ProjectCard project={project} key={project.key} />
            ))}
          </div>
        ) : (
          <Absence line="No projects yet." />
        )}
      </Section>
    </div>
  );
}

/**
 * The orientation strip.
 *
 * Every number is `array.length` and every word is a canonical string. There is
 * no readiness score, no percentage and no ranking here, because the profile
 * contains none -- the closest thing it has is the boolean
 * `completeness.career.*` family, and a count the student can verify by
 * scrolling is more honest than a figure only we can compute.
 *
 * The student's name is deliberately absent: the dashboard rail and the
 * overview header already establish whose profile this is.
 */
function CareerSummary({ model }: { model: ReturnType<typeof buildCareerViewModel> }) {
  const { direction, counts } = model;
  const headline = direction.targetRoles.length > 0 ? direction.targetRoles.join(' · ') : null;

  return (
    <header className="cp-summary">
      {/* No "Career" eyebrow here: the topbar and the section's own <h2>
          already say it twice, and a third would be noise rather than
          orientation. */}
      <div className="cp-summary-lead">
        {headline ? (
          <p className="cp-summary-roles">{headline}</p>
        ) : (
          <p className="cp-summary-roles cp-summary-roles--absent">No target roles yet</p>
        )}
      </div>

      <dl className="cp-metrics">
        {[
          { label: counts.skills === 1 ? 'Skill' : 'Skills', value: counts.skills },
          { label: counts.experience === 1 ? 'Experience' : 'Experiences', value: counts.experience },
          { label: counts.projects === 1 ? 'Project' : 'Projects', value: counts.projects },
          {
            label: counts.certifications === 1 ? 'Certification' : 'Certifications',
            value: counts.certifications,
          },
        ].map(({ label, value }) => (
          <div className="cp-metric" key={label}>
            <dt className="cp-metric-label">{label}</dt>
            <dd className="cp-metric-value">{value}</dd>
          </div>
        ))}
      </dl>
    </header>
  );
}

/**
 * How the four stored AI-comfort values read on screen.
 *
 * Mirrors AI_OPTIONS in ProfileCompletionForm, which is where a student picks
 * one. The raw column values are machine tokens -- 'not_sure' rendered
 * verbatim is not English -- so they are labelled here, and an unrecognised
 * value passes through untouched rather than being swallowed, the same way
 * certificationEntries handles an unexpected status.
 */
const AI_COMFORT_LABELS: Record<string, string> = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  not_sure: 'Not sure',
};

/**
 * The facts guidance is calibrated against, stated plainly.
 *
 * READ-ONLY, DELIBERATELY. These three rows exist because nothing in the
 * authenticated app rendered them at all: a student could be told an analysis
 * needed their expected graduation while the page never showed what it had.
 * Editing arrives in a later step; nothing here is clickable, so no control
 * implies an ability the page does not yet have.
 *
 * A missing value is "Not set" rather than an em dash. The dash is what the
 * demo's CareerSummaryRow uses, and it reads as a layout filler -- these rows
 * are about to become the checklist's targets, so an absence has to say it is
 * an absence.
 */
function DetailsSection({
  details,
  aiComfort,
}: {
  details: CareerDetails;
  aiComfort: string | null;
}) {
  const { expectedGraduation, majorCurrent, majorIntended } = details;
  // The sentinel is a stored answer ("not switching"), never a major anyone
  // typed, so it must not be printed back as though it were one.
  const switching = !isNoIntendedMajor(majorIntended);
  const comfort = aiComfort ? AI_COMFORT_LABELS[aiComfort] ?? aiComfort : null;

  return (
    <Section title="Details" count={null}>
      <dl className="cp-details">
        <Detail label="Expected graduation" value={expectedGraduation} />
        <Detail
          label="Major"
          value={majorCurrent}
          // Only a switching student has a second major to report. "Not
          // switching" is a real answer and says so; it is not an absence.
          note={switching ? `Switching to ${majorIntended ?? ''}`.trim() : 'Not switching majors'}
        />
        <Detail
          label="AI comfort"
          value={comfort}
          // Null means never asked, which is a different state from 'not_sure'
          // (asked, does not know) -- see the 20260812143000 migration.
          absentLabel="Not answered"
        />
      </dl>
    </Section>
  );
}

/** One labelled fact, or an explicit absence in its place. */
function Detail({
  label,
  value,
  note,
  absentLabel = 'Not set',
}: {
  label: string;
  value: string | null;
  note?: string;
  absentLabel?: string;
}) {
  return (
    <div className="cp-detail">
      <dt className="cp-detail-label">{label}</dt>
      <dd className="cp-detail-value-group">
        {value ? (
          <span className="cp-detail-value">{value}</span>
        ) : (
          <span className="cp-detail-value cp-detail-value--absent">{absentLabel}</span>
        )}
        {/* The note qualifies a value that exists; with nothing to qualify it
            would be a sentence floating beside "Not set". */}
        {value && note && <span className="cp-detail-note">{note}</span>}
      </dd>
    </div>
  );
}

/** A section shell: eyebrow, optional count, and a rule. */
function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number | null;
  children: React.ReactNode;
}) {
  return (
    <section className="cp-section">
      <div className="cp-section-head">
        <h3 className="cp-section-title">{title}</h3>
        {count !== null && count > 0 && <span className="cp-section-count">{count}</span>}
      </div>
      {children}
    </section>
  );
}

/**
 * A missing section, in one line.
 *
 * The old page spent a full card on three negative sentences. This is the whole
 * treatment: state the absence, and optionally say what filling it would do.
 *
 * THE LINK APPEARS ONCE PER PAGE, not once per gap. Confirming a resume rewrites
 * every career section at the same time, so a route repeated beside all five
 * absences would offer the same single action five times -- which reads as
 * nagging and makes an empty profile look busier than a full one. It sits on
 * target roles because that is the gap with a consequence worth stating (FIT,
 * GAP and SHIFT all require it), and because it is the first field on the page
 * that can be absent. Splitting Career direction into per-field absences moved
 * it one level down from the section to that field; it did not add a second.
 */
function Absence({ line, help, action = false }: { line: string; help?: string; action?: boolean }) {
  return (
    <div className="cp-absent">
      <p className="cp-absent-line">{line}</p>
      {help && <p className="cp-absent-help">{help}</p>}
      {action && (
        <Link to="/resume" className="cp-absent-link">
          Update from your resume
        </Link>
      )}
    </div>
  );
}

/**
 * One role on the timeline.
 *
 * Employer is the marker and the anchor; role sits under it; duration and
 * location are secondary and appear ONLY when the record has them. Nothing is
 * substituted for a missing date -- an invented "Present" or "Dates unknown"
 * would be a claim about someone's employment history.
 */
function ExperienceRow({ entry }: { entry: ExperienceEntry }) {
  const meta = [entry.duration, entry.location].filter(Boolean);

  return (
    <li className="cp-tl-item">
      <span className="cp-tl-marker" aria-hidden="true" />
      <div className="cp-tl-body">
        <h4 className="cp-tl-org">{entry.employer ?? entry.role ?? 'Experience'}</h4>
        {entry.employer && entry.role && <p className="cp-tl-role">{entry.role}</p>}
        {meta.length > 0 && <p className="cp-tl-meta">{meta.join(' · ')}</p>}
        {entry.preview && <p className="cp-tl-desc">{entry.preview}</p>}
        {entry.skills.length > 0 && (
          <ul className="cp-chips cp-chips--tight">
            {entry.skills.map((skill) => (
              <li className="cp-chip cp-chip--quiet" key={skill}>
                {skill}
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

/** One credential. Status is a real constrained column, not an inference. */
function CertificationRow({ entry }: { entry: CertificationEntry }) {
  const meta = [entry.issuer, entry.date].filter(Boolean);

  return (
    <li className="cp-cert">
      <h4 className="cp-cert-name">{entry.name ?? 'Untitled certification'}</h4>
      {meta.length > 0 && <p className="cp-cert-meta">{meta.join(' · ')}</p>}
      {entry.statusLabel && (
        <span
          className={`cp-cert-status${entry.status === 'completed' ? ' cp-cert-status--done' : ''}`}
        >
          {entry.statusLabel}
        </span>
      )}
    </li>
  );
}
