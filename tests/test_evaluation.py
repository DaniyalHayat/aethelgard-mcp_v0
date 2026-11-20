import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from aethelgard_mcp.contracts import Candidate, Finding, ResearchArtifact, Scenario, Valuation
from aethelgard_mcp.evaluation import evaluate
from aethelgard_mcp.models import Evidence, ResearchRequest
from aethelgard_mcp.storage import RunStore


@pytest.fixture
def research():
    cutoff = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    request = ResearchRequest(tickers=["AAA"], as_of=cutoff, horizons_years=[1])
    source = Evidence(
        source_id="primary",
        url="https://example.invalid/fixture",
        title="Synthetic fixture",
        claim="Synthetic price and financial inputs",
        kind="observed",
        authority="primary",
        published_at=cutoff - timedelta(hours=1),
    )
    candidate = Candidate(
        ticker="AAA",
        thesis="Synthetic",
        risks=["Synthetic"],
        price=100,
        price_at=cutoff - timedelta(hours=1),
        price_source_id="primary",
        financial_source_ids=["primary"],
        scenarios=[
            Scenario(name=name, years=1, terminal_price=price, rationale="Synthetic")
            for name, price in [("bear", 60), ("base", 120), ("bull", 150)]
        ],
        valuation=Valuation(
            cash_flow_type="FCFE",
            cashflows=[10, 12],
            discount_rate=0.1,
            terminal_growth=0.02,
            diluted_shares=1,
            units="dollars",
            bridge_explanation="Synthetic",
            reinvestment_explanation="Synthetic",
        ),
    )
    return request, ResearchArtifact(narrative="Synthetic", evidence=[source], candidates=[candidate])


def test_scenario_math_and_gate(research):
    request, artifact = research
    result = evaluate(artifact, request)
    assert result["candidates"][0]["eligible"]
    rank = result["rankings"][0]["ranked"][0]
    assert rank["base_return"] == pytest.approx(0.199)
    assert rank["score"] == pytest.approx(0.199 - 0.5 * 0.401)


@pytest.mark.parametrize(
    "change",
    [
        "future_price",
        "old_price",
        "unread",
        "undated",
        "no_valuation",
        "missing_scenario",
        "fcfe_debt",
        "wrong_eps",
        "duplicate_scenario",
    ],
)
def test_bad_evidence_or_arithmetic_withholds_candidate(research, change):
    request, artifact = research
    candidate = artifact.candidates[0]
    if change == "future_price":
        candidate.price_at = request.as_of + timedelta(seconds=1)
    elif change == "old_price":
        candidate.price_at = request.as_of - timedelta(days=8)
    elif change == "unread":
        artifact.evidence[0].access = "indexed_excerpt"
    elif change == "undated":
        artifact.evidence[0].published_at = None
    elif change == "no_valuation":
        candidate.valuation = None
    elif change == "missing_scenario":
        candidate.scenarios.pop()
    elif change == "fcfe_debt":
        candidate.valuation.net_debt = 20
    elif change == "wrong_eps":
        candidate.scenarios[1].starting_eps = 5
        candidate.scenarios[1].terminal_eps = 6
        candidate.scenarios[1].exit_pe = 100
    elif change == "duplicate_scenario":
        candidate.scenarios.append(candidate.scenarios[0])
    result = evaluate(artifact, request)
    assert not result["candidates"][0]["eligible"]
    assert not result["rankings"][0]["ranked"]


def test_storage_confinement_and_recovery(tmp_path):
    store = RunStore(tmp_path)
    run_id = "a" * 32
    digest = store.write(run_id, "status.json", {"status": "running"})
    assert len(digest) == 64
    assert digest == hashlib.sha256((tmp_path / run_id / "status.json").read_bytes()).hexdigest()
    store.recover()
    assert store.read(run_id, "status.json")["status"] == "interrupted"
    with pytest.raises(ValueError):
        store.read("../outside", "status.json")
    with pytest.raises(ValueError):
        store.write(run_id, "../secret.json", {})


@pytest.mark.parametrize("kind", ["assumption", "opinion", "dated_forecast"])
def test_financial_evidence_requires_observed_primary_fact(research, kind):
    request, artifact = research
    source = artifact.evidence[0].model_copy(update={"source_id": "financial", "kind": kind})
    artifact.evidence.append(source)
    artifact.candidates[0].financial_source_ids = ["financial"]
    assert not evaluate(artifact, request)["candidates"][0]["eligible"]


def test_future_observation_and_zero_eps_reconciliation(research):
    request, artifact = research
    artifact.evidence[0].event_at = request.as_of + timedelta(days=100)
    assert artifact.evidence[0].cutoff_status(request.as_of) == "future_observation"
    artifact.evidence[0].event_at = None
    scenario = artifact.candidates[0].scenarios[0]
    scenario.starting_eps, scenario.terminal_eps, scenario.exit_pe = 5, 0, 20
    assert not evaluate(artifact, request)["candidates"][0]["eligible"]


@pytest.mark.parametrize("subject", ["AAA", "aaa", "portfolio", "Unclear provenance problem"])
def test_carried_blocking_findings_cannot_be_dropped(research, subject):
    request, artifact = research
    finding = Finding(subject=subject, severity="blocking", explanation="Unverified", correction="Resolve")
    assert not evaluate(artifact, request, [finding])["candidates"][0]["eligible"]
