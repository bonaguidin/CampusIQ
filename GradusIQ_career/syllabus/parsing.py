"""PDF -> ParsedSyllabusDocument adapter (Phase 2).

Library choice: native PyMuPDF (`pymupdf`), not PyMuPDF4LLM. PyMuPDF4LLM's
markdown converter pulls in an ONNX layout-detection stack (onnxruntime,
numpy, networkx, protobuf, tabulate, psutil) built for scanned/complex
layouts -- unnecessary weight for the digitally generated, single-column
syllabi this phase targets, and this phase explicitly excludes OCR/vision.
Plain PyMuPDF exposes page-by-page text with font metadata, from which this
module derives a deterministic, lightweight Markdown rendering itself: no
ML model, no extra runtime dependency, fully reproducible across runs.

Scope: native-text ("digital") PDFs only. A PDF with no extractable text
(a scanned page, an image-only page) fails loudly via
SyllabusNoExtractableTextError rather than returning a useless empty
document -- an OCR/vision fallback belongs to a future phase.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pymupdf

from GradusIQ_career.syllabus.models import (
    ParsedDocumentMetadata,
    ParsedPage,
    ParsedSection,
    ParsedSyllabusDocument,
)

# Mirrors resume/extraction.py's MIN_MEANINGFUL_CHARS threshold for "this is
# effectively blank" -- kept as a separate constant since the two domains
# are free to diverge later.
MIN_MEANINGFUL_CHARS = 20

# A line must be at least this many points larger than the page's dominant
# (body) font size to be treated as a heading.
_HEADING_SIZE_MARGIN = 1.0

# A "heading" longer than this is almost certainly a wrapped paragraph line
# that happens to share a larger font, not a section title.
_MAX_HEADING_CHARS = 120


class SyllabusParsingError(ValueError):
    """Base class for all syllabus PDF parsing failures."""


class SyllabusFileNotFoundError(SyllabusParsingError):
    pass


class SyllabusInvalidPDFError(SyllabusParsingError):
    pass


class SyllabusEncryptedPDFError(SyllabusParsingError):
    pass


class SyllabusEmptyDocumentError(SyllabusParsingError):
    pass


class SyllabusNoExtractableTextError(SyllabusParsingError):
    pass


_PageLines = list[tuple[str, float]]


def parse_syllabus_pdf(file_path: str | Path) -> ParsedSyllabusDocument:
    """Convert a native-text PDF into a ParsedSyllabusDocument.

    Raises a SyllabusParsingError subclass for anything that is not a
    readable, non-empty, native-text PDF. See the exceptions above for the
    specific failure modes distinguished.
    """
    path = Path(file_path)
    if not path.is_file():
        raise SyllabusFileNotFoundError(f"syllabus PDF not found: {path}")

    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # pymupdf raises its own FileDataError/RuntimeError subtypes
        raise SyllabusInvalidPDFError(f"could not open '{path}' as a PDF: {exc}") from exc

    try:
        return _parse_document(doc, path)
    finally:
        doc.close()


def _parse_document(doc: pymupdf.Document, path: Path) -> ParsedSyllabusDocument:
    if doc.is_encrypted:
        # Some producers set is_encrypted for restricted-permissions bits
        # without a real viewer password; an empty password recovers those.
        # Anything requiring an actual password fails here rather than
        # guessing at credentials.
        if not doc.authenticate(""):
            raise SyllabusEncryptedPDFError(f"'{path}' is password-protected; cannot extract text")

    if doc.page_count == 0:
        raise SyllabusEmptyDocumentError(f"'{path}' has zero pages")

    page_lines = [_extract_page_lines(page) for page in doc]
    body_size = _dominant_font_size(page_lines)

    pages = [
        ParsedPage(page_number=page_number, markdown=_lines_to_markdown(lines, body_size))
        for page_number, lines in enumerate(page_lines, start=1)
    ]

    total_chars = sum(len(page.markdown.strip()) for page in pages)
    if total_chars < MIN_MEANINGFUL_CHARS:
        raise SyllabusNoExtractableTextError(
            f"'{path}' produced no meaningful extractable text "
            "(likely a scanned/image-only PDF; OCR is not supported in this phase)"
        )

    return ParsedSyllabusDocument(
        pages=pages,
        sections=_extract_sections(page_lines, body_size),
        markdown=_combine_pages(pages),
        metadata=_build_metadata(doc, path),
    )


def _extract_page_lines(page: pymupdf.Page) -> _PageLines:
    """One (text, max_span_font_size) pair per non-empty line, in reading order."""
    lines: _PageLines = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:  # skip images/non-text blocks
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            size = max((span.get("size", 0.0) for span in spans), default=0.0)
            lines.append((text, size))
    return lines


def _dominant_font_size(page_lines: list[_PageLines]) -> float:
    sizes = [round(size, 1) for lines in page_lines for _, size in lines if size > 0]
    if not sizes:
        return 0.0
    return statistics.mode(sizes)


def _looks_like_heading(text: str, size: float, body_size: float) -> bool:
    return len(text) <= _MAX_HEADING_CHARS and size >= body_size + _HEADING_SIZE_MARGIN


def _lines_to_markdown(lines: _PageLines, body_size: float) -> str:
    rendered = [
        f"## {text}" if _looks_like_heading(text, size, body_size) else text for text, size in lines
    ]
    return _normalize_markdown("\n".join(rendered))


def _normalize_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized: list[str] = []
    blank_run = 0
    for line in text.split("\n"):
        line = line.rstrip()
        if line == "":
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        normalized.append(line)
    return "\n".join(normalized).strip()


def _combine_pages(pages: list[ParsedPage]) -> str:
    """Join per-page markdown with stable, machine-readable page markers.

    `<!-- page: N -->` is a valid Markdown/HTML comment, so it renders
    invisibly wherever this text is displayed as Markdown while remaining
    trivially greppable/parseable for downstream page-provenance lookups.
    """
    blocks = [f"<!-- page: {page.page_number} -->\n\n{page.markdown}" for page in pages]
    return "\n\n".join(blocks)


def _extract_sections(page_lines: list[_PageLines], body_size: float) -> list[ParsedSection]:
    """Lightweight deterministic section extraction from heading-sized lines.

    No semantic classification: a section is only ever created because a
    line was detected as a heading by font size. Content between one
    heading and the next (including across a page boundary) belongs to
    that section; text before the first heading is not a section at all.
    """
    sections: list[ParsedSection] = []
    heading: str | None = None
    pages_seen: list[int] = []
    body_lines: list[str] = []

    def flush() -> None:
        if heading is not None:
            sections.append(
                ParsedSection(
                    heading=heading,
                    page_numbers=sorted(set(pages_seen)),
                    markdown=_normalize_markdown("\n".join(body_lines)),
                )
            )

    for page_number, lines in enumerate(page_lines, start=1):
        for text, size in lines:
            if _looks_like_heading(text, size, body_size):
                flush()
                heading = text
                pages_seen = [page_number]
                body_lines = []
            elif heading is not None:
                body_lines.append(text)
                if page_number not in pages_seen:
                    pages_seen.append(page_number)
    flush()
    return sections


def _build_metadata(doc: pymupdf.Document, path: Path) -> ParsedDocumentMetadata:
    raw = doc.metadata or {}
    extra: dict[str, str] = {}
    title = (raw.get("title") or "").strip()
    author = (raw.get("author") or "").strip()
    if title:
        extra["pdf_title"] = title
    if author:
        extra["pdf_author"] = author
    return ParsedDocumentMetadata(
        source_filename=path.name,
        page_count=doc.page_count,
        extra=extra,
    )
