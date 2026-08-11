import { useId, useState } from 'react';
import { SKILL_PREVIEW_COUNT } from '../../data/careerViewModel.mjs';
import type { SkillGroup } from '../../data/careerViewModel.mjs';

/**
 * Skills, as chips instead of a comma wall.
 *
 * THE CHIPS ARE NOT BUTTONS. Nothing happens when you click a skill, so they
 * are plain `<li>`s in a list -- giving them button semantics would promise an
 * interaction that does not exist and would put every one of them in the tab
 * order for no reason. Only the expander is interactive, and it is a real
 * button with real `aria-expanded`.
 *
 * ON THE COLLAPSE. A confirmed resume can carry dozens of skills, and the point
 * of the redesign is scanability -- 40 chips is a wall too, just a prettier
 * one. The overflow is hidden behind a count, never dropped: the expander is
 * always present when anything is collapsed, so no skill is unreachable.
 */
export function SkillCloud({ groups, total }: { groups: SkillGroup[]; total: number }) {
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const collapsible = total > SKILL_PREVIEW_COUNT;

  // Every non-empty group keeps at least one chip while collapsed, and the rest
  // of the budget is spent in canonical order. Without the reserved seat a long
  // technical list eats the whole allowance and the "Soft skills" heading
  // vanishes until you expand -- so the section would appear to gain a category
  // on click, which reads as the page changing its mind about the data.
  const budgetTotal = expanded || !collapsible ? total : SKILL_PREVIEW_COUNT;
  let spare = Math.max(0, budgetTotal - groups.length);
  const shown = groups.map((group) => {
    const extra = Math.min(Math.max(group.skills.length - 1, 0), spare);
    spare -= extra;
    return { ...group, visible: group.skills.slice(0, 1 + extra) };
  });
  const hidden = total - shown.reduce((sum, group) => sum + group.visible.length, 0);

  return (
    <div className="cp-skills" id={listId}>
      {shown.map((group) =>
        group.visible.length === 0 ? null : (
          <div className="cp-skill-group" key={group.key}>
            <h4 className="cp-subhead">{group.label}</h4>
            <ul className="cp-chips">
              {group.visible.map((skill) => (
                <li className="cp-chip" key={skill}>
                  {skill}
                </li>
              ))}
            </ul>
          </div>
        ),
      )}

      {collapsible && (
        <button
          type="button"
          className="cp-more"
          aria-expanded={expanded}
          aria-controls={listId}
          onClick={() => setExpanded((open) => !open)}
        >
          {/* "Show all 24 skills +6" stated the same fact twice. The hidden
              count is the only number the student needs to decide whether to
              click, and it is derived from the list rather than written down. */}
          {expanded ? 'Show less' : `Show ${String(hidden)} more`}
        </button>
      )}
    </div>
  );
}
