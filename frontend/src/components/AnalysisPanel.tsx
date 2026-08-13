import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { MissingField } from '../types/analysis';
import { useProfileCompletionModal } from './profile/ProfileCompletionContext';

export type AnalysisPhase = 'idle' | 'loading' | 'skipped' | 'failed' | 'success';

/**
 * Where a student goes to fill in what an analysis is missing.
 *
 * A placeholder: the route does not exist yet, and App.tsx's catch-all
 * currently redirects it to /login. Named here as one constant so the surface
 * that claims it later changes this line and nothing else. The missing field's
 * path rides along as a query parameter for that page to focus on if it wants
 * to -- a hint it is free to ignore, deliberately not a route segment, so
 * nothing here constrains the shape that page ends up taking.
 */
export const PROFILE_COMPLETION_PATH = '/profile/complete';

export function profileCompletionHref(path: string): string {
  return `${PROFILE_COMPLETION_PATH}?field=${encodeURIComponent(path)}`;
}

/**
 * The gaps the profile-completion surface cannot close.
 *
 * Skills and work experience are parsed from the résumé and edited on /resume;
 * the completion form deliberately owns neither. Sending these to the modal
 * opened a dialog with no field for the thing that was missing, so they route
 * to the surface that can actually fix them instead.
 */
const RESUME_OWNED_PATHS = new Set(['career.skills_self_reported', 'career.work_experience']);

interface AnalysisPanelProps {
  title: string;
  invitation: string;
  phase: AnalysisPhase;
  onRun(): void;
  missingFields?: MissingField[];
  /**
   * Why the run failed, when it did. Optional and additive: AnalysisPhase and
   * the FeatureStatus contract behind it are untouched, so nothing that keys
   * off 'failed' changes. Absent it, the generic sentence still renders.
   */
  failureMessage?: string;
  children?: ReactNode;
}

// Shared shell for read-only AI-generated result panels (GAP, Professor
// Comment Analyzer). Mirrors EditableSection's card + header-actions layout
// so these read-only panels feel like part of the same system as the
// editable career sections, without offering Edit/Save/Cancel — these are
// AI-generated, not user-editable fields.
export function AnalysisPanel({
  title,
  invitation,
  phase,
  onRun,
  missingFields = [],
  failureMessage,
  children,
}: AnalysisPanelProps) {
  const openProfileCompletion = useProfileCompletionModal();
  return (
    <div className="card analysis-panel">
      <div className="editable-section-header">
        <h3 className="editable-section-title">{title}</h3>
        <div className="editable-section-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onRun}
            disabled={phase === 'loading'}
            aria-busy={phase === 'loading'}
          >
            {phase === 'loading' ? (
              <span className="btn-loading">
                <span className="spinner-small" aria-hidden="true" />
                Analyzing…
              </span>
            ) : phase === 'idle' ? (
              'Run analysis'
            ) : (
              'Re-run analysis'
            )}
          </button>
        </div>
      </div>

      {phase === 'idle' && <p className="analysis-empty">{invitation}</p>}

      {phase === 'loading' && (
        <div className="analysis-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <p>Running this analysis against a live model — this can take a moment.</p>
        </div>
      )}

      {phase === 'skipped' && (
        <div className="analysis-skipped">
          <p>Your profile is missing information this analysis needs:</p>
          <ul className="section-errors">
            {missingFields.map((field) => (
              <li key={field.path} className="section-error-item">
                <span className="missing-field-label">{field.label}</span>
                {RESUME_OWNED_PATHS.has(field.path)
                  ? <Link className="missing-field-link" to="/resume">Review résumé</Link>
                  : openProfileCompletion
                    ? <button className="missing-field-link" type="button" onClick={(event) => openProfileCompletion({ feature: title.match(/\((FIT|GAP|SHIFT)\)/)?.[1] ?? title, missingFields: missingFields.filter((entry) => !RESUME_OWNED_PATHS.has(entry.path)), trigger: event.currentTarget })}>Complete profile</button>
                    : <Link className="missing-field-link" to={profileCompletionHref(field.path)}>Add this</Link>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {phase === 'failed' && (
        <div className="analysis-failed">
          {/* The reason first, in the server's own words, then the generic
              retry line. A rate limit, a busy gate and a genuine AI failure
              used to render the identical sentence, so the screen said nothing
              the browser console had not already said better. */}
          <p>{failureMessage ?? 'Something went wrong generating this analysis.'}</p>
          {failureMessage && <p className="analysis-failed-retry">Try again in a moment.</p>}
        </div>
      )}

      {phase === 'success' && children}
    </div>
  );
}
