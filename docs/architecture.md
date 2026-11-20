# Architecture and tradeoffs

Contracts, providers, math, source adapters, orchestration, storage and reporting are separate modules. Three worker processes expose one MCP interface with different research emphasis. A fourth service owns sequencing, call budgets, validation and report release.

The provider uses the OpenAI Responses API with hosted web search and structured JSON: a fixed HTTPS endpoint, no redirects, no implicit proxy environment, no retries and sanitized errors. Credentials are request headers, never prompt text or stored configuration. Source URLs must appear in provider search/citation metadata or prior-stage provider metadata; a model-created ledger alone is insufficient.

Independent calls receive no peer context. Self-review receives only its own report. All self-reviews finish before cross-review. Fresh audits use new stateless calls, followed by methodological study, revisions and consolidation. Parallelism is bounded. Failure cancels sibling work, preserves completed artifacts and withholds final recommendations.

Runs use random identifiers, confined filenames and atomic JSON writes. Restart marks unfinished runs interrupted. Stage fingerprints provide integrity checks, not financial truth. One active run is permitted per orchestrator instance; separate instances should use separate run directories.

Role diversity is methodological, not model diversity by default. Shared models and public sources create correlated errors. The orchestrator compares evidence quality and unresolved conflicts; forecast accuracy requires frozen predictions and later outcomes.

Current limits: no automatic XBRL normalization, licensed consensus feed, complete exchange-universe screener, historical archive guarantee, validated investment track record or dollar-denominated API cap. Default discovery is bounded public research, not exhaustive optimization.

References: [MCP SDK](https://py.sdk.modelcontextprotocol.io/), [Responses web search](https://developers.openai.com/api/docs/guides/tools-web-search), [structured output](https://developers.openai.com/api/docs/guides/structured-outputs), [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [Alpaca bars](https://docs.alpaca.markets/us/reference/stockbars).
