import { useId, useState } from 'react';
import type { ProjectEntry } from '../../data/careerViewModel.mjs';

/**
 * One project, summarised rather than dumped.
 *
 * WHAT "SUMMARISED" MEANS HERE, PRECISELY: the preview is the student's own
 * description cut at a word boundary, and "View details" reveals that same
 * description in full, byte for byte. Nothing is regenerated, rewritten or
 * condensed by a model, and no metric, outcome or technology is inferred from
 * the prose. `tools` is shown because projects genuinely carry a structured
 * tools list; a project without one simply shows no tags rather than having
 * some parsed out of its description.
 *
 * Inline expansion rather than a modal or a route: reading a description is not
 * a context switch, and sending someone to another screen to read two more
 * sentences is the same mistake Phase 1 removed from the confirm flows.
 */
export function ProjectCard({ project }: { project: ProjectEntry }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();

  return (
    <article className="cp-project">
      <div className="cp-project-head">
        <h4 className="cp-project-name">{project.name ?? 'Untitled project'}</h4>
        {project.timeframe && <span className="cp-project-when">{project.timeframe}</span>}
      </div>

      {project.description && (
        <p className="cp-project-body" id={bodyId}>
          {open || !project.truncated ? project.description : project.preview}
        </p>
      )}

      {project.tools.length > 0 && (
        <ul className="cp-chips cp-chips--tight">
          {project.tools.map((tool) => (
            <li className="cp-chip cp-chip--quiet" key={tool}>
              {tool}
            </li>
          ))}
        </ul>
      )}

      {/* Only offered when there is genuinely more text to see. A "View
          details" that expands to the same sentence is a lie about depth. */}
      {project.truncated && (
        <button
          type="button"
          className="cp-more"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? 'Hide details' : 'View details'}
        </button>
      )}
    </article>
  );
}
