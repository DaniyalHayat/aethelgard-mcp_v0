"""The fourth MCP service: orchestration, status and deterministic calculators."""

import argparse
from contextlib import asynccontextmanager
from datetime import datetime
from importlib.resources import files
from typing import Any

from mcp.server import MCPServer

from . import calculators
from .config import Settings
from .data_sources import PublicData
from .models import ResearchRequest
from .orchestrator import Orchestrator


def create_server(settings: Settings, orchestrator=None):
    coordinator = orchestrator or Orchestrator(settings)

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield {}
        finally:
            await coordinator.close()

    server = MCPServer(
        "aethelgard-orchestrator",
        version="0.1.0",
        lifespan=lifespan,
        instructions="Start research, poll status, then read the report. Live runs can incur API charges. Three separate research services are coordinated internally.",
    )

    @server.resource("aethelgard://research-controls", mime_type="text/markdown")
    def research_controls() -> str:
        """Read the versioned evidence, valuation and review rules used by every research role."""
        return files("aethelgard_mcp").joinpath("resources/research-controls.md").read_text(encoding="utf-8")

    @server.tool(structured_output=True)
    async def issuer_filings(cik: str, as_of: str) -> dict[str, Any]:
        """Retrieve SEC filing metadata through a cutoff using your SEC_USER_AGENT."""
        return await PublicData().sec_filings(cik, datetime.fromisoformat(as_of))

    @server.tool(structured_output=True)
    async def adjusted_price_history(tickers: list[str], as_of: str, feed: str = "iex") -> dict[str, Any]:
        """Fetch optional Alpaca history and compute technicals; requires your market-data keys."""
        return await PublicData().stock_history(tickers, datetime.fromisoformat(as_of), feed)

    @server.tool(structured_output=True)
    async def start_research(request: dict | None = None) -> dict[str, Any]:
        """Start a full three-service review. Empty input discovers current market candidates."""
        return coordinator.start(ResearchRequest.model_validate(request or {}))

    @server.tool(structured_output=True)
    def research_status(run_id: str) -> dict[str, Any]:
        """Read a run's current stage, completed state or validation failure."""
        return coordinator.status(run_id)

    @server.tool(structured_output=True)
    def research_report(run_id: str) -> dict[str, Any]:
        """Read the complete structured report after research_status reports complete."""
        if coordinator.status(run_id)["status"] != "complete":
            raise ValueError("Report is not complete")
        return coordinator.store.read(run_id, "report.json")

    @server.tool(structured_output=True)
    def cancel_research(run_id: str) -> dict[str, Any]:
        """Cancel unfinished work. Provider requests already submitted may still be billed."""
        return coordinator.cancel(run_id)

    @server.tool(structured_output=True)
    def configuration() -> dict[str, Any]:
        """Describe configuration and cost limits without exposing API keys."""
        return {
            **settings.public(),
            "research_services": ["fundamental", "valuation", "challenge"],
            "planned_calls": 17,
            "live_provider_verified": False,
            "limits": "Call and output-token limits are not a hard dollar or search-call budget.",
        }

    for name in (
        "owner_cash_dcf",
        "enterprise_dcf",
        "reverse_growth",
        "incremental_roic",
        "return_attribution",
        "portfolio_return",
        "treasury_return",
        "shareholder_irr",
        "technical_context",
    ):
        server.tool(name=name, structured_output=True)(getattr(calculators, name))
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Use clearly labeled synthetic offline data")
    args = parser.parse_args()
    create_server(Settings.from_env(demo=args.demo)).run(transport="stdio")


if __name__ == "__main__":
    main()
