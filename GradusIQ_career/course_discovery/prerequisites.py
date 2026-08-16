"""Conservative prerequisite parsing and evaluation over local catalog data."""

import re
from collections.abc import Callable

from .models import (
    CourseCatalogRecord,
    PrerequisiteEvaluation,
    PrerequisiteMode,
    PrerequisiteRequirement,
    PrerequisiteStatus,
    StudentCourseState,
    StudentCourseStatus,
)


_UNSUPPORTED = re.compile(
    r"\b(grade|gpa|major|minor|classification|standing|approval|permission|consent|"
    r"admission|honors?|department|instructor|corequisite|concurrent|equivalent|campus|program)\b",
    re.IGNORECASE,
)


def prerequisite_requirement(course: CourseCatalogRecord) -> PrerequisiteRequirement:
    raw = " ".join((course.prerequisite_text or "").split()) or None
    if raw is None:
        return PrerequisiteRequirement(mode=PrerequisiteMode.NONE)

    cross_listings = set(course.cross_listings)
    codes = list(dict.fromkeys(
        code for code in course.prerequisite_courses if code not in cross_listings
    ))
    restrictions = list(dict.fromkeys(course.restrictions))
    reasons: list[str] = []
    if course.cross_listings:
        reasons.append("cross-listing text is not prerequisite logic")
    if _UNSUPPORTED.search(raw):
        reasons.append("prerequisite text contains an unsupported non-course restriction")
    if restrictions:
        reasons.append("parsed non-course restrictions require trusted structured data")
    if not codes:
        reasons.append("prerequisite text has no safely parsed course requirement")

    lower = raw.lower()
    has_and = bool(re.search(r"\band\b", lower))
    has_or = bool(re.search(r"\bor\b", lower))
    if len(codes) > 1 and has_and and has_or:
        reasons.append("mixed AND/OR grouping was not preserved by the catalog parser")
    if len(codes) > 1 and not has_and and not has_or:
        reasons.append("multiple prerequisite courses have no preserved relationship")
    if reasons:
        return PrerequisiteRequirement(
            mode=PrerequisiteMode.UNRESOLVED,
            course_codes=codes,
            restrictions=restrictions,
            raw_text=raw,
            unresolved_reasons=list(dict.fromkeys(reasons)),
        )
    if len(codes) == 1:
        mode = PrerequisiteMode.ALL
    elif has_or:
        mode = PrerequisiteMode.ANY
    else:
        mode = PrerequisiteMode.ALL
    return PrerequisiteRequirement(mode=mode, course_codes=codes, raw_text=raw)


def evaluate_prerequisites(
    course: CourseCatalogRecord,
    status_for: Callable[[str], StudentCourseStatus],
) -> PrerequisiteEvaluation:
    requirement = prerequisite_requirement(course)
    if requirement.mode == PrerequisiteMode.NONE:
        return PrerequisiteEvaluation(
            status=PrerequisiteStatus.ELIGIBLE,
            requirement=requirement,
            reasons=["catalog lists no prerequisites"],
        )

    satisfied: list[str] = []
    missing: list[str] = []
    in_progress: list[str] = []
    planned: list[str] = []
    unknown: list[str] = []
    for code in requirement.course_codes:
        state = status_for(code).state
        if state == StudentCourseState.COMPLETED:
            satisfied.append(code)
        elif state == StudentCourseState.IN_PROGRESS:
            in_progress.append(code)
        elif state == StudentCourseState.PLANNED:
            planned.append(code)
        elif state == StudentCourseState.NOT_TAKEN:
            missing.append(code)
        else:
            unknown.append(code)

    if requirement.mode == PrerequisiteMode.UNRESOLVED:
        return PrerequisiteEvaluation(
            status=PrerequisiteStatus.UNRESOLVED,
            requirement=requirement,
            satisfied_courses=satisfied,
            missing_courses=missing,
            in_progress_courses=in_progress,
            planned_courses=planned,
            unknown_courses=unknown,
            reasons=requirement.unresolved_reasons,
        )

    if requirement.mode == PrerequisiteMode.ANY and satisfied:
        status = PrerequisiteStatus.ELIGIBLE
        reasons = ["at least one alternative prerequisite is completed"]
    elif requirement.mode == PrerequisiteMode.ALL and len(satisfied) == len(requirement.course_codes):
        status = PrerequisiteStatus.ELIGIBLE
        reasons = ["all required prerequisite courses are completed"]
    elif in_progress or unknown:
        status = PrerequisiteStatus.UNRESOLVED
        reasons = ["in-progress or unknown prerequisite evidence is not treated as completed"]
    else:
        status = PrerequisiteStatus.INELIGIBLE
        reasons = ["one or more required prerequisite courses are not completed"]
    if planned:
        reasons.append("planned prerequisites are not currently satisfied")
    return PrerequisiteEvaluation(
        status=status,
        requirement=requirement,
        satisfied_courses=satisfied,
        missing_courses=missing,
        in_progress_courses=in_progress,
        planned_courses=planned,
        unknown_courses=unknown,
        reasons=reasons,
    )
