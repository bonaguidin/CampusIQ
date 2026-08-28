"""Deterministic relevance selection over a ParsedSyllabusDocument (Phase 3).

    ParsedSyllabusDocument -> select_relevant_syllabus_content() -> RelevantSyllabusContent

This module decides WHERE grading information probably lives in a syllabus.
It never decides WHAT that information means: it may record that page 4
matched signals "grading_heading" and "percentage", but it must never
produce a GradeCategory, a weight, or any other structured grading fact --
that belongs to a future LLM-extraction phase (Phase 4) that consumes this
module's output.

No file I/O, no network calls, no LLM calls. Pure text scanning over
Phase 2's ParsedSyllabusDocument, entirely local and reproducible.

Design: Phase 2 deliberately uses conservative, font-size-based heading
detection, so a syllabus with same-size bold "headings" can produce sparse
or empty ParsedSection entries even though its pages hold real grading
content. This module therefore scores content two ways -- against
`document.sections` (heading + body) and independently against every raw
`document.pages` entry (embedded "## " heading lines plus full page text)
-- and unions whatever clears the threshold either way. See
SELECTION_THRESHOLD and the *_SIGNAL_CATEGORIES tables below for the single
place all scoring weights live.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from pydantic import Field

from GradusIQ_career.syllabus.models import ParsedPage, ParsedSyllabusDocument, StrictModel

RELEVANT_SYLLABUS_CONTENT_SCHEMA_VERSION = "1"


class RelevanceSignal(str, Enum):
    # Heading-level signals (matched against a ParsedSection.heading, or a
    # "## ..." line embedded in a ParsedPage's markdown by Phase 2).
    GRADING_HEADING = "grading_heading"
    GRADE_SCALE_HEADING = "grade_scale_heading"
    ASSESSMENT_HEADING = "assessment_heading"
    SCHEDULE_HEADING = "schedule_heading"
    # Content-level signals (matched against raw page/section body text).
    ASSESSMENT_TERM = "assessment_term"
    WEIGHT_TERM = "weight_term"
    GRADE_SCALE_TERM = "grade_scale_term"
    RULE_TERM = "rule_term"
    SCHEDULE_TERM = "schedule_term"
    # Structural signals, not tied to any keyword list.
    MULTI_SIGNAL = "multi_signal"
    CONTEXT_EXPANSION = "context_expansion"


class RelevantPage(StrictModel):
    page_number: int = Field(ge=1)
    markdown: str
    matched_signals: list[RelevanceSignal] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    relevance_score: float = Field(ge=0)


class RelevantSection(StrictModel):
    heading: str
    page_numbers: list[int] = Field(min_length=1)
    markdown: str
    matched_signals: list[RelevanceSignal] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    relevance_score: float = Field(ge=0)


class RelevantSyllabusContent(StrictModel):
    schema_version: str = RELEVANT_SYLLABUS_CONTENT_SCHEMA_VERSION
    selected_pages: list[RelevantPage] = Field(default_factory=list)
    selected_sections: list[RelevantSection] = Field(default_factory=list)
    markdown: str = ""
    source_page_count: int = Field(ge=0)
    selected_page_count: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Scoring configuration -- the single place weights and keyword lists live.
# ---------------------------------------------------------------------------


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    if phrase == "%":
        return re.compile(re.escape(phrase))
    return re.compile(rf"\b{re.escape(phrase)}\b")


@dataclass(frozen=True)
class _SignalCategory:
    signal: RelevanceSignal
    weight: float
    patterns: tuple[re.Pattern[str], ...]


def _category(signal: RelevanceSignal, weight: float, *phrases: str, extra: tuple[re.Pattern[str], ...] = ()) -> _SignalCategory:
    return _SignalCategory(signal=signal, weight=weight, patterns=tuple(_phrase_pattern(p) for p in phrases) + extra)


# A heading contributes its category's weight once if ANY of its phrases
# appear as a substring of the normalized heading text. Deliberately
# excludes bare, over-broad tokens ("policy", "information", "requirements")
# that boilerplate sections (disability policy, Title IX, ...) also use.
STRONG_HEADING_WEIGHT = 5.0
MEDIUM_HEADING_WEIGHT = 2.0

HEADING_SIGNAL_CATEGORIES: tuple[_SignalCategory, ...] = (
    _category(RelevanceSignal.GRADING_HEADING, STRONG_HEADING_WEIGHT, "grading policy", "grade policy", "grading"),
    _category(RelevanceSignal.GRADE_SCALE_HEADING, STRONG_HEADING_WEIGHT, "grade scale", "grading scale"),
    _category(
        RelevanceSignal.ASSESSMENT_HEADING,
        MEDIUM_HEADING_WEIGHT,
        "grades",
        "assessment",
        "assessments",
        "evaluation",
        "course evaluation",
        "exams",
        "examinations",
        "quizzes",
        "assignments",
        "homework",
        "projects",
        "course requirements",
        "late work",
        "missed work",
        "makeup",
        "make-up",
        "extra credit",
    ),
    _category(
        RelevanceSignal.SCHEDULE_HEADING,
        MEDIUM_HEADING_WEIGHT,
        "course schedule",
        "class schedule",
        "semester schedule",
        "important dates",
    ),
)

# A grade-letter cutoff line such as "A: 90-100" or "B = 80-89": a single
# letter A-F, optional +/-, then ":" or "=". \b before the letter keeps this
# from matching inside another word (e.g. "TA:").
_GRADE_LETTER_PATTERN = re.compile(r"\b[a-f][+-]?\s*[:=]")

CONTENT_SIGNAL_CATEGORIES: tuple[_SignalCategory, ...] = (
    _category(
        RelevanceSignal.ASSESSMENT_TERM,
        1.0,
        # Singular and plural spelled out explicitly rather than a suffix
        # regex: "lab" + a wildcard suffix would also match "label", so
        # exact phrases stay the safer, still-deterministic choice.
        "exam",
        "exams",
        "midterm",
        "mid-term",
        "final exam",
        "quiz",
        "quizzes",
        "homework",
        "assignment",
        "assignments",
        "project",
        "projects",
        "lab",
        "labs",
        "participation",
        "attendance",
    ),
    _category(
        RelevanceSignal.WEIGHT_TERM,
        1.0,
        "%",
        "percent",
        "percentage",
        "weight",
        "weighted",
        "points",
        "pts",
        "total points",
    ),
    _category(
        RelevanceSignal.GRADE_SCALE_TERM,
        2.0,
        "grade scale",
        "grading scale",
        "letter grade",
        "passing",
        extra=(_GRADE_LETTER_PATTERN,),
    ),
    _category(
        RelevanceSignal.RULE_TERM,
        2.0,
        "drop",
        "dropped",
        "lowest",
        "replace",
        "replaces",
        "replacement",
        "curve",
        "curved",
        "extra credit",
        "late",
        "makeup",
        "make-up",
        "missed exam",
    ),
    _category(
        RelevanceSignal.SCHEDULE_TERM,
        1.0,
        "exam date",
        "due",
        "course schedule",
        "class schedule",
        "semester schedule",
    ),
)

# A page/section is selected only once its total score clears this bar.
# A single medium heading (2.0) or a single content category (1.0-2.0) never
# clears it alone -- corroboration from a second category is required
# (see MULTI_SIGNAL_BONUS), which is the precision guard against boilerplate
# that mentions "grade" or "late" exactly once (see module docstring).
SELECTION_THRESHOLD = 3.0

# Reaching multiple distinct content-signal categories on the same page or
# section (e.g. an assessment term AND a percentage, or an assessment term
# AND a replacement rule) is itself a strong indicator of an actual grading
# table or policy sentence, not a stray keyword -- rewarded on top of each
# category's own weight.
MULTI_SIGNAL_BONUS = 2.0

# A raw page must score at least this high on its own (i.e. clearly a
# grading page by itself) before an adjacent page is considered for
# conservative context expansion. See _expand_context below.
STRONG_SCORE_THRESHOLD = 5.0

_HEADING_LINE_PATTERN = re.compile(r"^##\s+(.*)$", re.MULTILINE)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _score(text: str, categories: tuple[_SignalCategory, ...]) -> tuple[float, set[RelevanceSignal], set[str], int]:
    """Return (score, matched signals, matched literal terms, categories matched)."""
    normalized = _normalize(text)
    score = 0.0
    signals: set[RelevanceSignal] = set()
    terms: set[str] = set()
    matched_categories = 0
    for category in categories:
        matched = [m for pattern in category.patterns if (m := pattern.search(normalized))]
        if not matched:
            continue
        score += category.weight
        signals.add(category.signal)
        terms.update(m.group(0) for m in matched)
        matched_categories += 1
    return score, signals, terms, matched_categories


def _score_heading(heading: str) -> tuple[float, set[RelevanceSignal], set[str]]:
    score, signals, terms, _ = _score(heading, HEADING_SIGNAL_CATEGORIES)
    return score, signals, terms


def _score_content(body: str) -> tuple[float, set[RelevanceSignal], set[str]]:
    score, signals, terms, matched_categories = _score(body, CONTENT_SIGNAL_CATEGORIES)
    if matched_categories >= 2:
        score += MULTI_SIGNAL_BONUS
        signals.add(RelevanceSignal.MULTI_SIGNAL)
    return score, signals, terms


def _has_markdown_heading(markdown: str) -> bool:
    return _HEADING_LINE_PATTERN.search(markdown) is not None


def _score_page(page: ParsedPage) -> tuple[float, set[RelevanceSignal], set[str]]:
    """Score a raw page: any "## " lines Phase 2 embedded as headings, plus
    the page's full text as content. This is the fallback path for syllabi
    where Phase 2's conservative font-size heading detection found nothing.
    """
    heading_score = 0.0
    heading_signals: set[RelevanceSignal] = set()
    heading_terms: set[str] = set()
    for match in _HEADING_LINE_PATTERN.finditer(page.markdown):
        s, sig, terms = _score_heading(match.group(1))
        heading_score += s
        heading_signals |= sig
        heading_terms |= terms

    content_score, content_signals, content_terms = _score_content(page.markdown)
    return (
        heading_score + content_score,
        heading_signals | content_signals,
        heading_terms | content_terms,
    )


def _combine_selected_pages(pages: list[RelevantPage]) -> str:
    blocks = [f"<!-- page: {page.page_number} -->\n\n{page.markdown}" for page in pages]
    return "\n\n".join(blocks)


def _expand_context(
    page_by_number: dict[int, ParsedPage],
    scored_pages: dict[int, tuple[float, set[RelevanceSignal], set[str]]],
    page_selected: set[int],
    already_selected: set[int],
) -> set[int]:
    """Conservatively pull in the immediately following page of a strongly
    relevant raw-page match when it looks like a continuation: no new "## "
    heading of its own, and at least a trace of matching content (so a
    following blank/unrelated administrative page is never swept in).

    Sections already get this for free -- Phase 2 groups a section's body
    across page boundaries whenever no new heading interrupts it -- so this
    only matters for pages that were never captured as a section at all.
    """
    expanded: set[int] = set()
    for page_number in sorted(page_selected):
        score, _, _ = scored_pages[page_number]
        if score < STRONG_SCORE_THRESHOLD:
            continue
        next_number = page_number + 1
        next_page = page_by_number.get(next_number)
        if next_page is None or next_number in already_selected:
            continue
        if _has_markdown_heading(next_page.markdown):
            continue
        next_score, _, _ = scored_pages[next_number]
        if next_score > 0:
            expanded.add(next_number)
    return expanded


def select_relevant_syllabus_content(document: ParsedSyllabusDocument) -> RelevantSyllabusContent:
    """Select the portions of a parsed syllabus most likely to describe
    grading. Deterministic, local-only: no file I/O, no model calls.

    Does not interpret grading semantics -- the result only says where
    grading information probably is, via matched_signals/matched_terms and
    relevance_score, never a parsed grading fact.
    """
    page_by_number = {page.page_number: page for page in document.pages}
    scored_pages = {page.page_number: _score_page(page) for page in document.pages}
    page_selected = {n for n, (score, _, _) in scored_pages.items() if score >= SELECTION_THRESHOLD}

    selected_sections: list[RelevantSection] = []
    section_selected_pages: set[int] = set()
    for section in document.sections:
        heading_score, heading_signals, heading_terms = _score_heading(section.heading)
        content_score, content_signals, content_terms = _score_content(section.markdown)
        total = heading_score + content_score
        if total < SELECTION_THRESHOLD:
            continue
        signals = sorted(heading_signals | content_signals, key=lambda s: s.value)
        terms = sorted(heading_terms | content_terms)
        selected_sections.append(
            RelevantSection(
                heading=section.heading,
                page_numbers=list(section.page_numbers),
                markdown=section.markdown,
                matched_signals=signals,
                matched_terms=terms,
                relevance_score=total,
            )
        )
        section_selected_pages.update(section.page_numbers)

    combined_selected = page_selected | section_selected_pages
    expanded = _expand_context(page_by_number, scored_pages, page_selected, combined_selected)
    combined_selected |= expanded

    selected_pages: list[RelevantPage] = []
    for page_number in sorted(combined_selected):
        page = page_by_number.get(page_number)
        if page is None:
            # A section can, in principle, cite a page_number with no
            # corresponding ParsedPage (Phase 1's model does not enforce
            # that invariant even though Phase 2's parser always produces
            # matching pages). The RelevantSection above still preserves
            # that provenance; there is just no raw page text to attach
            # here or fold into the combined, page-oriented markdown.
            continue
        score, signals, terms = scored_pages[page_number]
        if page_number in expanded:
            signals = signals | {RelevanceSignal.CONTEXT_EXPANSION}
        selected_pages.append(
            RelevantPage(
                page_number=page_number,
                markdown=page.markdown,
                matched_signals=sorted(signals, key=lambda s: s.value),
                matched_terms=sorted(terms),
                relevance_score=score,
            )
        )

    return RelevantSyllabusContent(
        selected_pages=selected_pages,
        selected_sections=selected_sections,
        markdown=_combine_selected_pages(selected_pages),
        source_page_count=len(document.pages),
        selected_page_count=len(selected_pages),
    )
