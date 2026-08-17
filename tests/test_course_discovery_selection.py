from GradusIQ_career.course_discovery.catalog import LocalCatalogRepository
from GradusIQ_career.course_discovery.models import (
    CatalogInstitution,
    CourseSearchQuery,
    MatchKind,
)
from GradusIQ_career.course_discovery.selection import (
    observe_candidate,
    select_candidates_for_qualification,
    select_candidates_with_seed_floor,
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


def test_full_seed_floor_cannot_be_evicted_by_stronger_supplemental_candidates():
    seeded = {item.course.course_code: item for item in search("C", 8)}
    observed = dict(seeded)
    supplemental = search("software", 8)
    for item in supplemental:
        if item.course.course_code not in seeded:
            observe_candidate(observed, item.model_copy(update={
                "score": 100,
                "match_kinds": [MatchKind.COURSE_CODE, MatchKind.TITLE],
                "matched_terms": [item.course.course_code],
            }))

    selected = select_candidates_with_seed_floor(seeded, observed, limit=8)

    assert [item.course.course_code for item in selected] == [
        item.course.course_code
        for item in select_candidates_for_qualification(seeded, limit=8)
    ]


def test_partial_seed_floor_preserves_floor_and_fills_strongest_supplemental():
    seeded_items = search("C", 5)
    seeded = {item.course.course_code: item for item in seeded_items}
    observed = dict(seeded)
    for item in search("software", 8):
        observe_candidate(observed, item)

    selected = select_candidates_with_seed_floor(seeded, observed, limit=8)
    selected_codes = [item.course.course_code for item in selected]
    floor_codes = [
        item.course.course_code
        for item in select_candidates_for_qualification(seeded, limit=8)
    ]
    supplemental = {
        code: item for code, item in observed.items() if code not in seeded
    }
    expected_fill = [
        item.course.course_code
        for item in select_candidates_for_qualification(supplemental, limit=3)
    ]

    assert selected_codes == [*floor_codes, *expected_fill]
    assert len(selected) == 8


def test_both_source_evidence_merges_without_consuming_an_extra_floor_slot():
    seeded_item = search("CSCE 206", 1)[0]
    seeded = {seeded_item.course.course_code: seeded_item}
    observed = dict(seeded)
    observe_candidate(observed, seeded_item.model_copy(update={
        "match_kinds": [MatchKind.DESCRIPTION],
        "matched_terms": ["programming"],
    }))

    selected = select_candidates_with_seed_floor(seeded, observed, limit=8)

    assert len(selected) == 1
    assert set(selected[0].match_kinds) == {
        MatchKind.COURSE_CODE, MatchKind.DESCRIPTION,
    }


def test_protected_pool_remains_hard_bounded():
    seeded = {item.course.course_code: item for item in search("C", 8)}
    observed = dict(seeded)
    for item in search("software", 8):
        observe_candidate(observed, item)

    assert len(select_candidates_with_seed_floor(seeded, observed, limit=8)) == 8
