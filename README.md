# Aethelgard MCP

Three research MCP services. One orchestrator. Inspectable evidence and financial math.

Compare supplied tickers, rank a researched universe, or run without tickers to investigate the current market and discover candidates. The default brief emphasizes growth, value, technology, semiconductors and durable market leaders while testing cross-sector alternatives. It aims for 3–5 supported recommendations and may withhold every recommendation when evidence is incomplete.

**This is a research system, not a trading bot or a validated return-prediction engine.** The services use different research roles; shared models and sources do not create independent statistical evidence.

## Try it without credentials

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

~~~sh
git clone https://github.com/DaniyalHayat/aethelgard-mcp_v0.git
cd aethelgard-mcp_v0
uv sync --locked --extra dev
uv run aethelgard-research --demo
~~~

The demo launches three actual MCP subprocesses and exercises every stage with clearly labeled fabricated fixtures. It makes no network requests and spends no API credits. Reports are saved under the ignored directory `runs/<run-id>/`.

## Live research

Copy `.env.example` to `.env` in the repository and enter your own `OPENAI_API_KEY`. All example credentials are blank. Model and limits are configurable. Never commit credentials or put them in research prompts.

~~~sh
uv run aethelgard-research
uv run aethelgard-research --tickers VRT MRVL --horizons 8 10 --budget 160
uv run aethelgard-research --mode rank --candidates 12 --horizons 0.5 1.4 4.6
uv run aethelgard-research --tickers MSFT MA --as-of 2026-11-20T12:45:00+00:00
~~~

These symbols demonstrate the interface; production discovery has no fixed ticker watchlist. Requests support up to 20 symbols/candidates and five horizons. Large requests may need a higher output-token limit or a narrower universe. Incomplete provider responses fail closed.

A complete live run submits **17 model requests** with web search enabled. Request and output-token limits are **not a dollar cap or a hosted-search-action cap**. Your API provider bills usage separately. There are no automatic retries. Mocked provider tests and offline MCP connections have passed; a billed end-to-end live run has not been verified in this development session.

## Connect an MCP host

Replace the directory with your absolute checkout path:

~~~json
{
  "mcpServers": {
    "aethelgard": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/aethelgard-mcp_v0", "run", "aethelgard-mcp"]
    }
  }
}
~~~

Windows JSON paths can use forward slashes, such as `C:/Projects/aethelgard-mcp_v0`. Add `--demo` after `aethelgard-mcp` for offline use.

Call `start_research` with an empty request for market discovery, or supply `tickers`, `mode`, `candidate_limit`, `budget_per_horizon`, `horizons_years`, `objective` and a timezone-aware `as_of`. Poll `research_status`, then read `research_report`. Cancellation stops pending work; requests already submitted may still be billed.

The orchestrator launches three independently addressable services:

~~~sh
uv run python -m aethelgard_mcp.worker --role fundamental
uv run python -m aethelgard_mcp.worker --role valuation
uv run python -m aethelgard_mcp.worker --role challenge
~~~

Each exposes `research_stage` and `capabilities`. Separate registration is optional: the orchestrator already connects to all three over stdio.

## Review sequence

~~~mermaid
flowchart TD
    R[Ticker comparison or market discovery] --> O[Orchestrator: freeze request and cutoff]
    O --> F[Fundamental MCP]
    O --> V[Valuation MCP]
    O --> C[Challenge MCP]
    F --> S[Independent reports then own self-checks]
    V --> S
    C --> S
    S --> X[Each service reviews all three reports]
    X --> A[Fresh source, valuation and omission audits]
    A --> L[Academic and methodological challenge]
    L --> U[Each service revises its conclusions]
    U --> M[Deterministic calculations and evidence gates]
    M --> D[Orchestrator review and conditional rankings]
~~~

Stage barriers prevent peer context reaching the first pass. Each stage is a separate stateless model request. The orchestrator checks identity, ticker coverage, peer coverage, synthetic/live separation and final-universe membership. Sources, queries, citations, search actions, usage and artifact fingerprints remain inspectable.

Research covers business economics, owner earnings, FCFF/FCFE, reinvestment, ROIC, SBC/dilution, debt/leases, customer financing, contracts, AI power/supply constraints, macro/credit, news chronology, ETF overlap, technicals, tax and execution. These are requirements to investigate, not a claim that every fact can be obtained.

## Math, data and ranking

Deterministic tools include operating-to-FCFF/FCFE reconciliation, funded terminal growth, liquidity shortfalls, DCF, reverse implied growth, incremental ROIC, earnings/multiple attribution, portfolio/tax scenarios, dated shareholder IRR, Treasury carry/duration, and SMA/RSI/momentum/volatility/drawdown. The cash bridge retains compensation in margins, exposes acquisition/customer-financing uses and does not assume loss-related tax refunds by default. These tools check supplied inputs; they do not certify that a generated forecast is economically achievable.

The disclosed ranking score is **base holding-period return minus 0.5 × bear-case loss**. It is a risk preference, not expected return, probability-weighted optimization or a Sharpe ratio. Full scenarios remain visible. No future accuracy is claimed.

Missing/stale/post-cutoff prices, unread primary financial evidence, incomplete scenarios, blocking findings, absent cash-flow valuation or inconsistent EPS/multiple arithmetic withhold a candidate from computed rankings. A schema and valid URL cannot prove a source supports a generated claim. The generated narrative is retained for audit; `eligible_recommendations` contains the gated result.

Optional host tools:

- `issuer_filings`: SEC recent-submission metadata by CIK and acceptance timestamp. Set `SEC_USER_AGENT` to your application name and contact email. No SEC key is required. This returns filing links, not automatic audited statement extraction.
- `latest_stock_quotes`: timestamped Alpaca bid/ask pairs, provider sizes, exchange codes, spread, midpoint and quote age using your market-data keys. IEX is one venue, SIP requires entitlement, and `delayed_sip` has a 15-minute delay. Missing, crossed, zero-price, nonfinite or materially future-dated quotes are explicitly withheld per symbol. This is latest-available data, not a historical-cutoff lookup or a guaranteed broker fill. [Endpoint contract](https://docs.alpaca.markets/us/reference/stocklatestquotes-1).
- `adjusted_price_history`: Alpaca history and technicals using your `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. IEX is one venue; SIP requires entitlement. Pagination is checked. Adjusted history is not an executable quote or guaranteed point-in-time backtest data.

These optional tools are separate from the autonomous research stages, which use hosted web search. Their output is not automatically injected into research calls.

## Verification

~~~sh
uv run ruff check .
uv run pytest -q
uv build
~~~

Tests cover financial identities, evidence failures, tax netting, malformed/refused provider output, credential protection, pagination, stage isolation, cancellation and a full three-subprocess MCP run. CI needs no keys. See [architecture](docs/architecture.md), [methodology](docs/methodology.md) and [verification](docs/verification.md).

The full [research controls](src/aethelgard_mcp/resources/research-controls.md) are packaged with the server, included in each role's instructions and exposed as the MCP resource `aethelgard://research-controls`. They incorporate explicit source-version checks, indirect manager exposure, same-index controls, funded reinvestment, tax netting and academic-method limits.

Prompts are versioned source, not hidden system-prompt or model-weight changes. No brokerage orders, account access, paid-data purchases or external messages are implemented. Development is AI-assisted, with meaningful commits and explicit verification limits.
