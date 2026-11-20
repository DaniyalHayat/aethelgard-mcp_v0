"""Deterministic evidence gates and conditional scenario comparisons."""

from datetime import timedelta

from .calculators import enterprise_dcf, owner_cash_dcf, portfolio_return, return_attribution
from .contracts import Finding, ResearchArtifact
from .models import ResearchRequest


def blocks_candidate(finding: Finding, ticker: str, known_tickers: set[str]) -> bool:
    if finding.severity != "blocking":
        return False
    subject = finding.subject.strip().upper()
    if finding.scope == "global":
        return True
    if finding.scope == "auto" and subject in {"ALL", "GLOBAL", "PORTFOLIO"}:
        return True
    return subject == ticker or subject not in known_tickers


def evaluate(
    artifact: ResearchArtifact,
    request: ResearchRequest,
    carried_findings: list[Finding] | None = None,
    known_tickers: set[str] | None = None,
) -> dict:
    ledger = {row.source_id: row for row in artifact.evidence}
    subjects = {row.ticker for row in artifact.candidates} | (known_tickers or set())
    findings = [*artifact.findings, *(carried_findings or [])]
    rows = []
    for candidate in artifact.candidates:
        failures = list(candidate.gaps)
        source = ledger.get(candidate.price_source_id)
        if candidate.price is None or candidate.price_at is None:
            failures.append("Missing dated entry price")
        elif candidate.price_at > request.as_of:
            failures.append("Entry price is after the decision cutoff")
        elif request.as_of - candidate.price_at > timedelta(days=7):
            failures.append("Entry price is more than seven calendar days old")
        if source is None or source.cutoff_status(request.as_of) != "eligible" or source.kind != "observed":
            failures.append("Entry price has no eligible observed source")
        financial_sources = [ledger.get(key) for key in candidate.financial_source_ids]
        if not financial_sources or any(
            row is None
            or row.authority != "primary"
            or row.access != "full_text"
            or row.kind != "observed"
            or row.cutoff_status(request.as_of) != "eligible"
            for row in financial_sources
        ):
            failures.append("Financial inputs lack eligible fully read primary sources")
        if any(blocks_candidate(f, candidate.ticker, subjects) for f in findings):
            failures.append("Unresolved blocking research finding")
        seen = set()
        calculations = []
        for scenario in candidate.scenarios:
            key = (scenario.years, scenario.name)
            if key in seen:
                failures.append("Duplicate scenario horizon/name")
                continue
            seen.add(key)
            if candidate.price is None:
                continue
            result = portfolio_return(
                [
                    {
                        "amount": request.budget_per_horizon,
                        "entry_price": candidate.price,
                        "terminal_price": scenario.terminal_price,
                        "dividends_per_share": scenario.dividends_per_share,
                    }
                ],
                scenario.years,
                capital_tax_rate=0.24 if scenario.years <= 1 else 0.15,
            )
            attribution = None
            if all(
                value is not None
                for value in (scenario.starting_eps, scenario.terminal_eps, scenario.exit_pe)
            ):
                attribution = return_attribution(
                    candidate.price, scenario.starting_eps, scenario.terminal_eps, scenario.exit_pe
                )
                if abs(attribution["terminal_price"] - scenario.terminal_price) > max(
                    0.01, scenario.terminal_price * 0.001
                ):
                    failures.append(f"EPS times exit multiple does not match {key} terminal price")
            calculations.append(
                {"name": scenario.name, "years": scenario.years, **result, "attribution": attribution}
            )
        for years in request.horizons_years:
            group = {
                s.name: s.terminal_price + s.dividends_per_share
                for s in candidate.scenarios
                if s.years == years
            }
            if set(group) != {"bear", "base", "bull"}:
                failures.append(f"Missing complete scenarios for {years} years")
            elif not group["bear"] <= group["base"] <= group["bull"]:
                failures.append(f"Scenario ordering is inconsistent for {years} years")
        valuation = None
        if candidate.valuation:
            model = candidate.valuation
            try:
                if model.cash_flow_type == "FCFF":
                    valuation = enterprise_dcf(
                        model.cashflows,
                        model.discount_rate,
                        model.terminal_growth,
                        model.net_debt,
                        model.diluted_shares,
                    )
                else:
                    valuation = owner_cash_dcf(model.cashflows, model.discount_rate, model.terminal_growth)
                    valuation["per_share"] = valuation["value"] / model.diluted_shares
                    if model.net_debt != 0:
                        failures.append("FCFE already values equity; do not subtract net debt again")
            except ValueError as exc:
                failures.append("Invalid valuation: " + str(exc))
        else:
            failures.append("No explicit cash-flow valuation supplied")
        rows.append(
            {
                "ticker": candidate.ticker,
                "eligible": not failures,
                "gaps": list(dict.fromkeys(failures)),
                "scenarios": calculations,
                "valuation": valuation,
            }
        )
    rankings = []
    for years in request.horizons_years:
        ranked = []
        for row in rows:
            if not row["eligible"]:
                continue
            cases = {s["name"]: s for s in row["scenarios"] if s["years"] == years}
            base = cases["base"]["holding_period_return"]
            downside = min(0, cases["bear"]["holding_period_return"])
            score = base + 0.5 * downside
            ranked.append(
                {
                    "ticker": row["ticker"],
                    "score": score,
                    "base_return": base,
                    "bear_return": cases["bear"]["holding_period_return"],
                    "bull_return": cases["bull"]["holding_period_return"],
                }
            )
        rankings.append(
            {"years": years, "ranked": sorted(ranked, key=lambda row: row["score"], reverse=True)}
        )
    return {
        "candidates": rows,
        "rankings": rankings,
        "score_definition": "Conditional holding-period base return minus 0.5 times bear-case loss. Explicit risk preference, not expected return, probability or optimized Sharpe ratio.",
        "verification_limit": "Gates validate supplied provenance and arithmetic, not whether a source actually supports a generated claim. Independent source audits remain necessary.",
    }
