import asyncio

import pytest
from mcp import Client

from aethelgard_mcp.config import Settings
from aethelgard_mcp.contracts import Finding
from aethelgard_mcp.models import ResearchRequest
from aethelgard_mcp.orchestrator import Orchestrator
from aethelgard_mcp.prompts import ROLES
from aethelgard_mcp.provider import SyntheticProvider
from aethelgard_mcp.server import create_server
from aethelgard_mcp.worker import create_worker


class RecordedProvider(SyntheticProvider):
    def __init__(self, settings, events, sabotage=None):
        super().__init__(settings)
        self.events = events
        self.sabotage = sabotage

    async def run(self, role, stage, request, context):
        self.events.append((role, stage, context))
        await asyncio.sleep(0)
        result = await super().run(role, stage, request, context)
        if self.sabotage == stage:
            result.artifact.reviewed_roles = []
        if self.sabotage == "blocking_" + stage:
            result.artifact.findings = [
                Finding(
                    subject="AAA",
                    severity="blocking",
                    explanation="Fabricated source",
                    correction="Exclude until verified",
                )
            ]
        if self.sabotage == "no_price_final" and stage == "final":
            result.artifact.candidates[0].price = None
            result.artifact.narrative = "Buy AAA immediately with the whole budget."
        return result


def setup_inprocess(tmp_path, sabotage=None):
    settings = Settings(demo=True, run_dir=tmp_path)
    events = []
    provider = RecordedProvider(settings, events, sabotage)
    coordinator = Orchestrator(
        settings,
        provider=provider,
        client_factory=lambda role: Client(create_worker(role, settings, provider)),
    )
    return coordinator, events


async def test_full_protocol_barriers_and_saved_artifacts(tmp_path):
    coordinator, events = setup_inprocess(tmp_path)
    run = coordinator.start(ResearchRequest(tickers=["AAA", "BBB"], horizons_years=[1, 4.6]))
    status = await coordinator.wait(run["run_id"])
    assert status["status"] == "complete"
    assert status["calls"] == 17
    stage_order = ["independent"] * 3 + ["self_review"] * 3 + ["cross_review"] * 3 + ["fresh_audit"] * 3
    stage_order += ["study"] + ["revision"] * 3 + ["final"]
    assert [entry[1] for entry in events] == stage_order
    assert all(not context for _, _, context in events[:3])
    assert all(set(context) == {"own"} for _, _, context in events[3:6])
    assert all(set(context["reports"]) == set(ROLES) for _, _, context in events[6:9])
    report = coordinator.store.read(run["run_id"], "report.json")
    assert len(report["artifact_sha256"]) == 17
    assert report["synthetic"]
    assert report["eligible_recommendations"] == ["AAA", "BBB"]
    assert "SYNTHETIC OFFLINE" in (tmp_path / run["run_id"] / "report.md").read_text(encoding="utf-8")


async def test_incomplete_peer_review_fails_before_final(tmp_path):
    coordinator, events = setup_inprocess(tmp_path, "cross_review")
    run = coordinator.start(ResearchRequest(tickers=["AAA"]))
    status = await coordinator.wait(run["run_id"])
    assert status["status"] == "failed"
    assert not any(stage == "final" for _, stage, _ in events)
    assert not (tmp_path / run["run_id"] / "report.json").exists()


async def test_orchestrator_mcp_tools_and_background_lifecycle(tmp_path):
    coordinator, _ = setup_inprocess(tmp_path)
    async with Client(create_server(coordinator.settings, coordinator)) as client:
        response = await client.call_tool("start_research", {"request": {"tickers": ["AAA"]}})
        assert not response.is_error
        run_id = response.structured_content["run_id"]
        await coordinator.wait(run_id)
        result = await client.call_tool("research_report", {"run_id": run_id})
        assert result.structured_content["synthetic"]
        math_result = await client.call_tool(
            "return_attribution", {"price": 100, "starting_eps": 5, "terminal_eps": 6, "exit_pe": 20}
        )
        assert math_result.structured_content["terminal_price"] == 120


async def test_worker_refuses_peer_context_in_independent_stage(tmp_path):
    settings = Settings(demo=True, run_dir=tmp_path)
    async with Client(create_worker("fundamental", settings)) as client:
        result = await client.call_tool(
            "research_stage", {"stage": "independent", "request": {}, "context": {"peer": "buy AAA"}}
        )
        assert result.is_error


async def test_three_real_stdio_processes_end_to_end(tmp_path):
    coordinator = Orchestrator(Settings(demo=True, run_dir=tmp_path))
    run = coordinator.start(ResearchRequest(tickers=["AAA"], horizons_years=[1]))
    status = await coordinator.wait(run["run_id"])
    assert status["status"] == "complete"
    assert status["calls"] == 17


async def test_cancel_and_second_run_rejection(tmp_path):
    coordinator, _ = setup_inprocess(tmp_path)
    run = coordinator.start(ResearchRequest())
    with pytest.raises(ValueError, match="already active"):
        coordinator.start(ResearchRequest())
    await asyncio.sleep(0.01)
    coordinator.cancel(run["run_id"])
    status = await coordinator.wait(run["run_id"])
    assert status["status"] == "cancelled"


async def test_cancellation_before_background_task_starts(tmp_path):
    coordinator, events = setup_inprocess(tmp_path)
    run = coordinator.start(ResearchRequest())
    coordinator.cancel(run["run_id"])
    status = await coordinator.wait(run["run_id"])
    assert status["status"] == "cancelled"
    assert status["calls"] == 0
    assert not events


def test_missing_key_and_low_budget_rejected(tmp_path):
    coordinator = Orchestrator(Settings(run_dir=tmp_path, demo=False))
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        coordinator.start(ResearchRequest())
    coordinator = Orchestrator(Settings(run_dir=tmp_path, demo=True, max_api_calls=16))
    with pytest.raises(ValueError, match="17 calls"):
        coordinator.start(ResearchRequest())


@pytest.mark.parametrize(
    "sabotage",
    [
        "blocking_cross_review",
        "blocking_fresh_audit",
        "blocking_study",
        "blocking_revision",
        "no_price_final",
    ],
)
async def test_release_gates_survive_later_model_omissions(tmp_path, sabotage):
    coordinator, _ = setup_inprocess(tmp_path, sabotage)
    run = coordinator.start(ResearchRequest(tickers=["AAA"]))
    status = await coordinator.wait(run["run_id"])
    assert status["status"] == "complete"
    assert status["eligible_recommendations"] == []
    report = coordinator.store.read(run["run_id"], "report.json")
    assert report["final"]["artifact"]["recommendations"] == []
    assert report["raw_final_audit"]["release_status"] == "unreleased_model_draft"
    markdown = (tmp_path / run["run_id"] / "report.md").read_text(encoding="utf-8")
    assert "Buy AAA immediately" not in markdown


def test_credentials_rejected_before_request_persistence(tmp_path):
    settings = Settings(
        api_key="configured-fixture-secret", model="configured-fixture-secret", run_dir=tmp_path
    )
    assert "configured-fixture-secret" not in str(settings.public())
    assert "configured-fixture-secret" not in repr(settings)
    coordinator = Orchestrator(settings)
    with pytest.raises(ValueError, match="credential"):
        coordinator.start(ResearchRequest(objective="Use configured-fixture-secret"))
    assert not list(tmp_path.iterdir())
