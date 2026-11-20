"""Command-line entry point for the same MCP-backed workflow."""

import argparse
import asyncio
import json
from datetime import datetime

from .config import Settings
from .models import ResearchRequest
from .orchestrator import Orchestrator


async def execute(args):
    request = {
        "tickers": args.tickers or [],
        "mode": args.mode,
        "candidate_limit": args.candidates,
        "budget_per_horizon": args.budget,
        "horizons_years": args.horizons,
    }
    if args.as_of:
        request["as_of"] = datetime.fromisoformat(args.as_of)
    if args.objective:
        request["objective"] = args.objective
    coordinator = Orchestrator(Settings.from_env(demo=args.demo))
    try:
        started = coordinator.start(ResearchRequest.model_validate(request))
        print(json.dumps(started))
        status = await coordinator.wait(started["run_id"])
        print(json.dumps(status))
        return 0 if status["status"] == "complete" else 1
    finally:
        await coordinator.close()


def main():
    parser = argparse.ArgumentParser(description="Three research MCPs plus an evidence-checking orchestrator")
    parser.add_argument("--tickers", nargs="*")
    parser.add_argument("--mode", choices=["compare", "rank", "market"], default="market")
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("--budget", type=float, default=160)
    parser.add_argument("--horizons", nargs="+", type=float, default=[0.5, 1.4, 4.6])
    parser.add_argument("--as-of", help="ISO timestamp with timezone; future cutoffs are rejected")
    parser.add_argument("--objective")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(execute(args)))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
