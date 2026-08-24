import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const NODE = new URL('../src/components/RequirementGroupNode.tsx', import.meta.url);
const OPTIONS = new URL('../src/components/TechnicalElectiveCandidates.tsx', import.meta.url);
const SLOT = new URL('../src/components/TechnicalElectiveSlot.tsx', import.meta.url);
const PANEL = new URL('../src/components/RequirementSatisfactionPanel.tsx', import.meta.url);

test('every requirement group node defers its technical-elective rendering to the shared-fetch slot', async () => {
  const source = await readFile(NODE, 'utf8');
  assert.doesNotMatch(source, /coursedog_rule_id === 'AjzAZTn4'/);
  assert.match(source, /<TechnicalElectiveSlot groupId=\{group\.id\} \/>/);
});

test('the slot renders the full widget only for the primary match, a cross-reference for co-matched groups, and nothing otherwise', async () => {
  const source = await readFile(SLOT, 'utf8');
  assert.match(source, /groupId === result\.requirement_group_id/);
  assert.match(source, /<TechnicalElectiveCandidates result=\{result\} \/>/);
  assert.match(source, /also_satisfies_requirement_groups\.some/);
  assert.match(source, /Same suggestions as \{result\.requirement_name\}/);
  // Loading/error/skipped states render nothing at the node level -- the
  // panel owns those states, not individual nodes.
  assert.match(source, /state\.phase !== 'done'/);
});

test('the technical-electives fetch is lifted to the panel and shared via context, not per-node', async () => {
  const panel = await readFile(PANEL, 'utf8');
  assert.match(panel, /fetchTechnicalElectiveCandidates/);
  assert.match(panel, /TechnicalElectiveContext\.Provider value=\{technicalElectives\.state\}/);
  // One retry control for both fetches, not a second one buried in the tree.
  assert.match(panel, /const refresh = useCallback\(\(\) => \{\s*trigger\(\);\s*technicalElectivesTrigger\(\);/);
  const options = await readFile(OPTIONS, 'utf8');
  assert.doesNotMatch(options, /useAnalysisRun|fetchTechnicalElectiveCandidates/);
});

test('candidate list is explicit, collapsed, bounded, and non-persisting', async () => {
  const source = await readFile(OPTIONS, 'utf8');
  assert.match(source, /useState\(false\)/);
  assert.match(source, /View course options/);
  assert.match(source, /slice\(0, 6\)/);
  assert.match(source, /View all \$\{result\.candidates\.length\} options/);
  assert.match(source, /Adviser approval is required/);
  assert.doesNotMatch(source, /supabase|addPlanned|persist|method:\s*'POST'/i);
});
