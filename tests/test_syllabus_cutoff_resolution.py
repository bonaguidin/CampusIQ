"""Unit tests for cutoff_resolution.resolve_cutoff_overlaps -- the pure
"higher grade wins the tie" proposal over overlapping letter-grade cutoffs.
"""

import pytest

from GradusIQ_career.syllabus.cutoff_resolution import (
    CutoffOverlapResolution,
    resolve_cutoff_overlaps,
)
from GradusIQ_career.syllabus.models import GradeThreshold
from GradusIQ_career.syllabus.reconciliation import (
    CANONICAL_LETTER_RANK,
    _check_grade_thresholds,
)
from GradusIQ_career.syllabus.models import GradeModel


def th(letter: str, minimum=None, maximum=None) -> GradeThreshold:
    return GradeThreshold(letter=letter, minimum=minimum, maximum=maximum)


# --- resolved: canonical, rank-adjacent, exact shared boundary point ------------


def test_bc_boundary_overlap_resolves_to_higher_grade():
    result = resolve_cutoff_overlaps([th("B", 80, 90), th("C", 70, 80)])
    assert result.unresolved == []
    assert len(result.resolved) == 1
    r = result.resolved[0]
    assert r.boundary == 80.0
    assert r.winner == "B"
    assert r.loser == "C"
    assert r.letters == ("B", "C")


def test_ab_boundary_overlap_resolves_to_a():
    result = resolve_cutoff_overlaps([th("A", 90, 100), th("B", 80, 90)])
    assert [(r.winner, r.loser, r.boundary) for r in result.resolved] == [("A", "B", 90.0)]
    assert result.unresolved == []


def test_input_order_does_not_matter():
    lo_first = resolve_cutoff_overlaps([th("C", 70, 80), th("B", 80, 90)])
    hi_first = resolve_cutoff_overlaps([th("B", 80, 90), th("C", 70, 80)])
    assert lo_first.model_dump() == hi_first.model_dump()
    assert lo_first.resolved[0].winner == "B"


def test_two_independent_adjacent_boundary_pairs_both_resolve():
    # A/B share 90, C/D share 70; B and C do NOT touch -> two separate
    # 2-node components, both resolvable.
    thresholds = [th("A", 90, 100), th("B", 80, 90), th("C", 60, 70), th("D", 50, 60)]
    result = resolve_cutoff_overlaps(thresholds)
    assert result.unresolved == []
    assert {(r.winner, r.loser) for r in result.resolved} == {("A", "B"), ("C", "D")}


def test_degenerate_single_point_lower_threshold_still_resolves():
    # C is a single-point range touching B's floor.
    result = resolve_cutoff_overlaps([th("B", 80, 90), th("C", 80, 80)])
    assert [r.winner for r in result.resolved] == ["B"]
    assert result.unresolved == []


# --- unresolved: everything the function refuses to guess at -------------------


def test_non_adjacent_letters_unresolved():
    result = resolve_cutoff_overlaps([th("A", 80, 100), th("C", 70, 85)])
    assert result.resolved == []
    assert [(u.letters, u.reason) for u in result.unresolved] == [(("A", "C"), "non_adjacent_letters")]


def test_overlap_wider_than_a_point_unresolved():
    result = resolve_cutoff_overlaps([th("B", 79, 90), th("C", 70, 81)])
    assert result.resolved == []
    assert result.unresolved[0].reason == "overlap_wider_than_a_point"


def test_non_canonical_letters_unresolved():
    result = resolve_cutoff_overlaps([th("Pass", 60, 100), th("HighPass", 60, 100)])
    assert result.resolved == []
    assert result.unresolved[0].reason == "non_canonical_letters"


def test_single_bound_threshold_overlap_unresolved():
    # F has only a maximum; reconciliation's own detector skips this pair
    # entirely, this function surfaces it as explicitly unresolved.
    result = resolve_cutoff_overlaps([th("D", 60, 70), th("F", maximum=65)])
    assert result.resolved == []
    assert result.unresolved[0].reason == "single_bound_threshold"


def test_multi_way_component_all_pairs_unresolved():
    # B shares a boundary point with both A (at 90) and C (at 80): a
    # 3-threshold connected component -> nothing in it is resolved.
    thresholds = [th("A", 90, 100), th("B", 80, 90), th("C", 70, 80)]
    result = resolve_cutoff_overlaps(thresholds)
    assert result.resolved == []
    assert {u.reason for u in result.unresolved} == {"multi_way_overlap"}
    assert {u.letters for u in result.unresolved} == {("A", "B"), ("B", "C")}


def test_fully_inclusive_five_letter_scale_is_entirely_unresolved():
    thresholds = [
        th("A", 90, 100),
        th("B", 80, 90),
        th("C", 70, 80),
        th("D", 60, 70),
        th("F", 0, 60),
    ]
    result = resolve_cutoff_overlaps(thresholds)
    assert result.resolved == []
    assert all(u.reason == "multi_way_overlap" for u in result.unresolved)


def test_wider_three_way_overlap_unresolved():
    thresholds = [th("A", 85, 100), th("B", 80, 95), th("C", 78, 90)]
    result = resolve_cutoff_overlaps(thresholds)
    assert result.resolved == []
    assert {u.reason for u in result.unresolved} == {"multi_way_overlap"}


# --- no overlap / empty -------------------------------------------------------


def test_no_overlap_returns_empty_resolution():
    thresholds = [th("A", 90, 100), th("B", 80, 89), th("C", 70, 79)]
    result = resolve_cutoff_overlaps(thresholds)
    assert result == CutoffOverlapResolution()


def test_empty_input_returns_empty_resolution():
    assert resolve_cutoff_overlaps([]) == CutoffOverlapResolution()


# --- parity with reconciliation's detector ------------------------------------


def test_every_resolved_or_unresolved_pair_was_flagged_by_reconciliation():
    """The B/C-style boundary overlap this function resolves is exactly the
    shape _check_grade_thresholds flags as overlapping_grade_thresholds, so
    the resolution is a genuine follow-up to that finding, not a different
    notion of "overlap".
    """
    thresholds = [th("B", 80, 90), th("C", 70, 80)]
    findings = _check_grade_thresholds(GradeModel(grade_thresholds=thresholds))
    assert any(f.code == "overlapping_grade_thresholds" for f in findings)

    result = resolve_cutoff_overlaps(thresholds)
    assert len(result.resolved) == 1


# --- letter_rank parameter ---------------------------------------------------


def test_custom_letter_rank_must_be_canonical():
    with pytest.raises(ValueError):
        resolve_cutoff_overlaps([th("B", 80, 90), th("C", 70, 80)], letter_rank={"B": 0, "C": 1})


def test_passing_the_canonical_rank_explicitly_is_accepted():
    result = resolve_cutoff_overlaps([th("B", 80, 90), th("C", 70, 80)], letter_rank=CANONICAL_LETTER_RANK)
    assert result.resolved[0].winner == "B"
