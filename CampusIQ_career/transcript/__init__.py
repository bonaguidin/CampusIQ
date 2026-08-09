"""Transcript ingestion utilities for Campus IQ.

Stage 1 only: extraction. Parsing, course matching, and storage land in later
stages and will extend this package's exports.
"""

from .extraction import (
    MIN_MEANINGFUL_CHARS,
    TranscriptExtractionResult,
    TranscriptExtractionStatus,
    extract_transcript_text,
)

__all__ = [
    "MIN_MEANINGFUL_CHARS",
    "TranscriptExtractionResult",
    "TranscriptExtractionStatus",
    "extract_transcript_text",
]
