"""Request models for the API."""
from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SurvivalRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: float = Field(ge=0.0, le=1.0)
    high: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> "SurvivalRange":
        if self.low > self.high:
            raise ValueError("low must be <= high")
        return self


class TreeCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    small: int = Field(default=0, ge=0, le=1_000_000)
    medium: int = Field(default=0, ge=0, le=1_000_000)
    large: int = Field(default=0, ge=0, le=1_000_000)


class SizeMix(BaseModel):
    """Relative weights (any positive scale, e.g. percentages) for each size class."""

    model_config = ConfigDict(extra="forbid")

    small: float = Field(default=0.0, ge=0.0)
    medium: float = Field(default=0.0, ge=0.0)
    large: float = Field(default=0.0, ge=0.0)


class CalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str = Field(description="City profile id, e.g. 'pune' or 'mumbai'.")

    # Give EITHER exact counts per size class OR a total plus a size mix.
    tree_counts: Optional[TreeCounts] = None
    total_trees: Optional[int] = Field(default=None, gt=0, le=1_000_000)
    size_mix: Optional[SizeMix] = None

    promised_ratio: Optional[float] = Field(
        default=None, ge=0.0, le=1000.0, description="Replacement trees promised per tree felled."
    )
    promised_survival: Optional[Union[float, SurvivalRange]] = Field(
        default=None, description="Survival stated in the promise. Default 100%."
    )
    realistic_survival: Optional[Union[float, SurvivalRange]] = Field(
        default=None, description="Override of the realistic survival (0-1 or a low/high range)."
    )
    survival_preset: Optional[str] = Field(
        default=None, description="Name of a preset from /city-profiles, e.g. 'mumbai_like' or 'chennai_like'."
    )
    growth_class: Optional[str] = Field(default=None, description="'fast', 'moderate' or 'slow'.")
    horizon_years: int = Field(default=40, ge=1, le=100)

    @model_validator(mode="after")
    def _counts_or_mix(self) -> "CalculateRequest":
        has_counts = self.tree_counts is not None
        has_total = self.total_trees is not None
        if has_counts and (has_total or self.size_mix is not None):
            raise ValueError("give either tree_counts, or total_trees with size_mix, not both")
        if not has_counts and not has_total:
            raise ValueError("give tree_counts, or total_trees with size_mix")
        if has_total and self.size_mix is None:
            raise ValueError("total_trees requires size_mix")
        if self.realistic_survival is not None and self.survival_preset is not None:
            raise ValueError("give realistic_survival or survival_preset, not both")
        for name in ("promised_survival", "realistic_survival"):
            v = getattr(self, name)
            if isinstance(v, float) and not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        return self
