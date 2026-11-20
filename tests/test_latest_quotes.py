from datetime import datetime, timedelta, timezone

import httpx
import pytest
from mcp import Client

from aethelgard_mcp.config import Settings
from aethelgard_mcp.data_sources import DataSourceError, PublicData
from aethelgard_mcp.server import create_server


@pytest.fixture(autouse=True)
def market_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "quote-fixture-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "quote-fixture-secret")


def quote(**changes):
    return {"bp": 100, "ap": 100.2, "bs": 2, "as": 1, "bx": "V", "ax": "V",
            "t": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(), **changes}


def source(payload):
    return PublicData(httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))


async def test_latest_quote_preserves_timestamp_feed_and_market_fields():
    fixture = quote()

    def handler(request):
        assert str(request.url).startswith("https://data.alpaca.markets/v2/stocks/quotes/latest?")
        assert dict(request.url.params) == {"symbols": "AAA", "feed": "iex", "currency": "USD"}
        assert request.headers["APCA-API-KEY-ID"] == "quote-fixture-key"
        return httpx.Response(200, json={"quotes": {"AAA": fixture}})

    result = await PublicData(httpx.MockTransport(handler)).latest_quotes([" aaa "])
    row = result["symbols"]["AAA"]
    assert result["status"] == "complete"
    assert row["quoted_at"] == fixture["t"]
    assert row["bid_size"] == 2 and row["ask_size"] == 1
    assert row["spread"] == pytest.approx(.2)
    assert row["midpoint"] == pytest.approx(100.1)
    assert 9 <= row["age_seconds"] < 60
    assert not row["older_than_60_seconds"]


async def test_missing_symbol_and_invalid_quote_do_not_hide_valid_symbol():
    result = await source({"quotes": {"AAA": quote(), "BBB": quote(bp=0)}}).latest_quotes(["AAA", "BBB", "CCC"])
    assert result["status"] == "partial"
    assert set(result["symbols"]) == {"AAA"}
    assert set(result["errors"]) == {"BBB", "CCC"}


@pytest.mark.parametrize("changes", [
    {"bp": 0}, {"ap": 0}, {"bp": 101}, {"bs": -1}, {"bp": True},
    {"ap": "100.2"}, {"bs": 10 ** 400}, {"t": "2026-01-01T12:00:00"}, {"t": "secret-provider-body"},
    {"t": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}, {"bx": "https://example.invalid"},
])
async def test_invalid_quotes_are_withheld(changes):
    result = await source({"quotes": {"AAA": quote(**changes)}}).latest_quotes(["AAA"])
    assert result["status"] == "unavailable"
    assert result["symbols"] == {}
    assert "secret-provider-body" not in str(result)


async def test_nonfinite_quote_is_withheld():
    body = '{"quotes":{"AAA":{"bp":NaN,"ap":100,"bs":1,"as":1,"bx":"V","ax":"V","t":"2026-01-01T12:00:00Z"}}}'
    data = PublicData(httpx.MockTransport(lambda request: httpx.Response(200, text=body)))
    result = await data.latest_quotes(["AAA"])
    assert result["status"] == "unavailable"
    assert "finite" in result["errors"]["AAA"]


async def test_stale_and_small_clock_skew_are_explicit():
    old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    ahead = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
    result = await source({"quotes": {"AAA": quote(t=old), "BBB": quote(t=ahead)}}).latest_quotes(["AAA", "BBB"], "delayed_sip")
    assert result["symbols"]["AAA"]["older_than_60_seconds"]
    assert result["symbols"]["BBB"]["within_clock_skew_tolerance"]
    assert "15 minutes" in result["limitations"]


@pytest.mark.parametrize("payload", [{}, {"quotes": []}, {"quotes": {"WRONG": {}}}])
async def test_invalid_response_or_unexpected_coverage_fails(payload):
    with pytest.raises(DataSourceError):
        await source(payload).latest_quotes(["AAA"])


async def test_error_response_does_not_expose_secret():
    data = PublicData(httpx.MockTransport(lambda request: httpx.Response(403, text="quote-fixture-secret")))
    with pytest.raises(DataSourceError) as error:
        await data.latest_quotes(["AAA"])
    assert "quote-fixture-secret" not in str(error.value)


async def test_required_credentials_and_input_validation(monkeypatch):
    with pytest.raises(ValueError, match="ticker"):
        await PublicData().latest_quotes([])
    with pytest.raises(ValueError, match="Feed"):
        await PublicData().latest_quotes(["AAA"], "unknown")
    monkeypatch.delenv("ALPACA_API_KEY")
    with pytest.raises(ValueError, match="ALPACA"):
        await PublicData().latest_quotes(["AAA"])


async def test_quote_tool_is_exposed_over_mcp(monkeypatch, tmp_path):
    async def latest(self, tickers, feed):
        assert tickers == ["AAA"] and feed == "iex"
        return {"status": "complete", "symbols": {"AAA": {"bid_price": 100, "ask_price": 101}}}

    monkeypatch.setattr(PublicData, "latest_quotes", latest)
    async with Client(create_server(Settings(demo=True, run_dir=tmp_path))) as client:
        result = await client.call_tool("latest_stock_quotes", {"tickers": ["AAA"]})
        assert not result.is_error
        assert result.structured_content["symbols"]["AAA"]["ask_price"] == 101
