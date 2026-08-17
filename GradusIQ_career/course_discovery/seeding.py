"""Bounded deterministic catalog seeding from trusted career-skill needs."""

from dataclasses import dataclass, field

from .models import CareerSkillNeed, CourseSearchResult, EvidenceState, SearchCoursesInput
from .selection import observe_candidate
from .tools import ReadOnlyCourseTools


SEED_RESULTS_PER_NEED = 5
MAX_SEED_CANDIDATES = 12

_CATEGORY_PRIORITY = {
    "technology": 0,
    "knowledge": 1,
    "skills": 2,
    "abilities": 3,
}


@dataclass
class CandidateSeedResult:
    candidates: dict[str, CourseSearchResult] = field(default_factory=dict)
    need_ids_by_course: dict[str, set[str]] = field(default_factory=dict)
    search_count: int = 0
    candidate_count: int = 0


def seed_search_term(need: CareerSkillNeed) -> str:
    """Return one conservative catalog term derived only from the need itself."""
    term = " ".join(need.skill.split())
    # A one-character technology label is not safe input to the catalog's
    # prefix matcher. O*NET uses this shape for programming languages such as C.
    if need.category == "technology" and len(term) == 1 and term.isalnum():
        return "program"
    return term


def _need_priority(need: CareerSkillNeed) -> tuple:
    return (
        _CATEGORY_PRIORITY.get((need.category or "").lower(), 4),
        0 if need.importance == "required" else 1,
        -(need.confidence or 0),
        need.skill.lower(),
        need.need_id,
    )


def seed_candidates(
    tools: ReadOnlyCourseTools,
    needs: list[CareerSkillNeed],
    *,
    per_need_limit: int = SEED_RESULTS_PER_NEED,
    total_limit: int = MAX_SEED_CANDIDATES,
) -> CandidateSeedResult:
    """Build a bounded catalog-backed floor without model or network input."""
    if per_need_limit < 1 or total_limit < 1:
        raise ValueError("candidate seed limits must be positive")
    result = CandidateSeedResult()
    trusted = sorted(
        (need for need in needs if need.evidence_state == EvidenceState.VERIFIED_LOCAL),
        key=_need_priority,
    )
    for need in trusted:
        if len(result.candidates) >= total_limit:
            break
        search = tools.search_courses(SearchCoursesInput(
            query=seed_search_term(need), limit=per_need_limit
        ))
        result.search_count += 1
        result.candidate_count += len(search.results)
        for candidate in search.results:
            code = candidate.course.course_code
            observe_candidate(result.candidates, candidate)
            result.need_ids_by_course.setdefault(code, set()).add(need.need_id)
            if len(result.candidates) >= total_limit:
                break
    return result
