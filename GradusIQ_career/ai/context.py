"""Small, typed execution context for canonical AI feature calls."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping
from uuid import uuid4

from GradusIQ_career.student_intelligence_profile import StudentIntelligenceProfile


TrustLevel = Literal["trusted_internal", "trusted_reference", "untrusted_external"]


@dataclass(frozen=True)
class GroundingMetadata:
    """Describes grounding without copying its potentially sensitive payload."""

    source_types: tuple[str, ...] = ()
    trust_level: TrustLevel = "trusted_reference"
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentContext:
    """Execution metadata plus the canonical input for one feature invocation.

    The profile is deliberately retained only in memory. ``trace`` generation
    never serializes this object, so student data cannot accidentally become
    diagnostic metadata.
    """

    feature: str
    canonical_profile: StudentIntelligenceProfile
    model_role: str
    prompt_name: str
    prompt_version: str
    grounding: GroundingMetadata
    request_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
