"""A separately launchable MCP research service for one independent role."""

import argparse
import json
from typing import Any

from mcp.server import MCPServer

from .config import Settings
from .contracts import Role, Stage
from .models import ResearchRequest
from .prompts import PROMPT_VERSION, ROLE_FOCUS
from .provider import ResponsesProvider, SyntheticProvider


def create_worker(role: Role, settings: Settings, provider=None):
    provider = provider or (SyntheticProvider(settings) if settings.demo else ResponsesProvider(settings))
    server = MCPServer("aethelgard-" + role, instructions=ROLE_FOCUS[role], version="0.1.0")

    @server.tool(structured_output=True)
    async def research_stage(stage: Stage, request: dict, context: dict | None = None) -> dict[str, Any]:
        """Research one stage. A live call uses the configured API key and may incur charges."""
        if len(json.dumps(context or {})) > 240_000:
            raise ValueError("Context exceeds the explicit 240,000-character budget; narrow the universe")
        validated = ResearchRequest.model_validate(request)
        if stage == "independent" and context:
            raise ValueError("Independent research must not receive peer context")
        result = await provider.run(role, stage, validated, context or {})
        return result.model_dump(mode="json")

    @server.tool(structured_output=True)
    def capabilities() -> dict[str, Any]:
        """Return role identity and public configuration without credentials."""
        return {
            "role": role,
            "focus": ROLE_FOCUS[role],
            "prompt_version": PROMPT_VERSION,
            "configuration": settings.public(),
        }

    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["fundamental", "valuation", "challenge"], required=True)
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    create_worker(args.role, Settings.from_env(demo=args.demo)).run(transport="stdio")


if __name__ == "__main__":
    main()
