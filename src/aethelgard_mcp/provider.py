"""Single-call Responses transport and explicitly synthetic, network-free fixtures."""

import json
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from .config import Settings
from .contracts import Candidate, ResearchArtifact, Scenario, StageResult, Valuation
from .models import Evidence, ResearchRequest
from .prompts import PROMPT_VERSION, ROLE_FOCUS, ROLES, STAGES, build_prompt

RESPONSES_URL = "https://api.openai.com/v1/responses"


class ProviderError(RuntimeError):
    """A sanitized provider failure, with no upstream body or credentials."""


def _check_inputs(role: str, stage: str, request: ResearchRequest) -> None:
    if (
        not isinstance(role, str)
        or not isinstance(stage, str)
        or role not in ROLE_FOCUS
        or stage not in STAGES
        or not isinstance(request, ResearchRequest)
    ):
        raise ProviderError("Invalid research role, stage or request.")


def _url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
        ):
            return value
    except ValueError:
        pass
    return None


def _source_urls(citations: list[dict], actions: list[dict]) -> set[str]:
    urls = set()
    for citation in citations:
        if citation.get("type") == "url_citation" and (url := _url(citation.get("url"))):
            urls.add(url)
    for call in actions:
        action = call.get("action", call)
        if not isinstance(action, dict):
            continue
        if action.get("type") in ("open_page", "find_in_page") and (url := _url(action.get("url"))):
            urls.add(url)
        sources = action.get("sources", [])
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict) and (url := _url(source.get("url"))):
                    urls.add(url)
    return urls


def _prior_urls(context: Any) -> set[str]:
    urls: set[str] = set()
    pending = [context]
    visited = set()
    while pending:
        item = pending.pop()
        if isinstance(item, (dict, list, tuple, StageResult)):
            if id(item) in visited:
                continue
            visited.add(id(item))
        if isinstance(item, StageResult):
            if not item.synthetic:
                urls.update(_source_urls(item.citations, item.search_actions))
        elif isinstance(item, dict):
            if {"artifact", "role", "stage", "model", "prompt_version"} <= item.keys():
                try:
                    prior = StageResult.model_validate(item)
                except (ValidationError, TypeError, ValueError):
                    prior = None
                if prior is not None and not prior.synthetic:
                    urls.update(_source_urls(prior.citations, prior.search_actions))
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return urls


def _json_context(value: Any) -> Any:
    if isinstance(value, StageResult):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_context(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_context(item) for item in value]
    return value


class ResponsesProvider:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport

    async def run(self, role: str, stage: str, request: ResearchRequest, context: Any) -> StageResult:
        _check_inputs(role, stage, request)
        key = self._settings.api_key
        if not isinstance(key, str) or not key.strip():
            raise ProviderError("OPENAI_API_KEY is required for live research.")
        key = key.strip()
        try:
            prompt = build_prompt(role, stage, request, _json_context(context))
        except (TypeError, ValueError, RecursionError):
            raise ProviderError("Research context could not be serialized.") from None
        if key in prompt:
            raise ProviderError("Research input contains a configured credential.")
        payload = {
            "model": self._settings.model,
            "input": prompt,
            "tools": [{"type": "web_search"}],
            "include": ["web_search_call.action.sources"],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "ResearchArtifact",
                    "schema": ResearchArtifact.model_json_schema(),
                    "strict": False,
                }
            },
            "max_output_tokens": self._settings.max_output_tokens,
            "store": False,
        }
        if key in json.dumps(payload, ensure_ascii=False):
            raise ProviderError("Research input contains a configured credential.")
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(180.0, connect=15.0),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    RESPONSES_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    json=payload,
                )
        except httpx.TimeoutException:
            raise ProviderError("OpenAI request timed out; no retry was attempted.") from None
        except (httpx.HTTPError, ValueError):
            raise ProviderError("OpenAI request failed; no retry was attempted.") from None
        if not 200 <= response.status_code < 300:
            raise ProviderError(
                f"OpenAI request failed (HTTP {response.status_code}); no retry was attempted."
            )
        try:
            body = response.json()
        except (ValueError, UnicodeError, RecursionError):
            raise ProviderError("OpenAI returned an invalid response envelope.") from None
        if key in json.dumps(body, ensure_ascii=False):
            raise ProviderError("OpenAI response contained a configured credential.")
        return self._parse(body, role, stage, context)

    def _parse(self, body: Any, role: str, stage: str, context: Any) -> StageResult:
        if not isinstance(body, dict) or body.get("status") != "completed":
            raise ProviderError("OpenAI response was not completed.")
        if body.get("error") is not None or body.get("incomplete_details") is not None:
            raise ProviderError("OpenAI response reported an error or incomplete output.")
        if body.get("refusal"):
            raise ProviderError("OpenAI refused the research request.")
        output = body.get("output")
        if not isinstance(output, list) or not output:
            raise ProviderError("OpenAI response contained no research output.")
        text_parts, citations, actions = [], [], []
        for item in output:
            if not isinstance(item, dict):
                raise ProviderError("OpenAI returned an invalid output item.")
            if item.get("type") == "refusal" or item.get("refusal"):
                raise ProviderError("OpenAI refused the research request.")
            if item.get("type") == "web_search_call":
                if item.get("status") != "completed" or not isinstance(item.get("action"), dict):
                    raise ProviderError("OpenAI web search did not complete.")
                actions.append(item)
            elif item.get("type") == "message":
                if item.get("role") != "assistant" or item.get("status", "completed") != "completed":
                    raise ProviderError("OpenAI research message did not complete.")
                content = item.get("content")
                if not isinstance(content, list):
                    raise ProviderError("OpenAI returned invalid message content.")
                for part in content:
                    if not isinstance(part, dict):
                        raise ProviderError("OpenAI returned invalid message content.")
                    if part.get("type") == "refusal" or part.get("refusal"):
                        raise ProviderError("OpenAI refused the research request.")
                    if part.get("type") == "output_text":
                        if not isinstance(part.get("text"), str):
                            raise ProviderError("OpenAI returned invalid research text.")
                        annotations = part.get("annotations", [])
                        if not isinstance(annotations, list) or any(
                            not isinstance(annotation, dict) for annotation in annotations
                        ):
                            raise ProviderError("OpenAI returned invalid source annotations.")
                        text_parts.append(part["text"])
                        citations.extend(annotations)
        if not text_parts:
            raise ProviderError("OpenAI response contained no research text.")
        try:
            artifact = ResearchArtifact.model_validate_json("".join(text_parts))
        except (ValidationError, ValueError):
            raise ProviderError("OpenAI research output did not match the artifact schema.") from None
        supported = _source_urls(citations, actions) | _prior_urls(context)
        usable = [
            row for row in artifact.evidence if row.kind != "assumption" and row.access != "unavailable"
        ]
        if not usable or any(row.url not in supported for row in usable):
            raise ProviderError(
                "Research evidence is missing supporting provider citations or search sources."
            )
        source_ids = {row.source_id for row in artifact.evidence}
        for candidate in artifact.candidates:
            if candidate.price is not None and candidate.price_source_id not in source_ids:
                raise ProviderError("A candidate price is missing its evidence reference.")
            if any(source_id not in source_ids for source_id in candidate.financial_source_ids):
                raise ProviderError("Candidate financial evidence references are invalid.")
        usage = body.get("usage", {})
        model = body.get("model", self._settings.model)
        if not isinstance(usage, dict) or not isinstance(model, str) or not model:
            raise ProviderError("OpenAI returned invalid model or usage metadata.")
        return StageResult(
            role=role,
            stage=stage,
            artifact=artifact,
            citations=citations,
            search_actions=actions,
            usage=usage,
            model=model,
            prompt_version=PROMPT_VERSION,
            synthetic=False,
        )


class SyntheticProvider:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings

    async def run(self, role: str, stage: str, request: ResearchRequest, context: Any) -> StageResult:
        _check_inputs(role, stage, request)
        tickers = request.tickers or ["AAA", "BBB", "CCC"][: request.candidate_limit]
        evidence, candidates, citations = [], [], []
        at = request.as_of - timedelta(minutes=1)
        for index, ticker in enumerate(tickers):
            price = float(100 + 10 * index)
            source_id = f"synthetic-{ticker}"
            url = f"https://example.invalid/synthetic/{ticker}"
            evidence.append(
                Evidence(
                    source_id=source_id,
                    url=url,
                    title=f"SYNTHETIC fixture for {ticker}",
                    claim="SYNTHETIC test observation; all prices, financials and sources are fabricated fixtures.",
                    kind="observed",
                    authority="primary",
                    published_at=at,
                    event_at=at,
                    retrieved_at=request.as_of,
                    access="full_text",
                )
            )
            candidates.append(
                Candidate(
                    ticker=ticker,
                    thesis="SYNTHETIC DEMO ONLY: this is not researched investment advice.",
                    risks=["All values are fabricated fixture inputs and must not guide a trade."],
                    price=price,
                    price_at=at,
                    price_source_id=source_id,
                    financial_source_ids=[source_id],
                    scenarios=[
                        Scenario(
                            name=name,
                            years=years,
                            terminal_price=price * factor**years,
                            dividends_per_share=years,
                            starting_eps=price / 20,
                            terminal_eps=price * factor**years / 20,
                            exit_pe=20,
                            rationale="SYNTHETIC fixture growth and multiple; no estimated probability.",
                        )
                        for years in request.horizons_years
                        for name, factor in (("bear", 0.8), ("base", 1.07), ("bull", 1.15))
                    ],
                    valuation=Valuation(
                        cash_flow_type="FCFE",
                        cashflows=[10.0, 11.0, 12.0, 13.0, 14.0],
                        discount_rate=0.10,
                        terminal_growth=0.02,
                        diluted_shares=1.0,
                        units="SYNTHETIC USD and one synthetic share",
                        bridge_explanation="SYNTHETIC FCFE fixture, no enterprise-to-equity adjustment.",
                        reinvestment_explanation="SYNTHETIC cash after assumed reinvestment, not issuer data.",
                    ),
                )
            )
            citations.append({"type": "synthetic_fixture", "url": url, "title": f"SYNTHETIC {ticker}"})
        reviewed = (
            list(ROLES) if stage in ("cross_review", "fresh_audit", "study", "revision", "final") else []
        )
        if stage == "self_review" and role in ROLES:
            reviewed = [role]
        artifact = ResearchArtifact(
            narrative=f"SYNTHETIC DEMO: {role}/{stage}. No live API, search or market research was performed.",
            evidence=evidence,
            candidates=candidates,
            reviewed_roles=reviewed,
            recommendations=tickers[:5],
            limitations=[
                "SYNTHETIC=true: all financial values and example.invalid sources are fabricated test fixtures.",
                "Supplied symbols are labels only; this output contains no facts about their actual issuers.",
                "This demo exercises workflow plumbing, not research quality or forecast accuracy.",
            ],
        )
        return StageResult(
            role=role,
            stage=stage,
            artifact=artifact,
            citations=citations,
            search_actions=[],
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            model="synthetic-fixture-v1",
            prompt_version=PROMPT_VERSION,
            synthetic=True,
        )
