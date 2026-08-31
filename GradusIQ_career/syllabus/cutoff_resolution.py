"""Pure "higher grade wins the tie" resolution for overlapping letter-grade cutoffs.

    list[GradeThreshold] -> resolve_cutoff_overlaps() -> CutoffOverlapResolution

Phase 5 (reconciliation.py:_check_grade_thresholds) *detects* overlapping
grade thresholds and emits an ERROR finding per overlapping pair. It never
resolves them. This module proposes a resolution for the one overlap shape
that has an unambiguous answer:

    two canonical A-F letters, rank-adjacent, whose ranges share exactly
    one boundary point -> the boundary score belongs to the HIGHER letter
    grade (90 is an A not a B; 80 is a B not a C).

That is the decision recorded in the syllabus-review redesign spec
(planning-docs/syllabus-review-redesign-spec.md §2A / §5): propose the
higher-grade-wins default, let the student confirm or override. This
function only produces the proposal -- it does not mutate the GradeModel,
does not apply corrections, and is not wired into the API. It is
deliberately callable independent of any question-flow UI so it can be
unit-tested against constructed threshold cases.

WHAT IS NOT RESOLVED (returned in `unresolved`, never guessed at)
----------------------------------------------------------------
- non-canonical letters (S/U, custom labels, numeric)
- letters that are not rank-adjacent (an A vs C overlap)
- an overlap that spans more than a single point (a genuine range conflict)
- any pair that involves a single-bound threshold ("A: 90+", "F: below 60")
- "multi-way" overlaps: three or more thresholds in one connected overlap
  component -- naive per-pair tie-breaking there could compound, so the
  whole component is punted. (A fully inclusive-lower A/B/C/D/F scale where
  every adjacent pair shares its boundary is one such component and is
  reported entirely unresolved.)

No LLM, no network, no I/O -- pure deterministic Python.
"""

from __future__ import annotations

from pydantic import Field

from GradusIQ_career.syllabus.models import GradeThreshold, StrictModel
from GradusIQ_career.syllabus.reconciliation import CANONICAL_LETTER_RANK

CUTOFF_RESOLUTION_SCHEMA_VERSION = "1"


class ResolvedCutoffOverlap(StrictModel):
    """One overlapping cutoff pair resolved by "higher grade wins the tie"."""

    letters: tuple[str, str] = Field(description="(winner, loser) -- higher grade first")
    boundary: float = Field(description="the shared boundary score")
    winner: str = Field(description="letter the boundary score is assigned to (the higher grade)")
    loser: str = Field(description="letter that loses the boundary score")


class UnresolvedCutoffOverlap(StrictModel):
    """One overlapping cutoff pair this function refuses to resolve."""

    letters: tuple[str, str]
    reason: str


class CutoffOverlapResolution(StrictModel):
    schema_version: str = CUTOFF_RESOLUTION_SCHEMA_VERSION
    resolved: list[ResolvedCutoffOverlap] = Field(default_factory=list)
    unresolved: list[UnresolvedCutoffOverlap] = Field(default_factory=list)


def _is_fully_bounded(threshold: GradeThreshold) -> bool:
    return threshold.minimum is not None and threshold.maximum is not None


def _overlaps(a: GradeThreshold, b: GradeThreshold) -> bool:
    """Same test as reconciliation._check_grade_thresholds, but tolerant of
    single-bound thresholds (missing bound treated as +/- infinity) so that
    a single-bound overlap is still surfaced -- as unresolved.
    """
    a_lo = a.minimum if a.minimum is not None else float("-inf")
    a_hi = a.maximum if a.maximum is not None else float("inf")
    b_lo = b.minimum if b.minimum is not None else float("-inf")
    b_hi = b.maximum if b.maximum is not None else float("inf")
    return max(a_lo, b_lo) <= min(a_hi, b_hi)


def _ordered_letters(a: GradeThreshold, b: GradeThreshold) -> tuple[str, str]:
    """(higher grade, lower grade) when both are canonical; else (a, b) as given."""
    ra = CANONICAL_LETTER_RANK.get(a.letter)
    rb = CANONICAL_LETTER_RANK.get(b.letter)
    if ra is not None and rb is not None and rb < ra:
        return b.letter, a.letter
    return a.letter, b.letter


def _connected_components(
    thresholds: list[GradeThreshold], pairs: list[tuple[int, int]]
) -> list[set[int]]:
    parent = list(range(len(thresholds)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in pairs:
        parent[find(i)] = find(j)

    groups: dict[int, set[int]] = {}
    for i, j in pairs:
        root = find(i)
        groups.setdefault(root, set()).update((i, j))
    return list(groups.values())


def _classify_pair(higher: GradeThreshold, lower: GradeThreshold) -> ResolvedCutoffOverlap | UnresolvedCutoffOverlap:
    letters = (higher.letter, lower.letter)

    if not (_is_fully_bounded(higher) and _is_fully_bounded(lower)):
        return UnresolvedCutoffOverlap(letters=letters, reason="single_bound_threshold")

    rank_h = CANONICAL_LETTER_RANK.get(higher.letter)
    rank_l = CANONICAL_LETTER_RANK.get(lower.letter)
    if rank_h is None or rank_l is None:
        return UnresolvedCutoffOverlap(letters=letters, reason="non_canonical_letters")
    if rank_l - rank_h != 1:
        return UnresolvedCutoffOverlap(letters=letters, reason="non_adjacent_letters")

    overlap_lo = max(higher.minimum, lower.minimum)
    overlap_hi = min(higher.maximum, lower.maximum)
    if overlap_lo != overlap_hi:
        return UnresolvedCutoffOverlap(letters=letters, reason="overlap_wider_than_a_point")

    # The single shared point should be exactly "lower grade's ceiling ==
    # higher grade's floor". Anything else (e.g. inverted or nested ranges
    # that still touch at one point) is unexpected geometry -- do not guess.
    if not (higher.minimum == overlap_lo and lower.maximum == overlap_hi):
        return UnresolvedCutoffOverlap(letters=letters, reason="unexpected_overlap_geometry")

    return ResolvedCutoffOverlap(
        letters=letters,
        boundary=float(overlap_lo),
        winner=higher.letter,
        loser=lower.letter,
    )


def resolve_cutoff_overlaps(
    thresholds: list[GradeThreshold],
    letter_rank: dict[str, int] | None = None,
) -> CutoffOverlapResolution:
    """Propose higher-grade-wins resolutions for overlapping cutoffs.

    `letter_rank` defaults to reconciliation.CANONICAL_LETTER_RANK; it is a
    parameter only so tests can exercise the canonical-membership branch
    with a custom map. Non-overlapping input yields an empty resolution.
    """
    if letter_rank is not None:
        # Kept as a parameter for testability; the module's helpers close
        # over the canonical map, so an override only makes sense when it IS
        # the canonical map. Guard against silent divergence.
        if letter_rank != CANONICAL_LETTER_RANK:
            raise ValueError("resolve_cutoff_overlaps only supports the canonical A-F letter rank")

    pairs: list[tuple[int, int]] = []
    for i in range(len(thresholds)):
        for j in range(i + 1, len(thresholds)):
            if thresholds[i].letter == thresholds[j].letter:
                continue
            if _overlaps(thresholds[i], thresholds[j]):
                pairs.append((i, j))

    if not pairs:
        return CutoffOverlapResolution()

    multi_way_indices: set[int] = set()
    for component in _connected_components(thresholds, pairs):
        if len(component) > 2:
            multi_way_indices.update(component)

    resolved: list[ResolvedCutoffOverlap] = []
    unresolved: list[UnresolvedCutoffOverlap] = []
    for i, j in pairs:
        higher_letter, lower_letter = _ordered_letters(thresholds[i], thresholds[j])
        higher = thresholds[i] if thresholds[i].letter == higher_letter else thresholds[j]
        lower = thresholds[i] if thresholds[i].letter == lower_letter else thresholds[j]

        if i in multi_way_indices or j in multi_way_indices:
            unresolved.append(
                UnresolvedCutoffOverlap(letters=(higher.letter, lower.letter), reason="multi_way_overlap")
            )
            continue

        outcome = _classify_pair(higher, lower)
        if isinstance(outcome, ResolvedCutoffOverlap):
            resolved.append(outcome)
        else:
            unresolved.append(outcome)

    resolved.sort(key=lambda r: r.letters)
    unresolved.sort(key=lambda u: (u.letters, u.reason))
    return CutoffOverlapResolution(resolved=resolved, unresolved=unresolved)
