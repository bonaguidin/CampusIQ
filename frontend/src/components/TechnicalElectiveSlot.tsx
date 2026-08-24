import { isSkippedTechnicalElectives } from '../api/technicalElectives.mjs';
import { TechnicalElectiveCandidates } from './TechnicalElectiveCandidates';
import { useTechnicalElectiveMatch } from './TechnicalElectiveContext';

/**
 * Per-node decision for one requirement group: does it get the full
 * candidate-pool widget, a short cross-reference to the group that does, or
 * nothing at all.
 *
 * Deliberately renders nothing while the shared fetch is loading, errored,
 * or skipped (no program) -- there is no way to attribute "this node is
 * the primary match" before a successful result exists, so every node
 * simply shows nothing until one does. Retrying the fetch on failure is the
 * requirement panel's own "Refresh degree progress" button, not a per-node
 * control -- see RequirementSatisfactionPanel.
 */
export function TechnicalElectiveSlot({ groupId }: { groupId: string }) {
  const state = useTechnicalElectiveMatch();
  if (!state || state.phase !== 'done' || isSkippedTechnicalElectives(state.result)) return null;

  const result = state.result;
  if (groupId === result.requirement_group_id) {
    return <TechnicalElectiveCandidates result={result} />;
  }

  const alsoSatisfies = result.also_satisfies_requirement_groups.some(
    (group) => group.requirement_group_id === groupId,
  );
  if (!alsoSatisfies) return null;

  return (
    <p className="requirement-group-adviser-note technical-elective-cross-reference">
      Same suggestions as {result.requirement_name}.
    </p>
  );
}
