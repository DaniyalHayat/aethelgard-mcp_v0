from datetime import datetime, timezone

import httpx
import pytest

from aethelgard_mcp.data_sources import DataSourceError, PublicData

CUTOFF = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)


async def test_sec_filters_by_acceptance_not_period_end(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test test@example.invalid")

    def handler(request):
        assert request.url.host == "data.sec.gov"
        return httpx.Response(
            200,
            json={
                "name": "Synthetic",
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000000001-26-000001", "0000000001-26-000002"],
                        "acceptanceDateTime": ["2026-01-05T20:00:00Z", "2026-01-06T13:00:00Z"],
                        "primaryDocument": ["annual.htm", "quarter.htm"],
                        "form": ["10-K", "10-Q"],
                        "filingDate": ["2026-01-05", "2026-01-06"],
                        "reportDate": ["2025-10-31", "2025-10-31"],
                    }
                },
            },
        )

    result = await PublicData(httpx.MockTransport(handler)).sec_filings("1", CUTOFF)
    assert len(result["filings"]) == 1
    assert result["filings"][0]["form"] == "10-K"


async def test_sec_identity_and_key_requirements(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        await PublicData().sec_filings("1", CUTOFF)
    with pytest.raises(ValueError, match="CIK"):
        await PublicData().sec_filings("../1", CUTOFF)


@pytest.fixture
def market_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "fixture-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "fixture-secret")


async def test_bar_pagination_and_partial_day_exclusion(market_keys):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["APCA-API-KEY-ID"] == "fixture-key"
        assert request.url.params["adjustment"] == "all"
        assert request.url.params["feed"] == "iex"
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={"bars": {"AAA": [{"t": "2026-01-02T05:00:00Z", "c": 100}]}, "next_page_token": "next"},
            )
        assert request.url.params["page_token"] == "next"
        return httpx.Response(
            200,
            json={
                "bars": {
                    "AAA": [{"t": "2026-01-05T05:00:00Z", "c": 101}, {"t": "2026-01-06T05:00:00Z", "c": 999}]
                }
            },
        )

    result = await PublicData(httpx.MockTransport(handler)).stock_history(["AAA"], CUTOFF)
    assert len(calls) == 2
    assert len(result["symbols"]["AAA"]["bars"]) == 2
    assert result["symbols"]["AAA"]["technical_context"]["last_adjusted_close"] == 101


async def test_pagination_cap_fails_instead_of_publishing_partial_history(market_keys):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"bars": {"AAA": []}, "next_page_token": "remaining"})
    )
    with pytest.raises(DataSourceError, match="page budget"):
        await PublicData(transport).stock_history(["AAA"], CUTOFF, max_pages=1)


async def test_errors_do_not_echo_keys_or_provider_body(market_keys):
    transport = httpx.MockTransport(lambda request: httpx.Response(403, text="fixture-secret denied"))
    with pytest.raises(DataSourceError) as error:
        await PublicData(transport).stock_history(["AAA"], CUTOFF)
    assert "fixture-secret" not in str(error.value)


async def test_missing_market_keys_and_empty_symbols(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="ALPACA"):
        await PublicData().stock_history(["AAA"], CUTOFF)
    with pytest.raises(ValueError, match="ticker"):
        await PublicData().stock_history([], CUTOFF)
