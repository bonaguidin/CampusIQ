"""Strict structured-output contracts for AI features."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FitRoleMatch(StrictOutputModel):
    role: str = Field(min_length=1)
    fit_level: Literal["high", "medium", "low"]
    rationale: str = Field(min_length=1)
    supporting_signals: list[str]
    missing_signals: list[str]


class FitOutput(StrictOutputModel):
    role_matches: list[FitRoleMatch] = Field(min_length=1, max_length=5)
    overall_fit_summary: str = Field(min_length=1)


def fit_output_is_valid(value: object) -> bool:
    """One semantic validation entry point shared by live and cached FIT."""
    try:
        FitOutput.model_validate(value)
    except (TypeError, ValueError):
        return False
    return True
