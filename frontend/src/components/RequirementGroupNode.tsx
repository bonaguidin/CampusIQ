import { useState } from 'react';
import type { RequirementGroupResult, RequirementGroupStatus } from '../api/requirementSatisfaction';

const STATUS_LABEL: Record<RequirementGroupStatus, string> = {
  SATISFIED: 'Satisfied',
  IN_PROGRESS: 'In progress',
  NOT_STARTED: 'Not started',
  MANUAL_REVIEW: 'Needs review',
};

const STATUS_MODIFIER: Record<RequirementGroupStatus, string> = {
  SATISFIED: 'satisfied',
  IN_PROGRESS: 'in-progress',
  NOT_STARTED: 'not-started',
  MANUAL_REVIEW: 'manual-review',
};

function RequirementStatusBadge({ status }: { status: RequirementGroupStatus }) {
  return (
    <span className={`course-discovery-status-badge course-discovery-status-badge--${STATUS_MODIFIER[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

// Self-referential: a RequirementGroupResult's children are the same shape,
// to whatever depth the program's requirement tree actually has. No
// accordion library -- one collapsible <li> per node, expanded by default so
// the tree reads as a document on first render rather than a stack of
// closed drawers.
export function RequirementGroupNode({ group }: { group: RequirementGroupResult }) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = group.children.length > 0;

  return (
    <li className="requirement-group">
      <div className="requirement-group-header">
        {hasChildren ? (
          <button
            type="button"
            className="requirement-group-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            <span className="requirement-group-toggle-icon" aria-hidden="true">{expanded ? '▾' : '▸'}</span>
            {group.name}
          </button>
        ) : (
          <span className="requirement-group-name">{group.name}</span>
        )}
        <RequirementStatusBadge status={group.status} />
      </div>

      {group.detail && <p className="requirement-group-detail">{group.detail}</p>}

      {group.matched_course_codes.length > 0 && (
        <p className="requirement-group-matched">
          Matched: {group.matched_course_codes.join(', ')}
        </p>
      )}

      {hasChildren && expanded && (
        <ul className="requirement-group-children">
          {group.children.map((child) => (
            <RequirementGroupNode key={child.id} group={child} />
          ))}
        </ul>
      )}
    </li>
  );
}
