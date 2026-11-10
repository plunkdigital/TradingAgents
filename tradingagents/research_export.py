"""Public research export v1. Tool observations do not attest citation correctness.

The final typed decision is preserved directly, without parsing the narrative or
making another model call. Financial sizing and execution are outside this API.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating


class ToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=255)
    tool_name: str = Field(min_length=1, max_length=255)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    status: Literal["returned", "error"]
    output_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    output_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_observation(self):
        if self.completed_at < self.started_at:
            raise ValueError("Tool observation ends before it starts")
        if self.status == "returned" and (self.output_sha256 is None or self.output_bytes is None):
            raise ValueError("Returned tools require an output digest and byte count")
        return self


class ResearchExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    ticker: str = Field(min_length=1, max_length=100)
    analysis_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    asset_type: Literal["stock", "crypto"]
    completed_at: AwareDatetime
    decision_mode: Literal["structured", "free_text", "unavailable"]
    rating: PortfolioRating | Literal["REVIEW"] | None
    decision: PortfolioDecision | None
    narrative: str
    reports: dict[str, str]
    model_metadata: dict
    observations: list[ToolObservation]
    source_verification: Literal["not_performed"] = "not_performed"

    @model_validator(mode="after")
    def typed_provenance(self):
        if self.decision_mode == "structured":
            if self.decision is None or self.rating != self.decision.rating:
                raise ValueError("Typed decision and rating must agree")
        elif self.decision is not None:
            raise ValueError("Fallback must not retain a stale typed decision")
        if any(item.completed_at > self.completed_at for item in self.observations):
            raise ValueError("Tool observation is after export completion")
        return self


def build_research_export(state, settings, *, observations=(), completed_at=None) -> dict:
    """Validate and return JSON-safe fields. Never copy endpoints, keys or paths."""
    metadata = {key: settings.get(key) for key in (
        "version", "llm_provider", "quick_think_provider", "deep_think_provider",
        "quick_think_llm", "deep_think_llm",
    )}
    for key in ("data_adapter", "data_adapter_fingerprint"):
        if key in settings:
            metadata[key] = settings[key]
    result = ResearchExport(
        ticker=state["company_of_interest"], analysis_date=state["trade_date"],
        asset_type=state.get("asset_type", "stock"),
        completed_at=completed_at or datetime.now(timezone.utc),
        decision_mode=state.get("portfolio_decision_mode", "unavailable"),
        rating=state.get("final_rating"), decision=state.get("portfolio_decision"),
        narrative=state.get("final_trade_decision", ""),
        reports={key: state[key] for key in (
            "market_report", "fundamentals_report", "news_report", "sentiment_report",
        ) if isinstance(state.get(key), str)},
        model_metadata=metadata, observations=list(observations),
    )
    return result.model_dump(mode="json")
