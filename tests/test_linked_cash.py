import math

import pytest

from aethelgard_mcp.calculators import funded_terminal_cash, funding_path, operating_cash_bridge


def test_bridge_reconciles_common_cash_and_does_not_ignore_financing():
    result = operating_cash_bridge(
        revenue=100, operating_margin=.3, tax_rate=.2, diluted_shares=10,
        depreciation=3, capex=8, working_capital_increase=2, investment_cash=4,
        guarantee_calls=1, cash_tax_timing=2, interest_expense=5, cash_interest_income=1,
        minority_cash=1, preferred_cash=.5, debt_issued=6, debt_principal=3, equipment_principal=1,
    )
    assert result["nopat"] == 24
    assert result["fcff"] == 10
    assert result["fcfe"] == pytest.approx(7.3)
    assert result["cash_equivalent_earnings_per_share"] == pytest.approx(1.93)
    assert "eps" not in result
    assert result["direct_fcfe"] == pytest.approx(result["fcfe"])


def test_loss_does_not_create_unassumed_tax_refund():
    inputs = dict(revenue=100, operating_margin=-.1, tax_rate=.2, diluted_shares=10, interest_expense=2)
    assert operating_cash_bridge(**inputs)["fcfe"] == -12
    assert operating_cash_bridge(**inputs, recognize_loss_tax_benefit=True)["fcfe"] == pytest.approx(-9.6)


def test_interest_deduction_cannot_create_refund_when_it_crosses_zero_income():
    result = operating_cash_bridge(100, .02, .2, 10, interest_expense=4)
    assert result["fcff"] == 1.6
    assert result["fcfe"] == pytest.approx(-2)
    assert result["net_financing_after_tax"] == pytest.approx(3.6)


@pytest.mark.parametrize("changes", [{"capex": -1}, {"diluted_shares": 0}, {"revenue": math.inf}, {"operating_margin": 1.1}, {"tax_rate": 2}, {"debt_issued": True}])
def test_invalid_bridge_inputs_fail(changes):
    inputs = dict(revenue=100, operating_margin=.2, tax_rate=.2, diluted_shares=10)
    with pytest.raises(ValueError):
        operating_cash_bridge(**(inputs | changes))


def test_terminal_growth_uses_greater_investment_without_double_counting():
    result = funded_terminal_cash(100, .03, .15, investment_floor=30, financing_after_tax=5, common_cash_claims=1)
    assert result["growth_reinvestment"] == 20
    assert result["fcff"] == 70
    assert result["fcfe_before_net_borrowing"] == 64
    assert funded_terminal_cash(100, .03, .10)["fcff"] / (.10 - .03) == pytest.approx(100 / .10)


def test_funding_gap_does_not_disappear_through_an_automatic_loan():
    result = funding_path(5, [-4, -2, 8], [1, 1, 1], [0, 1, 0])
    assert [r["cash"] for r in result["periods"]] == [0, -4, 3]
    assert result["maximum_funding_shortfall"] == 4
    with pytest.raises(ValueError):
        funding_path(5, [1, 2], [1], [0, 0])
