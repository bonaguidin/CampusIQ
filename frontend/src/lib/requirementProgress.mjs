/**
 * Counts leaf requirement groups (nodes with no children -- the actual
 * atomic requirements, e.g. a specific course slot) as satisfied vs. total,
 * for the Overview page's degree-progress ring. Compound parent nodes
 * (group_type compound_all/compound_any) are containers, not requirements in
 * their own right, so they are walked into but never counted themselves.
 */
export function countSatisfiedLeafGroups(groups) {
  let satisfied = 0
  let total = 0

  function walk(group) {
    const children = Array.isArray(group.children) ? group.children : []
    if (children.length === 0) {
      total += 1
      if (group.status === 'SATISFIED') satisfied += 1
      return
    }
    for (const child of children) walk(child)
  }

  for (const group of Array.isArray(groups) ? groups : []) walk(group)

  return { satisfied, total }
}
