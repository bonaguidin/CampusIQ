"""Conservative prerequisite parsing and evaluation over local catalog data."""

import re
from collections.abc import Callable

from .models import (
    CourseCatalogRecord,
    PrerequisiteClause,
    PrerequisiteEvaluation,
    PrerequisiteMode,
    PrerequisiteRequirement,
    PrerequisiteStatus,
    StructuredPrerequisite,
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


# ============================================================================
# structured_prerequisite(): the richer parser for the degree-planner
# scheduler (planning-docs/degree-planner-spec.md §4).
#
# WHY A SEPARATE FUNCTION IN THIS FILE, NOT A CHANGE TO THE ABOVE: C1's
# prerequisite_requirement()/evaluate_prerequisites() are live in
# course_discovery/service.py, gating real-time single-course eligibility
# checks, and README.md documents their conservative UNRESOLVED-on-anything-
# complex boundary as an intentional design choice, not a gap to close. The
# degree-planner scheduler needs a genuinely richer parse -- nested AND/OR,
# grade minimums, corequisites -- to sequence an entire 4-year plan, which is
# a different risk profile (a wrong requires_all costs a bad *suggestion* the
# student can override, not a wrong real-time gate). Rather than fork the
# parsing logic into a second file, this stays in the same module so
# prerequisite-text parsing has one home; it just exposes a second, richer
# entry point alongside the first, conservative one.
#
# DESIGN GROUNDED IN LIVE DATA, not hypothetical cases. Every pattern branch
# below traces to an actual sampled prerequisites string, mostly from
# data/catalog/engineering/computer_science_engineering.json and
# data/catalog/smu/lyle.json, checked this session:
#
#   Plain AND of two courses:
#     "Grade of C or better in ECEN 248 and CSCE 120 ; junior or senior
#     classification."
#   AND of two OR-groups, grade-min restated per group:
#     "Grade of C or better in ENGR 102, CSCE 110, CSCE 111, or CSCE 206 ;
#     grade of C or better in MATH 251, MATH 253, or STAT 211 ; junior or
#     senior classification."
#   Cross-listed pair inside one OR-group (both codes are the same course):
#     "Grade of C or better in CSCE 222/ECEN 222 or ECEN 222/CSCE 222, or
#     concurrent enrollment."
#   Trailing "or concurrent enrollment" (modifies the courses already named
#   in the same clause -- completion OR concurrent enrollment satisfies it):
#     "Prerequisite: Grade of C or better in CSCE 221 , or concurrent
#     enrollment."
#   Explicit named corequisite, no prior completion at all, its own clause:
#     "CSCE 312 and CSCE 314 , or CSCE 350/ECEN 350 or ECEN 350/CSCE 350 ;
#     concurrent enrollment in CSCE 313 ."
#   A real course mixed with an unverifiable non-course alternative --
#   MUST NOT enter requires_all as if mandatory, or a student who tested out
#   via AP credit or got consent would be wrongly blocked:
#     "C- or better in CS 1341, a grade of at least 4 on the AP Computer
#     Science A Exam, or departmental consent."
#     "Any one of the following with grade of C or better: CS 4381, CS 5385,
#     ECE 5381, ECE 5383, ECE 5385, or consent of instructor."
#   Genuinely ambiguous nested AND/OR within one clause, no reliable
#   precedence -- best-effort AND-of-ORs parse, but flagged, not trusted
#   blindly:
#     "Grade of C or better in MATH 304, MATH 311, or MATH 323 ; Grade of C
#     or better in STAT 211, and STAT 404 or CSCE 221, or ECEN 303, and
#     CSCE 121 or CSCE 120."
#   Trailing "Cross Listing:" sentence -- not prerequisite logic at all, must
#   be stripped before clause-splitting or it reads as a bogus AND clause:
#     "...junior or senior classification. Cross Listing: ECEN 360 and
#     STAT 315 ."
#   Restriction-only, no course logic (SMU): "Restricted to Lyle seniors."
#
# NO CACHING/PERSISTENCE: computed on demand from an in-memory
# CourseCatalogRecord, same as prerequisite_requirement() above -- that
# sibling function has never been cached or backed by a database column
# despite being on the same hot path (catalog.py's course lookups are
# @lru_cache'd, but the string parsing itself is not), and this is cheap
# regex work, not an LLM call. §4 of the spec floated caching in a database
# column; that was written without visibility into this existing, uncached
# sibling function, and this deviates from that suggestion deliberately
# rather than by oversight -- add persistence later only if the scheduler's
# actual call volume makes it a measured problem.
# ============================================================================

_CROSS_LISTING_TRAILING = re.compile(r";?\s*Cross Listing:.*$", re.IGNORECASE | re.DOTALL)

_GRADE_WITH_LABEL = re.compile(r"grade\s+(?:of\s+)?([A-D][+-]?)\s+or\s+better", re.IGNORECASE)
_GRADE_BARE = re.compile(r"(?<![A-Za-z0-9])([A-D][+-]?)\s+or\s+better\b")

_CONCURRENT_NAMED = re.compile(r"concurrent enrollment in\s+(.*)", re.IGNORECASE)
_CONCURRENT_TRAILING = re.compile(r",?\s*or\s+concurrent enrollment\.?\s*$", re.IGNORECASE)

_AND_SPLIT = re.compile(r"\band\b", re.IGNORECASE)
_OR_WORD = re.compile(r"\bor\b", re.IGNORECASE)

# Clauses matching this and carrying no course code are recognized eligibility
# text, not an unhandled gap -- routed to StructuredPrerequisite.restrictions.
# Broader than course_discovery.prerequisites._UNSUPPORTED above: that list
# also includes "grade"/"concurrent"/"corequisite", which this parser handles
# specifically rather than treating as generic non-course noise, and this
# list adds "replaces"/"taught at" for catalog-metadata sentences ("also
# taught at Galveston campus.", "Replaces CHEM 323 in previous catalogs.")
# that §4's full-catalog audit found riding in the same prerequisites field.
_KNOWN_NON_COURSE = re.compile(
    r"\b(classification|approval|permission|consent|admission|honors?|department|"
    r"instructor|equivalent|campus|program|major|minor|standing|replaces|taught at|"
    r"restrict\w*)\b",
    re.IGNORECASE,
)

# A course code mixed with one of these in the same OR-group is an
# unverifiable alternative path (instructor sign-off, AP credit, an
# unlisted equivalent course) -- the clause must not enter requires_all as
# if the named course were strictly mandatory. Narrower than
# _KNOWN_NON_COURSE on purpose: "junior or senior classification" alongside
# a course code in the same *clause* would be unusual (classification
# clauses are consistently their own semicolon-separated clause in every
# sampled row), so only the alternative-path phrasings actually observed
# sharing a clause with a real course code are matched here.
_NON_COURSE_ALTERNATIVE = re.compile(
    r"\b(consent|approval|permission|equivalent)\b|\bAP\b.*\bExam\b",
    re.IGNORECASE,
)


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _split_clauses(text: str) -> list[str]:
    """Semicolons are the primary clause delimiter in every sampled row;
    sentence boundaries within a clause are also split defensively, though
    no sampled row needed it (every real "." fell at a clause's own end).
    """
    pieces: list[str] = []
    for chunk in text.split(";"):
        pieces.extend(re.split(r"(?<=[.!?])\s+", chunk))
    return [piece.strip(" .;\t\n") for piece in pieces if piece.strip(" .;\t\n")]


def _codes_in_text(text: str, known_codes: list[str]) -> list[str]:
    """known_codes is the course's own already-extracted prerequisite_courses
    (normalize_catalog.py / fetch_smu_catalog.py's codes_in()/
    extract_prerequisite_courses()) -- substring containment against that
    trusted set, rather than re-deriving a course-code regex here, so this
    parser cannot disagree with the catalog layer about what counts as a
    course code (TAMU 3-digit vs SMU 4-digit, cross-listed slash pairs, all
    already handled upstream).
    """
    return [code for code in known_codes if code and code in text]


def _has_ambiguous_and_or(text_without_grade_phrase: str, code_count: int) -> bool:
    """True when a clause mixes real AND and real OR operators (beyond the
    "grade ... or better" idiom, already stripped by the caller) across
    multiple course codes, with no reliable way to infer precedence from
    prose alone -- e.g. "STAT 211, and STAT 404 or CSCE 221, or ECEN 303,
    and CSCE 121 or CSCE 120" (confirmed live). A single "and" splitting two
    clean OR-groups (the overwhelmingly common real-data shape, e.g. "CSCE
    221 and CSCE 222/ECEN 222") is handled by the caller's AND-split, not
    flagged here.
    """
    and_count = len(_AND_SPLIT.findall(text_without_grade_phrase))
    has_or = bool(_OR_WORD.search(text_without_grade_phrase))
    return code_count > 1 and and_count > 1 and has_or


def structured_prerequisite(course: CourseCatalogRecord) -> StructuredPrerequisite:
    """Parse course.prerequisite_text into the richer structured form the
    degree-planner scheduler consumes. See the module-level comment above
    this function for the design and the live examples it's grounded in.
    """
    raw = " ".join((course.prerequisite_text or "").split()) or None
    if raw is None:
        return StructuredPrerequisite(raw_text=None)

    text = _CROSS_LISTING_TRAILING.sub("", raw).strip()
    known_codes = [code for code in course.prerequisite_courses if code not in set(course.cross_listings)]

    requires_all: list[PrerequisiteClause] = []
    coreq_allowed: list[str] = []
    restrictions: list[str] = []
    needs_review: list[str] = []

    for clause in _split_clauses(text):
        # Explicit named corequisite: "concurrent enrollment in CSCE 313".
        named = _CONCURRENT_NAMED.search(clause)
        if named:
            codes = _codes_in_text(named.group(1), known_codes)
            remainder = (clause[: named.start()] + clause[named.end() :]).strip(" ,;.")
            if codes and not remainder:
                coreq_allowed.extend(codes)
                continue
            # Either no known code followed "concurrent enrollment in", or
            # there's other content in the same clause this parser hasn't
            # seen a live example of -- don't guess, flag it.
            needs_review.append(clause)
            continue

        # Trailing "or concurrent enrollment": the courses named earlier in
        # THIS SAME clause are satisfied by completion OR concurrent
        # enrollment -- both requires_all (still a real requirement) and
        # coreq_allowed (concurrent enrollment also counts).
        is_trailing_coreq = bool(_CONCURRENT_TRAILING.search(clause))
        working = _CONCURRENT_TRAILING.sub("", clause).strip(" ,;.") if is_trailing_coreq else clause

        grade_match = _GRADE_WITH_LABEL.search(working) or _GRADE_BARE.search(working)
        grade_min = grade_match.group(1).upper() if grade_match else None
        working_no_grade = _GRADE_WITH_LABEL.sub("", working)
        working_no_grade = _GRADE_BARE.sub("", working_no_grade)

        codes = _codes_in_text(working, known_codes)

        if not codes:
            # No course code at all: recognized eligibility text (its own
            # regex, independent of CourseCatalogRecord.restrictions -- see
            # StructuredPrerequisite.restrictions' docstring for why), or
            # genuinely unrecognized phrasing this parser has no live
            # example of yet.
            if _KNOWN_NON_COURSE.search(working):
                restrictions.append(clause)
            else:
                needs_review.append(clause)
            continue

        if _NON_COURSE_ALTERNATIVE.search(working_no_grade):
            # A real course code sharing an OR-group with an unverifiable
            # alternative path (instructor consent, AP credit, "or
            # equivalent"). Withheld from requires_all on purpose: including
            # it would wrongly block a student who satisfied the
            # requirement via the other path.
            needs_review.append(clause)
            continue

        if _AND_SPLIT.search(working_no_grade):
            sub_clauses = [part.strip(" ,;.") for part in _AND_SPLIT.split(working_no_grade)]
            sub_clauses = [part for part in sub_clauses if part]
            ambiguous = _has_ambiguous_and_or(working_no_grade, len(codes))
            any_sub_empty = False
            for sub_clause in sub_clauses:
                sub_codes = _codes_in_text(sub_clause, known_codes)
                if not sub_codes:
                    any_sub_empty = True
                    continue
                requires_all.append(PrerequisiteClause(course_codes=sub_codes, grade_min=grade_min))
                if is_trailing_coreq:
                    coreq_allowed.extend(sub_codes)
            if ambiguous or any_sub_empty:
                # Best-effort AND-split parse is still recorded above (more
                # useful to the scheduler than nothing), but flagged: don't
                # trust this one without a human look.
                needs_review.append(clause)
            continue

        requires_all.append(PrerequisiteClause(course_codes=codes, grade_min=grade_min))
        if is_trailing_coreq:
            coreq_allowed.extend(codes)

    return StructuredPrerequisite(
        requires_all=requires_all,
        coreq_allowed=_unique_preserve_order(coreq_allowed),
        restrictions=_unique_preserve_order(restrictions),
        needs_review=_unique_preserve_order(needs_review),
        raw_text=raw,
    )
