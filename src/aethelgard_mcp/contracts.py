"""Structured research artifacts; prose is never a substitute for validated inputs."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .models import Evidence, StrictModel

Role = Literal["fundamental", "valuation", "challenge"]
Stage = Literal["independent", "self_review", "cross_review", "fresh_audit", "study", "revision", "final"]


class Scenario(StrictModel):
    name: Literal["bear", "base", "bull"]
    years: float = Field(gt=0, le=50)
    terminal_price: float = Field(ge=0)
    dividends_per_share: float = Field(default=0, ge=0)
    starting_eps: float | None = Field(default=None, gt=0)
    terminal_eps: float | None = Field(default=None, ge=0)
    exit_pe: float | None = Field(default=None, gt=0)
    rationale: str = Field(min_length=1)


class Valuation(StrictModel):
    cash_flow_type: Literal["FCFF", "FCFE"]
    cashflows: list[float] = Field(min_length=1, max_length=30)
    discount_rate: float = Field(gt=0, lt=1)
    terminal_growth: float = Field(ge=-0.2, le=0.1)
    net_debt: float = 0
    diluted_shares: float = Field(gt=0)
    units: str = Field(min_length=1)
    bridge_explanation: str = Field(min_length=1)
    reinvestment_explanation: str = Field(min_length=1)


class Candidate(StrictModel):
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$")
    thesis: str
    risks: list[str]
    price: float | None = Field(default=None, gt=0)
    price_at: datetime | None = None
    price_source_id: str | None = None
    financial_source_ids: list[str] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    valuation: Valuation | None = None
    gaps: list[str] = Field(default_factory=list)

    @field_validator("price_at")
    @classmethod
    def timestamp_has_timezone(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Price timestamps require a timezone")
        return value


class Finding(StrictModel):
    subject: str
    severity: Literal["blocking", "material", "minor"]
    explanation: str
    correction: str


class ResearchArtifact(StrictModel):
    narrative: str
    queries: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list, max_length=20)
    findings: list[Finding] = Field(default_factory=list)
    reviewed_roles: list[Role] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list, max_length=5)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def unique_evidence(cls, values):
        ids = [row.source_id for row in values]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence identifiers must be unique within an artifact")
        return values

    @field_validator("candidates")
    @classmethod
    def unique_candidates(cls, values):
        names = [row.ticker for row in values]
        if len(names) != len(set(names)):
            raise ValueError("Candidate symbols must be unique")
        return values


class StageResult(StrictModel):
    role: str
    stage: Stage
    artifact: ResearchArtifact
    citations: list[dict] = Field(default_factory=list)
    search_actions: list[dict] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    model: str
    prompt_version: str
    synthetic: bool = False
