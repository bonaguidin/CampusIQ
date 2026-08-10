"""Text extraction from uploaded transcript files.

Stage 1 of the transcript parser: bytes in, plain text out. No AI call, no
course matching, no database write -- this module exists so that "did we read
the file" and "did the model understand it" stay independently diagnosable.

NEVER RAISES on file content. This is called from a request handler with
untrusted user input, so every failure mode -- encrypted PDF, truncated file,
wrong magic bytes, a .docx that is really a renamed .zip -- comes back as a
TranscriptExtractionResult with a non-"ok" status. A raised exception here
would 500 the process on a malformed upload.

RELATIONSHIP TO resume/extraction.py
------------------------------------
The mechanics of "get text out of a PDF or DOCX" are domain-neutral: layout
mode for PDFs, a body-element walk for DOCX. Those are imported from
GradusIQ_career.resume.extraction rather than copied, so a fix to either one
lands in both parsers. What is NOT shared is the part that is actually about
transcripts: the status vocabulary and every user-facing message.

That import direction (transcript -> resume) reads oddly and is deliberate but
temporary. The cleaner shape is a shared GradusIQ_career/extraction/ package
that both parsers import from. That refactor is left for later ON PURPOSE:
resume/extraction.py is live in production today, and moving it is a
higher-risk change than this stage should carry. See the report for the full
reasoning.
"""

from dataclasses import dataclass
from typing import Literal

from pypdf.errors import FileNotDecryptedError

# Format-level primitives, shared deliberately -- see module docstring. These
# are private-by-convention in resume.extraction; the underscore marks them as
# "not part of that module's public API", not "must not be reused". The future
# GradusIQ_career/extraction/ package is where they should end up public.
from GradusIQ_career.resume.extraction import (
    DOCX_CONTENT_TYPES,
    LEGACY_DOC_CONTENT_TYPES,
    OLE2_MAGIC,
    PDF_CONTENT_TYPES,
    _extract_docx,
    _extract_pdf,
    _meaningful_length,
    _normalize_content_type,
    _page_marker,
)


TranscriptExtractionStatus = Literal[
    "ok",
    "empty",
    "unsupported_format",
    "extraction_failed",
    "encrypted",
]

# "encrypted" is a status of its own rather than a flavour of
# extraction_failed. A password-protected transcript is the one failure here
# the student can fix themselves in ten seconds, so the caller needs to branch
# on it -- and branching on a message substring is exactly the kind of thing
# that breaks the next time someone rewords a sentence.

# Below this many NON-WHITESPACE characters, the extraction is treated as
# having produced nothing usable. Deliberately not zero: an image-only PDF page
# frequently yields a stray glyph or two, and a scanned transcript that
# extracts to "." is the same failure as one that extracts to "" -- both would
# send an effectively blank document to a paid LLM call and get back a
# confidently invented set of courses and a wrong GPA. No genuine transcript is
# under 20 characters.
#
# Intentionally a separate constant from the resume module's, despite the same
# value: these are two independent tuning knobs on two independent flows, and
# tuning one must not silently move the other.
MIN_MEANINGFUL_CHARS = 20


@dataclass(frozen=True)
class TranscriptExtractionResult:
    """Outcome of a single transcript extraction attempt.

    `text` is always a string -- never None -- so callers can log or inspect
    the partial output even on a non-"ok" status.
    """

    text: str
    status: TranscriptExtractionStatus
    message: str = ""
    page_count: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def extract_transcript_text(
    file_bytes: bytes, content_type: str
) -> TranscriptExtractionResult:
    """Extract plain text from an uploaded academic transcript.

    STAGE 2 HANDOFF -- `text` is what gets fed to the parsing prompt, and the
    length cap there MUST be a hard error, not a silent truncation. The resume
    parser slices to MAX_PROMPT_CHARS and appends a "[... truncated]" note
    (GradusIQ_career/resume/parser.py, build_messages). Copying that behaviour
    here would be a correctness bug: a resume that loses its last bullet is
    degraded, but a transcript that loses its last semesters drops real courses
    AND yields a GPA computed over a subset of them -- a plausible-looking
    wrong number written into the student's permanent record. Stage 2 must
    reject an over-length transcript outright. Nothing is truncated in Stage 1.

    Args:
        file_bytes: the raw uploaded bytes.
        content_type: the declared MIME type; parameters (e.g. "; charset=")
            are ignored.

    Returns:
        TranscriptExtractionResult. Never raises for bad input -- see the
        module docstring.
    """
    if not file_bytes:
        return TranscriptExtractionResult(
            text="",
            status="empty",
            message="The uploaded file is empty (0 bytes).",
        )

    media_type = _normalize_content_type(content_type)

    # Checked before the content-type dispatch so a mislabelled legacy file
    # still gets the actionable message rather than a parser failure.
    if file_bytes.startswith(OLE2_MAGIC) or media_type in LEGACY_DOC_CONTENT_TYPES:
        return TranscriptExtractionResult(
            text="",
            status="unsupported_format",
            message=(
                "Legacy Word .doc (Word 97-2003) files are not supported. "
                "Re-save the transcript as .docx or PDF and upload it again."
            ),
        )

    if media_type in PDF_CONTENT_TYPES:
        kind = "PDF"
    elif media_type in DOCX_CONTENT_TYPES:
        kind = "DOCX"
    else:
        return TranscriptExtractionResult(
            text="",
            status="unsupported_format",
            message=(
                f"Unsupported file type '{media_type or 'unknown'}'. "
                "Upload your transcript as a PDF or a .docx Word document."
            ),
        )

    page_count: int | None = None
    try:
        if kind == "PDF":
            text, page_count = _extract_pdf(file_bytes)
        else:
            text = _extract_docx(file_bytes)
    except FileNotDecryptedError:
        # Caught ABOVE the blanket handler, and caught rather than pre-checked.
        # reader.is_encrypted is NOT the right signal: a PDF issued with an
        # owner password but an empty user password -- the "no printing, no
        # copying" restriction registrars routinely apply -- reports
        # is_encrypted == True and still extracts perfectly. Only an actual
        # decryption failure means the student has to do something.
        return TranscriptExtractionResult(
            text="",
            status="encrypted",
            message=(
                "This PDF appears to be password-protected. Please upload an "
                "unprotected version of your transcript."
            ),
        )
    except Exception as exc:  # noqa: BLE001 -- untrusted input; see module docstring
        return TranscriptExtractionResult(
            text="",
            status="extraction_failed",
            message=f"Could not read the {kind} file: {type(exc).__name__}: {exc}",
        )

    # Measured on the extracted content only. The PDF page markers the shared
    # extractor adds are our own output and must not be what pushes a blank
    # scan over the threshold.
    if kind == "PDF":
        markers = {_page_marker(i) for i in range(1, (page_count or 0) + 1)}
        body_only = "\n".join(
            line for line in text.splitlines() if line not in markers
        )
    else:
        body_only = text

    if _meaningful_length(body_only) < MIN_MEANINGFUL_CHARS:
        # Far more likely for transcripts than for resumes: students commonly
        # photograph or scan a paper transcript, or download a PDF that is one
        # flat image per page. There is no OCR anywhere in this codebase and
        # adding it is out of scope, so the message has to be honest about the
        # limit and point at the fix.
        return TranscriptExtractionResult(
            text=text,
            status="empty",
            message=(
                "This looks like a scanned or image-based transcript. We can't "
                "read text from scanned documents yet -- please upload a "
                "text-based PDF export if your institution offers one."
            ),
            page_count=page_count,
        )

    return TranscriptExtractionResult(text=text, status="ok", page_count=page_count)
