from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from aethelgard_mcp.calculators import (
    enterprise_dcf,
    incremental_roic,
    owner_cash_dcf,
    portfolio_return,
    return_attribution,
    reverse_growth,
    treasury_return,
)
from aethelgard_mcp.models import Evidence, ResearchRequest


def test_request_defaults_and_ticker_normalization():
    assert ResearchRequest().mode == "market"
    request = ResearchRequest(tickers=[" nvda ", "V", "NVDA"])
    assert request.tickers == ["NVDA", "V"]
    assert request.mode == "compare"


@pytest.mark.parametrize(
    "data",
    [
        {"tickers": ["https://example.com"]},
        {"tickers": ["$(command)"]},
        {"budget_per_horizon": float("nan")},
        {"horizons_years": [0]},
        {"mode": "compare"},
        {"as_of": datetime.now()},
        {"as_of": datetime.now(timezone.utc) + timedelta(days=2)},
    ],
)
def test_invalid_requests_fail(data):
    with pytest.raises(ValidationError):
        ResearchRequest(**data)


def test_publication_date_is_separate_from_event_date():
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    evidence = Evidence(
        source_id="a",
        url="https://example.com",
        title="Example",
        claim="Test",
        kind="observed",
        authority="primary",
        event_at=cutoff - timedelta(days=10),
        published_at=cutoff + timedelta(days=1),
    )
    assert evidence.cutoff_status(cutoff) == "after_cutoff"


def test_return_decomposition_reconciles_without_hiding_interaction():
    result = return_attribution(100, 5, 6, 25)
    assert result["price_return"] == pytest.approx(0.5)
    assert result["earnings_growth"] == pytest.approx(0.2)
    assert result["multiple_change"] == pytest.approx(0.25)
    assert result["interaction"] == pytest.approx(0.05)
    assert result["unchanged_multiple_price"] == pytest.approx(120)


def test_flat_perpetuity_and_enterprise_bridge():
    assert owner_cash_dcf([10] * 5, 0.1, 0)["value"] == pytest.approx(100)
    assert enterprise_dcf([10] * 5, 0.1, 0, 20, 10)["per_share"] == pytest.approx(8)
    assert reverse_growth(100, 10, 5, 0.1, 0)["implied_growth"] == pytest.approx(0, abs=1e-12)


def test_dcf_rejects_infinite_terminal_value():
    with pytest.raises(ValueError):
        owner_cash_dcf([10], 0.03, 0.03)
    assert incremental_roic(10, 20, 100, 90)["incremental_roic"] is None


def test_treasury_carry_and_rate_shock_are_separate():
    flat = treasury_return(160, 59, 0.0389, 0.11)
    shock = treasury_return(160, 59, 0.0389, 0.11, 0.005)
    assert flat["profit"] == pytest.approx(160 * 0.0389 * 59 / 365 - 0.016)
    assert shock["profit"] - flat["profit"] == pytest.approx(-0.088)


def test_tax_nets_mixed_gains_and_losses_at_portfolio_level():
    rows = [
        dict(amount=80, entry_price=100, terminal_price=120, dividends_per_share=0),
        dict(amount=80, entry_price=100, terminal_price=80, dividends_per_share=0),
    ]
    result = portfolio_return(rows, 1.4, roundtrip_cost=0)
    assert result["tax"] == pytest.approx(0)
    assert result["profit"] == pytest.approx(0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
def test_financial_functions_reject_nonfinite_and_boolean_numbers(bad):
    with pytest.raises(ValueError):
        return_attribution(bad, 5, 6, 20)
