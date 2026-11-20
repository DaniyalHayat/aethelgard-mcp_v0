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


def operating_cash_bridge(
    revenue: float, operating_margin: float, tax_rate: float, diluted_shares: float,
    depreciation: float = 0, capex: float = 0, working_capital_increase: float = 0,
    investment_cash: float = 0, guarantee_calls: float = 0, cash_tax_timing: float = 0,
    interest_expense: float = 0, cash_interest_income: float = 0,
    minority_cash: float = 0, preferred_cash: float = 0,
    debt_issued: float = 0, debt_principal: float = 0, equipment_principal: float = 0,
    recognize_loss_tax_benefit: bool = False,
) -> dict[str, Any]:
    """Reconcile operating earnings to FCFF and common FCFE in consistent currency units.

    Margins retain compensation as a cash-equivalent cost. Do not add SBC again or
    separately impose the same future compensation through dilution. Operating rent
    remains in margins; equipment principal must not duplicate cash capex.
    """
    numeric = {k: v for k, v in locals().items() if k != "recognize_loss_tax_benefit"}
    finite(**numeric)
    if diluted_shares <= 0 or not 0 <= tax_rate <= 1 or operating_margin > 1:
        raise ValueError("Require positive shares, tax from 0 to 1 and margin at most 1")
    signed = {"operating_margin", "working_capital_increase", "cash_tax_timing"}
    if any(v < 0 for k, v in numeric.items() if k not in signed):
        raise ValueError("Cash uses and asset quantities must be nonnegative")
    if not isinstance(recognize_loss_tax_benefit, bool):
        raise ValueError("recognize_loss_tax_benefit must be boolean")
    ebit = revenue * operating_margin
    pretax_common = ebit - interest_expense + cash_interest_income
    operating_tax = (ebit if recognize_loss_tax_benefit else max(ebit, 0)) * tax_rate
    common_tax = (pretax_common if recognize_loss_tax_benefit else max(pretax_common, 0)) * tax_rate
    nopat = ebit - operating_tax
    net_financing = interest_expense - cash_interest_income + common_tax - operating_tax
    common_income = pretax_common - common_tax - minority_cash - preferred_cash
    reinvestment = capex - depreciation + working_capital_increase + investment_cash + guarantee_calls
    fcff = nopat - reinvestment - cash_tax_timing
    net_borrowing = debt_issued - debt_principal - equipment_principal
    fcfe = fcff - net_financing - minority_cash - preferred_cash + net_borrowing
    direct_fcfe = common_income - reinvestment - cash_tax_timing + net_borrowing
    return {
        "ebit": ebit, "nopat": nopat, "cash_equivalent_common_income": common_income,
        "cash_equivalent_earnings_per_share": common_income / diluted_shares, "economic_reinvestment": reinvestment,
        "net_financing_after_tax": net_financing, "net_borrowing": net_borrowing,
        "fcff": fcff, "fcfe": fcfe, "direct_fcfe": direct_fcfe,
        "reconciliation_difference": fcfe - direct_fcfe, "cash_per_share": fcfe / diluted_shares,
        "convention": "Compensation retained in margin; fixed input ownership; no second opening-debt subtraction from FCFE value. Minority/preferred inputs are cash distributions, so the earnings output is a cash-equivalent proxy, not accounting EPS. Tax timing, deductibility limits and asset recoveries require explicit assumptions.",
    }


def funded_terminal_cash(
    next_nopat: float, terminal_growth: float, marginal_roic: float,
    investment_floor: float = 0, financing_after_tax: float = 0, common_cash_claims: float = 0,
) -> dict[str, Any]:
    """Fund stable growth without adding two estimates of the same reinvestment need."""
    finite(**locals())
    if next_nopat <= 0 or marginal_roic <= 0 or not 0 <= terminal_growth < 1:
        raise ValueError("Require positive NOPAT/ROIC and terminal growth from 0 to less than 1")
    if investment_floor < 0 or common_cash_claims < 0:
        raise ValueError("Investment floor and common cash claims must be nonnegative")
    growth_investment = next_nopat * terminal_growth / marginal_roic
    investment = max(growth_investment, investment_floor)
    fcff = next_nopat - investment
    return {
        "growth_reinvestment": growth_investment, "reinvestment": investment,
        "fcff": fcff, "fcfe_before_net_borrowing": fcff - financing_after_tax - common_cash_claims,
        "convention": "Next-period NOPAT; investment floor includes persistent capex less depreciation, working capital and recurring investments. A nonpositive cash flow does not support a positive perpetuity.",
    }


def funding_path(
    opening_cash: float, common_cashflows: list[float], dividends: list[float], buybacks: list[float]
) -> dict[str, Any]:
    """Show liquidity before corrective financing; negative balances are funding gaps."""
    if not common_cashflows or len({len(common_cashflows), len(dividends), len(buybacks)}) != 1:
        raise ValueError("Cash flows, dividends and buybacks need equal nonzero lengths")
    finite(opening_cash=opening_cash, **{str(i): x for i, x in enumerate(common_cashflows + dividends + buybacks)})
    if opening_cash < 0 or any(x < 0 for x in dividends + buybacks):
        raise ValueError("Opening cash and shareholder payouts must be nonnegative")
    cash, periods = opening_cash, []
    for index, (fcfe, dividend, buyback) in enumerate(zip(common_cashflows, dividends, buybacks), 1):
        cash += fcfe - dividend - buyback
        periods.append({"period": index, "cash": cash, "funding_shortfall": max(-cash, 0)})
    return {"periods": periods, "maximum_funding_shortfall": max(p["funding_shortfall"] for p in periods),
            "convention": "FCFE already includes specified borrowing and principal. Retained cash is not also added to a DCF that values the same flows."}


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
