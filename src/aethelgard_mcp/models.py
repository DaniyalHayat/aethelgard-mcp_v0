"""Public request contracts and evidence provenance."""

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ResearchRequest(StrictModel):
    tickers: list[str] = Field(default_factory=list, max_length=20)
    candidate_limit: int = Field(default=8, ge=1, le=20)
    budget_per_horizon: float = Field(default=160, gt=0, le=1e12)
    horizons_years: list[float] = Field(default_factory=lambda: [0.5, 1.4, 4.6], min_length=1, max_length=5)
    objective: str = Field(
        default="Seek attractive prospective returns with explicit downside and opportunity cost.",
        max_length=2000,
    )
    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mode: Literal["compare", "rank", "market"] = "market"

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip().upper() for value in values))
        if any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", value) for value in normalized):
            raise ValueError("Use exchange ticker symbols, not URLs, prose or commands")
        return normalized

    @field_validator("horizons_years")
    @classmethod
    def valid_horizons(cls, values: list[float]) -> list[float]:
        if any(not 0 < value <= 50 for value in values):
            raise ValueError("Each horizon must be positive and no longer than 50 years")
        return sorted(set(values))

    @field_validator("as_of")
    @classmethod
    def cutoff_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if value > datetime.now(timezone.utc) + timedelta(minutes=1):
            raise ValueError("A future cutoff cannot be researched as observed data")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def select_mode(self):
        if self.tickers and self.mode == "market":
            self.mode = "compare"
        if self.mode == "compare" and not self.tickers:
            raise ValueError("compare mode requires tickers; use market or rank to discover candidates")
        return self


class Evidence(StrictModel):
    source_id: str = Field(min_length=1, max_length=120)
    url: str = Field(pattern=r"^https://", max_length=3000)
    title: str = Field(min_length=1, max_length=500)
    claim: str = Field(min_length=1, max_length=5000)
    kind: Literal["observed", "dated_forecast", "assumption", "opinion"]
    authority: Literal["primary", "reported", "commentary"]
    published_at: datetime | None = None
    event_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    access: Literal["full_text", "indexed_excerpt", "unavailable"] = "full_text"

    @field_validator("published_at", "event_at", "retrieved_at")
    @classmethod
    def dates_have_timezone(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Evidence timestamps must include a timezone")
        return value

    def cutoff_status(self, cutoff: datetime) -> str:
        if self.published_at is None:
            return "publication_time_unverified"
        if self.published_at > cutoff:
            return "after_cutoff"
        if self.kind == "observed" and self.event_at is not None and self.event_at > cutoff:
            return "future_observation"
        if self.access == "unavailable":
            return "not_read"
        return "eligible"
