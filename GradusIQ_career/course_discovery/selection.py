"""Deterministic pre-qualification candidate evidence and pool selection."""

from collections.abc import Mapping

from .models import CourseSearchResult, MatchKind, canonical_course_code


def merge_candidate_evidence(
    existing: CourseSearchResult | None,
    incoming: CourseSearchResult,
) -> CourseSearchResult:
    """Merge repeated observations without duplicating a qualification slot."""
    if existing is None:
        return incoming
    if existing.course.course_code != incoming.course.course_code:
        raise ValueError("candidate evidence can only be merged for the same course")
    best = min(
        (existing, incoming),
        key=lambda item: (-item.score, item.course.course_code),
    )
    return CourseSearchResult(
        course=best.course,
        score=max(existing.score, incoming.score),
        match_kinds=sorted(
            set(existing.match_kinds) | set(incoming.match_kinds),
            key=lambda item: item.value,
        ),
        matched_terms=sorted(set(existing.matched_terms) | set(incoming.matched_terms)),
    )


def observe_candidate(
    observed: dict[str, CourseSearchResult],
    incoming: CourseSearchResult,
) -> None:
    code = incoming.course.course_code
    observed[code] = merge_candidate_evidence(observed.get(code), incoming)


def _selection_key(candidate: CourseSearchResult) -> tuple:
    kinds = set(candidate.match_kinds)
    exact_code_match = any(
        canonical_course_code(term) == candidate.course.course_code
        for term in candidate.matched_terms
    )
    return (
        -int(exact_code_match),
        -int(MatchKind.COURSE_CODE in kinds),
        -candidate.score,
        -int(MatchKind.TITLE in kinds),
        -len(kinds),
        -len(candidate.matched_terms),
        candidate.course.course_code,
    )


def select_candidates_for_qualification(
    observed: Mapping[str, CourseSearchResult],
    *,
    limit: int,
) -> list[CourseSearchResult]:
    """Return the strongest bounded candidates across every observed search."""
    if limit < 1:
        raise ValueError("qualification candidate limit must be positive")
    return sorted(observed.values(), key=_selection_key)[:limit]


def select_candidates_with_seed_floor(
    seeded: Mapping[str, CourseSearchResult],
    observed: Mapping[str, CourseSearchResult],
    *,
    limit: int,
) -> list[CourseSearchResult]:
    """Protect the strongest deterministic seed floor and fill spare capacity."""
    seed_floor = select_candidates_for_qualification(seeded, limit=limit)
    floor_codes = {item.course.course_code for item in seed_floor}
    selected = [
        observed.get(item.course.course_code, item)
        for item in seed_floor
    ]
    remaining = limit - len(selected)
    if remaining <= 0:
        return selected
    supplemental = {
        code: candidate
        for code, candidate in observed.items()
        if code not in floor_codes
    }
    return [
        *selected,
        *select_candidates_for_qualification(supplemental, limit=remaining),
    ]
