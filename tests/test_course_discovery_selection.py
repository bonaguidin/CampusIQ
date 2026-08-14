from GradusIQ_career.course_discovery.catalog import LocalCatalogRepository
from GradusIQ_career.course_discovery.models import (
    CatalogInstitution,
    CourseSearchQuery,
    MatchKind,
)
from GradusIQ_career.course_discovery.selection import (
    observe_candidate,
    select_candidates_for_qualification,
)


def search(query: str, limit: int = 8):
    return LocalCatalogRepository().search(CourseSearchQuery(
        institution=CatalogInstitution.TAMU,
        query=query,
        limit=limit,
    ))


def test_later_stronger_candidate_displaces_earlier_weak_candidate():
    early = search("C", 8)
    later = search("CSCE 206", 1)[0]
    observed = {item.course.course_code: item for item in early}
    observe_candidate(observed, later)

    selected = select_candidates_for_qualification(observed, limit=8)
    codes = [item.course.course_code for item in selected]

    assert len(observed) == 9 and len(selected) == 8
    assert later.course.course_code in codes
    assert any(item.course.course_code not in codes for item in early)


def test_multiple_later_exact_candidates_enter_same_bounded_pool():
    observed = {item.course.course_code: item for item in search("C", 8)}
    later = [search("CSCE 206", 1)[0], search("CSCE 110", 1)[0]]
    for item in later:
        observe_candidate(observed, item)

    selected = select_candidates_for_qualification(observed, limit=8)
    codes = {item.course.course_code for item in selected}

    assert len(selected) == 8
    assert {item.course.course_code for item in later} <= codes


def test_equal_evidence_has_stable_course_code_tie_break():
    candidates = [
        item.model_copy(update={
            "score": 10,
            "match_kinds": [MatchKind.DESCRIPTION],
            "matched_terms": ["shared"],
        })
        for item in reversed(search("C", 8))
    ]
    observed = {item.course.course_code: item for item in candidates}

    first = select_candidates_for_qualification(observed, limit=8)
    second = select_candidates_for_qualification(dict(reversed(list(observed.items()))), limit=8)

    expected = sorted(item.course.course_code for item in candidates)
    assert [item.course.course_code for item in first] == expected
    assert [item.course.course_code for item in second] == expected


def test_duplicate_course_merges_evidence_into_one_slot():
    exact = search("CSCE 206", 1)[0]
    descriptive = exact.model_copy(update={
        "score": 12,
        "match_kinds": [MatchKind.DESCRIPTION],
        "matched_terms": ["programming"],
    })
    observed = {}
    observe_candidate(observed, descriptive)
    observe_candidate(observed, exact)

    selected = select_candidates_for_qualification(observed, limit=8)

    assert len(observed) == len(selected) == 1
    assert selected[0].score == exact.score
    assert set(selected[0].match_kinds) == {MatchKind.COURSE_CODE, MatchKind.DESCRIPTION}
    assert set(selected[0].matched_terms) >= {"programming"}


def test_pool_never_exceeds_batch_limit():
    observed = {}
    for item in [*search("C", 8), *search("software", 8)]:
        observe_candidate(observed, item)
    assert len(observed) > 8
    assert len(select_candidates_for_qualification(observed, limit=8)) == 8
