"""Deterministic scenarios; none of these functions predicts an outcome."""

import math
from datetime import date
from statistics import stdev
from typing import Any


def finite(**values):
    if any(isinstance(v, bool) or not math.isfinite(v) for v in values.values()):
        raise ValueError("All numeric inputs must be finite numbers")


def positive(**values):
    finite(**values)
    if any(v <= 0 for v in values.values()):
        raise ValueError("These inputs must be positive: " + ", ".join(values))


def return_attribution(
    price: float, starting_eps: float, terminal_eps: float, exit_pe: float
) -> dict[str, Any]:
    positive(price=price, starting_eps=starting_eps, exit_pe=exit_pe)
    finite(terminal_eps=terminal_eps)
    if terminal_eps < 0:
        raise ValueError("P/E attribution requires nonnegative terminal EPS")
    earnings = terminal_eps / starting_eps - 1
    rerating = exit_pe / (price / starting_eps) - 1
    interaction = earnings * rerating
    return {
        "starting_pe": price / starting_eps,
        "terminal_price": terminal_eps * exit_pe,
        "earnings_growth": earnings,
        "multiple_change": rerating,
        "interaction": interaction,
        "price_return": earnings + rerating + interaction,
        "unchanged_multiple_price": terminal_eps * price / starting_eps,
    }


def owner_cash_dcf(cashflows: list[float], discount_rate: float, terminal_growth: float) -> dict[str, Any]:
    if not cashflows:
        raise ValueError("At least one cash flow is required")
    finite(
        discount_rate=discount_rate,
        terminal_growth=terminal_growth,
        **{str(i): v for i, v in enumerate(cashflows)},
    )
    if discount_rate <= terminal_growth or discount_rate <= 0 or terminal_growth <= -1:
        raise ValueError("Require discount rate > terminal growth > -1 and discount rate > 0")
    if cashflows[-1] <= 0:
        raise ValueError("A perpetuity requires a positive normalized terminal cash flow")
    present = sum(cash / (1 + discount_rate) ** (i + 1) for i, cash in enumerate(cashflows))
    terminal = cashflows[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
    terminal_pv = terminal / (1 + discount_rate) ** len(cashflows)
    value = present + terminal_pv
    return {
        "value": value,
        "explicit_pv": present,
        "terminal_pv": terminal_pv,
        "terminal_share": terminal_pv / value if value else None,
    }


def enterprise_dcf(
    fcffs: list[float], wacc: float, terminal_growth: float, net_debt: float, diluted_shares: float
) -> dict[str, Any]:
    positive(diluted_shares=diluted_shares)
    finite(net_debt=net_debt)
    result = owner_cash_dcf(fcffs, wacc, terminal_growth)
    equity = result["value"] - net_debt
    return {
        **result,
        "enterprise_value": result["value"],
        "net_debt": net_debt,
        "equity_value": equity,
        "per_share": equity / diluted_shares,
        "claim_warning": "Net debt must include only claims consistent with projected cash-flow treatment.",
    }


def reverse_growth(
    target_value: float, starting_cash: float, years: int, discount_rate: float, terminal_growth: float
) -> dict[str, Any]:
    positive(target_value=target_value, starting_cash=starting_cash)
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 50:
        raise ValueError("years must be an integer from 1 to 50")

    def value(growth):
        flows = [starting_cash * (1 + growth) ** (i + 1) for i in range(years)]
        return owner_cash_dcf(flows, discount_rate, terminal_growth)["value"]

    low, high = -0.95, 2.0
    if not value(low) <= target_value <= value(high):
        raise ValueError("No solution within -95% to +200% annual growth")
    for _ in range(120):
        mid = (low + high) / 2
        if value(mid) < target_value:
            low = mid
        else:
            high = mid
    growth = (low + high) / 2
    return {
        "implied_growth": growth,
        "reconciled_value": value(growth),
        "meaning": "Growth that prices the assumed cash-flow model, not a forecast.",
    }


def incremental_roic(
    nopat_before: float, nopat_after: float, capital_before: float, capital_after: float
) -> dict[str, Any]:
    finite(
        nopat_before=nopat_before,
        nopat_after=nopat_after,
        capital_before=capital_before,
        capital_after=capital_after,
    )
    change = capital_after - capital_before
    return {
        "incremental_nopat": nopat_after - nopat_before,
        "incremental_capital": change,
        "incremental_roic": (nopat_after - nopat_before) / change if change > 0 else None,
        "status": "defined" if change > 0 else "not_meaningful_nonpositive_incremental_capital",
    }


def treasury_return(
    capital: float,
    days: int,
    net_sec_yield: float,
    duration: float,
    yield_change: float = 0,
    roundtrip_spread: float = 0.0001,
    ordinary_tax_rate: float = 0.24,
) -> dict[str, Any]:
    positive(capital=capital)
    finite(
        net_sec_yield=net_sec_yield,
        duration=duration,
        yield_change=yield_change,
        roundtrip_spread=roundtrip_spread,
        ordinary_tax_rate=ordinary_tax_rate,
    )
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("days must be a positive integer")
    if duration < 0 or not 0 <= roundtrip_spread < 1 or not 0 <= ordinary_tax_rate <= 1:
        raise ValueError("Invalid duration, spread or tax rate")
    carry = capital * net_sec_yield * days / 365
    price = -capital * duration * yield_change
    cost = capital * roundtrip_spread
    tax = max(carry, 0) * ordinary_tax_rate + max(price - cost, 0) * ordinary_tax_rate
    profit = carry + price - cost
    return {
        "carry": carry,
        "price_change": price,
        "execution_cost": cost,
        "profit": profit,
        "ending_wealth": capital + profit,
        "illustrative_after_tax_profit": profit - tax,
        "convention": "SEC yield is net of expenses; distributions are included in carry. Linear duration only; resets, convexity and curve changes excluded.",
    }


def portfolio_return(
    positions: list[dict],
    years: float,
    capital_tax_rate: float = 0.15,
    dividend_tax_rate: float = 0.15,
    roundtrip_cost: float = 0.001,
) -> dict[str, Any]:
    positive(years=years)
    finite(
        capital_tax_rate=capital_tax_rate, dividend_tax_rate=dividend_tax_rate, roundtrip_cost=roundtrip_cost
    )
    if not positions or any(not 0 <= x <= 1 for x in (capital_tax_rate, dividend_tax_rate, roundtrip_cost)):
        raise ValueError("Provide positions and valid tax/cost fractions")
    principal = gains = income = 0.0
    for row in positions:
        amount, entry, terminal, dividends = (
            row[key] for key in ("amount", "entry_price", "terminal_price", "dividends_per_share")
        )
        positive(amount=amount, entry_price=entry)
        finite(terminal_price=terminal, dividends_per_share=dividends)
        if terminal < 0 or dividends < 0:
            raise ValueError("Terminal price and dividends cannot be negative")
        principal += amount
        gains += amount * (terminal / entry - 1 - roundtrip_cost)
        income += amount / entry * dividends
    profit = gains + income
    tax = max(gains, 0) * capital_tax_rate + income * dividend_tax_rate
    ending = principal + profit
    return {
        "principal": principal,
        "capital_gain_after_costs": gains,
        "income": income,
        "profit": profit,
        "ending_wealth": ending,
        "tax": tax,
        "after_tax_profit": profit - tax,
        "holding_period_return": profit / principal,
        "annualized_terminal_wealth_return": (ending / principal) ** (1 / years) - 1 if ending >= 0 else None,
        "convention": "Dividends retained as cash; terminal-wealth CAGR is not a dated shareholder IRR. Gains netted across positions; no immediate net-loss tax credit.",
    }


def shareholder_irr(dates: list[str], cashflows: list[float]) -> dict[str, Any]:
    """Dated annual IRR for one investment followed only by nonnegative receipts."""
    if len(dates) != len(cashflows) or len(dates) < 2:
        raise ValueError("Provide matching dates and cash flows, including purchase and exit")
    parsed = [date.fromisoformat(value) for value in dates]
    finite(**{str(i): cash for i, cash in enumerate(cashflows)})
    if any(a >= b for a, b in zip(parsed, parsed[1:])):
        raise ValueError("Dates must be strictly increasing; combine same-day cash flows")
    if cashflows[0] >= 0 or any(cash < 0 for cash in cashflows[1:]) or not any(cashflows[1:]):
        raise ValueError("Require one initial negative investment followed by nonnegative receipts")
    years = [(day - parsed[0]).days / 365 for day in parsed]

    def npv(rate):
        terms = [cashflows[0]]
        for cash, year in zip(cashflows[1:], years[1:]):
            exponent = -year * math.log1p(rate)
            terms.append(cash * math.exp(exponent) if exponent < 700 else float("inf"))
        return sum(terms)

    low, high = -0.999999, 1e6
    if npv(low) < 0 or npv(high) > 0:
        raise ValueError("IRR is outside the supported numerical bracket")
    for _ in range(200):
        midpoint = (low + high) / 2
        if npv(midpoint) > 0:
            low = midpoint
        else:
            high = midpoint
    result = (low + high) / 2
    return {
        "annual_irr": result,
        "npv_residual": npv(result),
        "day_count": "ACT/365",
        "convention": "Receipts must include dividends and terminal sale proceeds after the chosen costs/taxes.",
    }


def technical_context(adjusted_closes: list[float], volatility_days: int = 63) -> dict[str, Any]:
    """Indicators from ordered, consistently adjusted daily observations."""
    if len(adjusted_closes) < 2:
        raise ValueError("At least two observations are required")
    positive(**{str(i): price for i, price in enumerate(adjusted_closes)})
    if isinstance(volatility_days, bool) or not isinstance(volatility_days, int) or volatility_days < 2:
        raise ValueError("Volatility window must be an integer of at least two daily returns")
    returns = [math.log(b / a) for a, b in zip(adjusted_closes, adjusted_closes[1:])]
    rsi = None
    if len(adjusted_closes) >= 15:
        changes = [b - a for a, b in zip(adjusted_closes, adjusted_closes[1:])]
        gain = sum(max(value, 0) for value in changes[:14]) / 14
        loss = sum(max(-value, 0) for value in changes[:14]) / 14
        for change in changes[14:]:
            gain = (gain * 13 + max(change, 0)) / 14
            loss = (loss * 13 + max(-change, 0)) / 14
        rsi = 50.0 if gain == loss == 0 else 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    peak = adjusted_closes[0]
    drawdown = 0.0
    for price in adjusted_closes:
        peak = max(peak, price)
        drawdown = min(drawdown, price / peak - 1)
    return {
        "observations": len(adjusted_closes),
        "last_adjusted_close": adjusted_closes[-1],
        "sma": {
            str(window): sum(adjusted_closes[-window:]) / window if len(adjusted_closes) >= window else None
            for window in (20, 50, 200)
        },
        "rsi14_wilder": rsi,
        "annualized_log_volatility": stdev(returns[-volatility_days:]) * math.sqrt(252)
        if len(returns) >= volatility_days
        else None,
        "volatility_days": volatility_days,
        "max_drawdown_full_input": drawdown,
        "return_252_days": adjusted_closes[-1] / adjusted_closes[-253] - 1
        if len(adjusted_closes) >= 253
        else None,
        "momentum_12_minus_1": adjusted_closes[-22] / adjusted_closes[-253] - 1
        if len(adjusted_closes) >= 253
        else None,
        "convention": "252 trading days/year; sample standard deviation of log returns; 12-minus-1 skips 21 sessions. Supply ordered daily prices with one consistent adjustment convention. These indicators do not predict returns.",
    }
