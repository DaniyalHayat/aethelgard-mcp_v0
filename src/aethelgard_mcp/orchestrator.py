"""Stage barriers, three real MCP clients and one review coordinator."""

import asyncio
import copy
import os
import sys
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from .config import Settings
from .contracts import Finding, StageResult
from .evaluation import evaluate
from .models import ResearchRequest
from .prompts import PROMPT_VERSION, ROLES
from .provider import ResponsesProvider, SyntheticProvider
from .storage import RunStore


class Orchestrator:
    def __init__(self, settings: Settings, client_factory=None, provider=None):
        self.settings = settings
        self.store = RunStore(settings.run_dir)
        self.client_factory = client_factory or self._client
        self.provider = provider or (
            SyntheticProvider(settings) if settings.demo else ResponsesProvider(settings)
        )
        self.tasks = {}
        self.store.recover()

    def _client(self, role):
        args = ["-m", "aethelgard_mcp.worker", "--role", role]
        if self.settings.demo:
            args.append("--demo")
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "PYTHONPATH"}
        }
        env.update(
            {
                "OPENAI_API_KEY": self.settings.api_key,
                "OPENAI_MODEL": self.settings.model,
                "AETHELGARD_MAX_OUTPUT_TOKENS": str(self.settings.max_output_tokens),
            }
        )
        return Client(
            StdioServerParameters(command=sys.executable, args=args, env=env),
            read_timeout_seconds=1200,
            raise_exceptions=True,
        )

    def start(self, request: ResearchRequest):
        serialized = request.model_dump_json()
        credentials = [
            self.settings.api_key,
            os.getenv("ALPACA_API_KEY", ""),
            os.getenv("ALPACA_SECRET_KEY", ""),
        ]
        if any(value.strip() and value.strip() in serialized for value in credentials):
            raise ValueError("Research input contains a configured credential; nothing was persisted")
        if any(not task.done() for task in self.tasks.values()):
            raise ValueError("One research run is already active in this orchestrator")
        if not self.settings.demo and not self.settings.api_key:
            raise ValueError("Set OPENAI_API_KEY in your local .env or environment, or use demo mode")
        if self.settings.max_api_calls < 17:
            raise ValueError("The complete workflow needs 17 calls; raise the call budget to at least 17")
        run_id = uuid.uuid4().hex
        self.store.write(run_id, "request.json", request.model_dump(mode="json"))
        self.store.write(run_id, "status.json", {"status": "running", "stage": "starting", "calls": 0})
        self.tasks[run_id] = asyncio.create_task(self._run(run_id, request))
        self.tasks[run_id].add_done_callback(lambda task: self._record_unstarted_cancellation(run_id, task))
        return {
            "run_id": run_id,
            "status": "running",
            "synthetic": self.settings.demo,
            "planned_api_calls": 0 if self.settings.demo else 17,
        }

    async def wait(self, run_id):
        try:
            await self.tasks[run_id]
        except asyncio.CancelledError:
            if not self.tasks[run_id].cancelled():
                raise
            self._record_unstarted_cancellation(run_id, self.tasks[run_id])
        return self.status(run_id)

    def _record_unstarted_cancellation(self, run_id, task):
        if task.cancelled():
            status = self.status(run_id)
            if status["status"] == "running":
                self.store.write(run_id, "status.json", {"status": "cancelled", "calls": status["calls"]})

    def status(self, run_id):
        return self.store.read(run_id, "status.json")

    def cancel(self, run_id):
        task = self.tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            return {
                "run_id": run_id,
                "status": "cancellation_requested",
                "note": "Already submitted provider calls may still be billed.",
            }
        return self.status(run_id)

    async def close(self):
        pending = [task for task in self.tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _run(self, run_id, request):
        calls = 0
        artifacts = {}
        fingerprints = {}
        semaphore = asyncio.Semaphore(self.settings.max_parallel)

        def save(role, stage, result):
            if result.role != role or result.stage != stage:
                raise ValueError("Worker returned a mismatched role or stage")
            if result.synthetic != self.settings.demo:
                raise ValueError("Live and synthetic artifacts cannot be mixed")
            if stage in ("cross_review", "fresh_audit") and set(result.artifact.reviewed_roles) != set(ROLES):
                raise ValueError("A review did not explicitly cover all three services")
            if stage in ("independent", "self_review", "revision") and request.tickers:
                if set(request.tickers) != {row.ticker for row in result.artifact.candidates}:
                    raise ValueError("A service omitted or substituted requested tickers")
            key = role + "_" + stage
            value = result.model_dump(mode="json")
            artifacts[key] = value
            fingerprints[key] = self.store.write(run_id, key + ".json", value)
            return value

        async def invoke(client, role, stage, context):
            nonlocal calls
            async with semaphore:
                if calls >= self.settings.max_api_calls:
                    raise ValueError("API call budget exhausted")
                calls += 1
                self.store.write(
                    run_id,
                    "status.json",
                    {"status": "running", "stage": stage, "calls": calls, "synthetic": self.settings.demo},
                )
                if client is None:
                    result = await self.provider.run(role, stage, request, context)
                else:
                    response = await client.call_tool(
                        "research_stage",
                        {
                            "stage": stage,
                            "request": request.model_dump(mode="json"),
                            "context": context,
                        },
                    )
                    if response.is_error:
                        raise ValueError("A research MCP service returned an error")
                    result = StageResult.model_validate(response.structured_content)
                return save(role, stage, result)

        async def batch(clients, stage, contexts):
            tasks = [
                asyncio.create_task(invoke(clients[role], role, stage, contexts[role])) for role in ROLES
            ]
            try:
                return dict(zip(ROLES, await asyncio.gather(*tasks), strict=True))
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

        try:
            async with AsyncExitStack() as stack:
                clients = {role: await stack.enter_async_context(self.client_factory(role)) for role in ROLES}
                independent = await batch(clients, "independent", {role: {} for role in ROLES})
                own = await batch(
                    clients, "self_review", {role: {"own": independent[role]} for role in ROLES}
                )
                cross = await batch(clients, "cross_review", {role: {"reports": own} for role in ROLES})
                audit = await batch(clients, "fresh_audit", {role: {"reports": cross} for role in ROLES})
                study = await invoke(None, "orchestrator", "study", {"cross_reviews": cross, "audits": audit})
                revisions = await batch(
                    clients,
                    "revision",
                    {role: {"own": cross[role], "audits": audit, "study": study} for role in ROLES},
                )
                blocking_ledger = [
                    {
                        "finding_id": f"{stage}:{role}:{index}",
                        "role": role,
                        "stage": stage,
                        "finding": finding,
                    }
                    for stage, group in (
                        ("cross_review", cross),
                        ("fresh_audit", audit),
                        ("study", {"orchestrator": study}),
                        ("revision", revisions),
                    )
                    for role, value in group.items()
                    for index, finding in enumerate(value["artifact"]["findings"])
                    if finding["severity"] == "blocking"
                ]
                carried = [Finding.model_validate(row["finding"]) for row in blocking_ledger]
                known_tickers = set(request.tickers) | {
                    candidate["ticker"]
                    for group in (independent, own, cross, audit, revisions)
                    for value in group.values()
                    for candidate in value["artifact"]["candidates"]
                }
                computed = {
                    role: evaluate(
                        StageResult.model_validate(value).artifact, request, carried, known_tickers
                    )
                    for role, value in revisions.items()
                }
                final = await invoke(
                    None,
                    "orchestrator",
                    "final",
                    {
                        "revisions": revisions,
                        "audits": audit,
                        "calculations": computed,
                        "unresolved_blocking_findings": blocking_ledger,
                    },
                )
                final_artifact = StageResult.model_validate(final).artifact
                final_checks = evaluate(final_artifact, request, carried, known_tickers)
                universe = set(request.tickers) or {
                    row["ticker"] for value in revisions.values() for row in value["artifact"]["candidates"]
                }
                unsupported = {row.ticker for row in final_artifact.candidates} - universe
                if unsupported:
                    raise ValueError("Final review introduced an unresearched candidate")
                if request.tickers and {row.ticker for row in final_artifact.candidates} != set(
                    request.tickers
                ):
                    raise ValueError("Final review omitted a requested ticker")
                eligible = {row["ticker"] for row in final_checks["candidates"] if row["eligible"]}
                recommendations = [ticker for ticker in final_artifact.recommendations if ticker in eligible]
                rejected = [ticker for ticker in final_artifact.recommendations if ticker not in eligible]
                released = copy.deepcopy(final)
                released["artifact"]["recommendations"] = recommendations
                released["artifact"]["narrative"] = (
                    "Evidence-gated candidates: "
                    + (", ".join(recommendations) or "none")
                    + ". Review the computed scenarios and unresolved gaps below. Raw model interpretations are unreleased audit material, not authoritative allocation instructions."
                )
                report = {
                    "run_id": run_id,
                    "request": request.model_dump(mode="json"),
                    "configuration": self.settings.public(),
                    "prompt_version": PROMPT_VERSION,
                    "synthetic": self.settings.demo,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "calls": calls,
                    "independent": independent,
                    "self_reviews": own,
                    "cross_reviews": cross,
                    "fresh_audits": audit,
                    "study": study,
                    "revisions": revisions,
                    "role_calculations": computed,
                    "final": released,
                    "raw_final_audit": {"release_status": "unreleased_model_draft", "artifact": final},
                    "blocking_findings": blocking_ledger,
                    "blocking_policy": "Blocking cross-review, fresh-audit and revision findings persist for this run. Correct the underlying evidence and start a new run; final prose cannot silently clear them.",
                    "final_calculations": final_checks,
                    "eligible_recommendations": recommendations,
                    "withheld_recommendations": rejected,
                    "artifact_sha256": fingerprints,
                    "accuracy_status": "Forecast accuracy unmeasured; no realized return validation.",
                }
                self.store.write(run_id, "report.json", report)
                from .reporting import render_report

                (self.store.directory(run_id) / "report.md").write_text(
                    render_report(report), encoding="utf-8"
                )
                self.store.write(
                    run_id,
                    "status.json",
                    {
                        "status": "complete",
                        "stage": "complete",
                        "calls": calls,
                        "synthetic": self.settings.demo,
                        "eligible_recommendations": recommendations,
                        "withheld_recommendations": rejected,
                        "report_path": str(self.store.directory(run_id) / "report.md"),
                    },
                )
        except asyncio.CancelledError:
            self.store.write(run_id, "status.json", {"status": "cancelled", "calls": calls})
        except Exception as exc:
            self.store.write(
                run_id,
                "status.json",
                {
                    "status": "failed",
                    "calls": calls,
                    "error_type": type(exc).__name__,
                    "message": "Research did not pass provider, protocol or validation checks. Partial artifacts are preserved; no recommendation was released.",
                },
            )
