"""Transcript ingestion utilities for Gradus IQ.

Stages 1 and 2: extraction, parsing, term resolution, catalog matching,
storage, confirmation, and review. The frontend is Stage 3.
"""

from .catalog import MatchReport, match_courses, normalize_code
from .crosscheck import CrossCheckReport, cross_check_terms
from .extraction import (
    MIN_MEANINGFUL_CHARS,
    TranscriptExtractionResult,
    TranscriptExtractionStatus,
    extract_transcript_text,
)
from .parser import (
    MAX_PROMPT_CHARS,
    OUTPUT_CONTRACT,
    ParsedTranscript,
    ParseStatus,
    RejectedRow,
    TermSummary,
    TranscriptContractError,
    TranscriptTooLongError,
    coerce_credit_hours,
    parse_transcript_text,
    validate_parsed_transcript,
)
from .repeats import (
    ReconcileReport,
    RepeatExclusion,
    plan_exclusions,
    reconcile_repeats,
)
from .store import (
    TRANSCRIPT_SOURCE,
    ConfirmBlocked,
    StoreReport,
    confirm_course_rows,
    counts_flags,
    grade_map_for,
    store_parsed_transcript,
    unverified_institutions,
)
from .terms import (
    ResolvedTerm,
    TermParseError,
    TermResolution,
    parse_term_label,
    resolve_terms,
)

__all__ = [
    "MAX_PROMPT_CHARS",
    "MIN_MEANINGFUL_CHARS",
    "OUTPUT_CONTRACT",
    "TRANSCRIPT_SOURCE",
    "ConfirmBlocked",
    "CrossCheckReport",
    "MatchReport",
    "ParseStatus",
    "ParsedTranscript",
    "ReconcileReport",
    "RejectedRow",
    "RepeatExclusion",
    "ResolvedTerm",
    "StoreReport",
    "TermParseError",
    "TermResolution",
    "TermSummary",
    "TranscriptContractError",
    "TranscriptExtractionResult",
    "TranscriptExtractionStatus",
    "TranscriptTooLongError",
    "coerce_credit_hours",
    "confirm_course_rows",
    "counts_flags",
    "cross_check_terms",
    "extract_transcript_text",
    "grade_map_for",
    "match_courses",
    "normalize_code",
    "parse_term_label",
    "plan_exclusions",
    "reconcile_repeats",
    "parse_transcript_text",
    "resolve_terms",
    "store_parsed_transcript",
    "unverified_institutions",
    "validate_parsed_transcript",
]
