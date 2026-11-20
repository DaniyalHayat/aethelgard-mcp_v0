import copy
import json
import traceback
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from aethelgard_mcp.config import Settings
from aethelgard_mcp.contracts import ResearchArtifact, StageResult
from aethelgard_mcp.models import ResearchRequest
from aethelgard_mcp.prompts import PROMPT_VERSION, ROLES, STAGES
from aethelgard_mcp.provider import ProviderError, ResponsesProvider, SyntheticProvider

KEY = "sk-provider-test-secret-never-serialize"
SOURCE = "https://issuer.example/annual-report"
CUTOFF = datetime(2025, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def request_data():
    return ResearchRequest(tickers=["AAA"], as_of=CUTOFF)


def artifact_data():
    return {
        "narrative": f"See the [issuer report]({SOURCE}); future returns remain uncertain.",
        "evidence": [
            {
                "source_id": "issuer",
                "url": SOURCE,
                "title": "Issuer annual report",
                "claim": "The source supplies the observed test price.",
                "kind": "observed",
                "authority": "primary",
                "published_at": "2024-12-01T00:00:00Z",
                "retrieved_at": "2025-01-01T00:00:00Z",
                "access": "full_text",
            }
        ],
        "candidates": [
            {
                "ticker": "AAA",
                "thesis": "Test research candidate.",
                "risks": ["Uncertain future cash flows."],
                "price": 100,
                "price_at": "2024-12-31T21:00:00Z",
                "price_source_id": "issuer",
                "financial_source_ids": ["issuer"],
            }
        ],
        "recommendations": [],
    }


def response_data(artifact=None):
    return {
        "id": "resp_test",
        "status": "completed",
        "model": "test-model-snapshot",
        "usage": {"input_tokens": 123, "output_tokens": 456, "total_tokens": 579},
        "output": [
            {
                "type": "web_search_call",
                "id": "search_test",
                "status": "completed",
                "action": {
                    "type": "search",
                    "query": "AAA issuer annual report",
                    "sources": [{"type": "url", "url": SOURCE, "title": "Issuer annual report"}],
                },
            },
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(artifact if artifact is not None else artifact_data()),
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": SOURCE,
                                "title": "Issuer annual report",
                                "start_index": 1,
                                "end_index": 10,
                            }
                        ],
                    }
                ],
            },
        ],
    }


def mock_provider(body, status=200, key=KEY):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    return ResponsesProvider(Settings(api_key=key), httpx.MockTransport(handle)), calls


async def test_live_request_uses_one_fixed_endpoint_and_records_provenance(request_data):
    body = response_data()
    provider, calls = mock_provider(body)
    result = await provider.run("fundamental", "independent", request_data, {"note": "untrusted context"})
    assert len(calls) == 1
    call = calls[0]
    assert str(call.url) == "https://api.openai.com/v1/responses"
    assert call.method == "POST"
    assert call.headers["authorization"] == f"Bearer {KEY}"
    payload = json.loads(call.content)
    assert payload["tools"] == [{"type": "web_search"}]
    assert payload["include"] == ["web_search_call.action.sources"]
    assert payload["store"] is False
    assert payload["max_output_tokens"] == 6000
    assert payload["text"]["format"]["name"] == "ResearchArtifact"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["schema"] == ResearchArtifact.model_json_schema()
    assert payload["text"]["format"]["strict"] is False
    assert "untrusted context" in payload["input"]
    assert KEY not in call.content.decode()
    assert KEY not in result.model_dump_json()
    assert result.synthetic is False
    assert result.model == "test-model-snapshot"
    assert result.prompt_version == PROMPT_VERSION
    assert result.citations == body["output"][1]["content"][0]["annotations"]
    assert result.search_actions == [body["output"][0]]
    assert result.usage == body["usage"]


@pytest.mark.parametrize("key", ["", "   "])
async def test_missing_key_fails_without_network(key, request_data):
    provider, calls = mock_provider(response_data(), key=key)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        await provider.run("fundamental", "independent", request_data, {})
    assert calls == []


@pytest.mark.parametrize("status", [301, 401, 429, 500, 503])
async def test_http_failures_do_not_retry_or_expose_upstream_body(status, request_data):
    provider, calls = mock_provider({"error": {"message": KEY + " private body"}}, status=status)
    with pytest.raises(ProviderError) as caught:
        await provider.run("valuation", "independent", request_data, {})
    assert str(status) in str(caught.value)
    assert KEY not in "".join(traceback.format_exception(caught.value))
    assert "private body" not in str(caught.value)
    assert len(calls) == 1


async def test_redirect_is_not_followed(request_data):
    calls = []

    def redirect(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://attacker.example/collect"})

    provider = ResponsesProvider(Settings(api_key=KEY), httpx.MockTransport(redirect))
    with pytest.raises(ProviderError, match="HTTP 307"):
        await provider.run("fundamental", "independent", request_data, {})
    assert len(calls) == 1
    assert calls[0].url.host == "api.openai.com"


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError])
async def test_transport_errors_are_sanitized_without_retry(failure, request_data):
    calls = []

    def fail(request):
        calls.append(request)
        raise failure(KEY + " private transport detail", request=request)

    provider = ResponsesProvider(Settings(api_key=KEY), httpx.MockTransport(fail))
    with pytest.raises(ProviderError) as caught:
        await provider.run("challenge", "fresh_audit", request_data, {})
    assert len(calls) == 1
    assert KEY not in "".join(traceback.format_exception(caught.value))
    assert "private transport detail" not in str(caught.value)
    assert "no retry" in str(caught.value)


async def test_non_json_envelope_is_sanitized(request_data):
    provider = ResponsesProvider(
        Settings(api_key=KEY), httpx.MockTransport(lambda request: httpx.Response(200, text=KEY))
    )
    with pytest.raises(ProviderError, match="invalid response envelope") as caught:
        await provider.run("fundamental", "independent", request_data, {})
    assert KEY not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("status", [None, "incomplete", "failed", "in_progress", "queued", "cancelled"])
async def test_only_completed_envelopes_are_accepted(status, request_data):
    body = response_data()
    body["status"] = status
    provider, calls = mock_provider(body)
    with pytest.raises(ProviderError, match="not completed"):
        await provider.run("fundamental", "independent", request_data, {})
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["error", "incomplete_details"])
async def test_completed_envelope_cannot_hide_an_error(field, request_data):
    body = response_data()
    body[field] = {"reason": "upstream failure"}
    provider, _ = mock_provider(body)
    with pytest.raises(ProviderError, match="error or incomplete"):
        await provider.run("fundamental", "independent", request_data, {})


async def test_refusal_rejects_even_when_other_text_is_valid(request_data):
    body = response_data()
    body["output"][1]["content"].append({"type": "refusal", "refusal": "Private refusal detail"})
    provider, _ = mock_provider(body)
    with pytest.raises(ProviderError, match="refused") as caught:
        await provider.run("fundamental", "independent", request_data, {})
    assert "Private refusal detail" not in str(caught.value)


@pytest.mark.parametrize("kind", ["extra_field", "missing_narrative", "bad_price", "duplicate_evidence"])
async def test_invalid_artifact_schema_fails_closed(kind, request_data):
    artifact = artifact_data()
    if kind == "extra_field":
        artifact["not_in_schema"] = "private schema detail"
    elif kind == "missing_narrative":
        del artifact["narrative"]
    elif kind == "bad_price":
        artifact["candidates"][0]["price"] = -1
    else:
        artifact["evidence"].append(copy.deepcopy(artifact["evidence"][0]))
    provider, calls = mock_provider(response_data(artifact))
    with pytest.raises(ProviderError, match="artifact schema") as caught:
        await provider.run("valuation", "revision", request_data, {})
    assert "private schema detail" not in "".join(traceback.format_exception(caught.value))
    assert len(calls) == 1


@pytest.mark.parametrize("text", ["not JSON", "{}{}", '```json\n{"narrative":"x"}\n```'])
async def test_invalid_json_text_is_not_repaired_or_retried(text, request_data):
    body = response_data()
    body["output"][1]["content"][0]["text"] = text
    provider, calls = mock_provider(body)
    with pytest.raises(ProviderError, match="artifact schema"):
        await provider.run("fundamental", "independent", request_data, {})
    assert len(calls) == 1


async def test_multiple_text_parts_are_combined_without_losing_annotations(request_data):
    body = response_data()
    content = body["output"][1]["content"]
    text = content[0]["text"]
    middle = len(text) // 2
    content[0]["text"] = text[:middle]
    content.append({"type": "output_text", "text": text[middle:], "annotations": []})
    provider, _ = mock_provider(body)
    result = await provider.run("valuation", "independent", request_data, {})
    assert result.artifact.candidates[0].ticker == "AAA"
    assert len(result.citations) == 1


@pytest.mark.parametrize("source_kind", ["annotations", "search_sources", "open_page"])
async def test_each_provider_source_form_can_support_evidence(source_kind, request_data):
    body = response_data()
    if source_kind == "annotations":
        body["output"].pop(0)
    else:
        body["output"][1]["content"][0]["annotations"] = []
        if source_kind == "open_page":
            body["output"][0]["action"] = {"type": "open_page", "url": SOURCE}
    provider, _ = mock_provider(body)
    result = await provider.run("fundamental", "independent", request_data, {})
    assert result.artifact.evidence[0].url == SOURCE
    if source_kind != "annotations":
        assert result.citations == []
        assert len(result.search_actions) == 1


@pytest.mark.parametrize("kind", ["no_evidence", "no_sources", "unbacked_url", "only_assumptions"])
async def test_missing_or_unsupported_citations_fail(kind, request_data):
    artifact = artifact_data()
    if kind == "no_evidence":
        artifact["evidence"] = []
    elif kind == "unbacked_url":
        artifact["evidence"][0]["url"] = "https://unverified.example/report"
    elif kind == "only_assumptions":
        artifact["evidence"][0]["kind"] = "assumption"
    body = response_data(artifact)
    if kind == "no_sources":
        body["output"].pop(0)
        body["output"][0]["content"][0]["annotations"] = []
    provider, _ = mock_provider(body)
    with pytest.raises(ProviderError, match="supporting provider citations"):
        await provider.run("challenge", "independent", request_data, {})


@pytest.mark.parametrize("as_dict", [True, False])
async def test_prior_stage_provider_metadata_can_support_reused_sources(as_dict, request_data):
    provider, _ = mock_provider(response_data())
    prior = await provider.run("fundamental", "independent", request_data, {})
    body = response_data()
    body["output"].pop(0)
    body["output"][0]["content"][0]["annotations"] = []
    provider, calls = mock_provider(body)
    context = {"prior": [prior.model_dump(mode="json") if as_dict else prior]}
    result = await provider.run("valuation", "cross_review", request_data, context)
    assert result.artifact.evidence[0].url == SOURCE
    assert len(calls) == 1
    assert result.citations == []


@pytest.mark.parametrize("context_kind", ["bare_artifact", "synthetic_stage"])
async def test_model_ledgers_and_synthetic_prior_results_cannot_launder_sources(context_kind, request_data):
    body = response_data()
    body["output"].pop(0)
    body["output"][0]["content"][0]["annotations"] = []
    context = artifact_data()
    if context_kind == "synthetic_stage":
        context = StageResult(
            role="fundamental",
            stage="independent",
            artifact=ResearchArtifact.model_validate(artifact_data()),
            citations=[{"type": "url_citation", "url": SOURCE}],
            model="synthetic",
            prompt_version=PROMPT_VERSION,
            synthetic=True,
        )
    provider, _ = mock_provider(body)
    with pytest.raises(ProviderError, match="supporting provider citations"):
        await provider.run("challenge", "cross_review", request_data, context)


async def test_study_can_record_later_papers_without_provider_claiming_cutoff_eligibility(request_data):
    artifact = artifact_data()
    artifact["candidates"] = []
    artifact["evidence"][0]["published_at"] = (CUTOFF + timedelta(days=30)).isoformat()
    provider, _ = mock_provider(response_data(artifact))
    result = await provider.run("valuation", "study", request_data, {})
    assert result.artifact.evidence[0].cutoff_status(request_data.as_of) == "after_cutoff"


@pytest.mark.parametrize("field", ["price_source_id", "financial_source_ids"])
async def test_dangling_candidate_evidence_references_fail(field, request_data):
    artifact = artifact_data()
    artifact["candidates"][0][field] = "missing" if field == "price_source_id" else ["missing"]
    provider, _ = mock_provider(response_data(artifact))
    with pytest.raises(ProviderError, match="evidence reference"):
        await provider.run("fundamental", "independent", request_data, {})


async def test_incomplete_search_is_not_accepted_as_completed_research(request_data):
    body = response_data()
    body["output"][0]["status"] = "in_progress"
    provider, _ = mock_provider(body)
    with pytest.raises(ProviderError, match="web search did not complete"):
        await provider.run("fundamental", "independent", request_data, {})


@pytest.mark.parametrize("kind", ["empty", "bad_item", "bad_content", "bad_annotations", "bad_usage"])
async def test_malformed_envelope_shapes_fail_as_sanitized_provider_errors(kind, request_data):
    body = response_data()
    if kind == "empty":
        body["output"] = []
    elif kind == "bad_item":
        body["output"].append("private detail")
    elif kind == "bad_content":
        body["output"][1]["content"] = None
    elif kind == "bad_annotations":
        body["output"][1]["content"][0]["annotations"] = ["private detail"]
    else:
        body["usage"] = "private detail"
    provider, _ = mock_provider(body)
    with pytest.raises(ProviderError) as caught:
        await provider.run("fundamental", "independent", request_data, {})
    assert "private detail" not in str(caught.value)


async def test_top_level_refusal_output_is_rejected(request_data):
    body = response_data()
    body["output"].append({"type": "refusal", "refusal": "private refusal"})
    provider, _ = mock_provider(body)
    with pytest.raises(ProviderError, match="refused"):
        await provider.run("fundamental", "independent", request_data, {})


async def test_credential_in_context_is_rejected_before_network(request_data):
    provider, calls = mock_provider(response_data())
    with pytest.raises(ProviderError, match="configured credential"):
        await provider.run("fundamental", "independent", request_data, {"accidental_secret": KEY})
    assert calls == []


async def test_credential_accidentally_configured_as_model_is_not_sent(request_data):
    def no_network(request):
        pytest.fail("A configured credential was sent in the request body")

    provider = ResponsesProvider(Settings(api_key=KEY, model=KEY), httpx.MockTransport(no_network))
    with pytest.raises(ProviderError, match="configured credential"):
        await provider.run("fundamental", "independent", request_data, {})


async def test_unserializable_context_has_no_network_call(request_data):
    provider, calls = mock_provider(response_data())
    context = {}
    context["cycle"] = context
    with pytest.raises(ProviderError, match="could not be serialized"):
        await provider.run("fundamental", "independent", request_data, context)
    assert calls == []


async def test_credential_echo_is_never_serialized(request_data):
    body = response_data()
    body["usage"]["accidental_secret"] = KEY
    provider, _ = mock_provider(body)
    with pytest.raises(ProviderError, match="configured credential") as caught:
        await provider.run("fundamental", "independent", request_data, {})
    assert KEY not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("role,stage", [("unknown", "independent"), ("fundamental", "unknown")])
async def test_invalid_workflow_selection_has_no_network_call(role, stage, request_data):
    provider, calls = mock_provider(response_data())
    with pytest.raises(ProviderError, match="Invalid research"):
        await provider.run(role, stage, request_data, {})
    assert calls == []


@pytest.mark.parametrize("stage", list(STAGES))
async def test_synthetic_provider_completes_each_stage_without_network(stage):
    def no_network(request):
        pytest.fail("Synthetic provider attempted network access")

    provider = SyntheticProvider(Settings(demo=True), httpx.MockTransport(no_network))
    request = ResearchRequest(as_of=CUTOFF)
    result = await provider.run("fundamental", stage, request, {})
    repeated = await provider.run("fundamental", stage, request, {})
    assert result.model_dump(mode="json") == repeated.model_dump(mode="json")
    assert result.synthetic is True
    assert result.model == "synthetic-fixture-v1"
    assert result.prompt_version == PROMPT_VERSION
    assert result.usage["total_tokens"] == 0
    assert result.search_actions == []
    assert "SYNTHETIC" in result.artifact.narrative
    assert [candidate.ticker for candidate in result.artifact.candidates] == ["AAA", "BBB", "CCC"]
    assert all(row.url.startswith("https://example.invalid/") for row in result.artifact.evidence)
    assert all("SYNTHETIC" in row.claim for row in result.artifact.evidence)
    if stage in ("cross_review", "fresh_audit"):
        assert result.artifact.reviewed_roles == list(ROLES)


async def test_synthetic_provider_honors_all_supplied_symbols_and_horizons():
    request = ResearchRequest(tickers=["ZZZ", "YYY", "XXX"], candidate_limit=1, horizons_years=[0.5, 4.6])
    result = await SyntheticProvider().run("orchestrator", "final", request, {})
    assert [candidate.ticker for candidate in result.artifact.candidates] == request.tickers
    assert result.artifact.recommendations == request.tickers
    for candidate in result.artifact.candidates:
        assert len(candidate.scenarios) == 6
        assert {case.years for case in candidate.scenarios} == {0.5, 4.6}
        assert candidate.valuation is not None


async def test_synthetic_discovery_respects_candidate_limit():
    request = ResearchRequest(candidate_limit=1, as_of=CUTOFF)
    result = await SyntheticProvider().run("challenge", "independent", request, {})
    assert [candidate.ticker for candidate in result.artifact.candidates] == ["AAA"]
