import { Link } from 'react-router-dom';
import { buildCareerViewModel } from '../../data/careerViewModel.mjs';
import type { CanonicalCareer } from '../../types/studentIntelligenceProfile';
import type { CertificationEntry, ExperienceEntry } from '../../data/careerViewModel.mjs';
import { ProjectCard } from './ProjectCard';
import { SkillCloud } from './SkillCloud';

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
export function CareerProfile({ career }: { career: CanonicalCareer }) {
  const model = buildCareerViewModel(career);
  const { direction, counts } = model;

  return (
    <div className="cp">
      <CareerSummary model={model} />

      <div className="cp-grid cp-grid--split">
        <Section title="Career direction" count={null}>
          {direction.present ? (
            <div className="cp-direction">
              {direction.targetRoles.length > 0 && (
                <div className="cp-field">
                  <h4 className="cp-subhead">Target roles</h4>
                  <ul className="cp-roles">
                    {direction.targetRoles.map((role) => (
                      <li key={role}>{role}</li>
                    ))}
                  </ul>
                </div>
              )}
              {direction.interests.length > 0 && (
                <div className="cp-field">
                  <h4 className="cp-subhead">Interests</h4>
                  <p className="cp-inline-list">{direction.interests.join(' · ')}</p>
                </div>
              )}
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
          ) : (
            <Absence
              line="No career direction yet."
              // Stated because it is true of this product, not as encouragement:
              // FIT, GAP and SHIFT read target roles directly.
              help="Target roles and interests are what FIT, GAP and SHIFT analyse. Adding them to your resume and confirming it fills this in."
              action
            />
          )}
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
 * career direction because that is the gap with a consequence worth stating
 * (FIT, GAP and SHIFT read target roles), and because it is the first section
 * on the page.
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
