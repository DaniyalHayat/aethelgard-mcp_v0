import pytest

from aethelgard_mcp.calculators import shareholder_irr, technical_context


def test_dated_irr_includes_dividend_timing():
    result = shareholder_irr(["2025-01-01", "2026-01-01", "2027-01-01"], [-100, 10, 110])
    assert result["annual_irr"] == pytest.approx(0.10)
    assert abs(result["npv_residual"]) < 1e-9


def test_irr_loss_and_invalid_sign_changes():
    assert shareholder_irr(["2025-01-01", "2026-01-01"], [-100, 50])["annual_irr"] == pytest.approx(-0.5)
    with pytest.raises(ValueError):
        shareholder_irr(["2025-01-01", "2026-01-01", "2027-01-01"], [-100, 230, -132])
    with pytest.raises(ValueError):
        shareholder_irr(["2025-01-01", "2025-01-01"], [-100, 110])


def test_technicals_constant_series_and_missing_history():
    result = technical_context([100.0] * 253)
    assert result["rsi14_wilder"] == 50
    assert result["annualized_log_volatility"] == 0
    assert result["max_drawdown_full_input"] == 0
    assert result["momentum_12_minus_1"] == 0
    assert result["sma"]["200"] == 100
    short = technical_context([100, 50, 75])
    assert short["max_drawdown_full_input"] == -0.5
    assert short["sma"]["20"] is None
    assert short["rsi14_wilder"] is None


def test_wilder_monotone_extremes_and_invalid_prices():
    assert technical_context(list(range(1, 30)))["rsi14_wilder"] == 100
    assert technical_context(list(range(30, 1, -1)))["rsi14_wilder"] == 0
    with pytest.raises(ValueError):
        technical_context([100, 0, 50])
