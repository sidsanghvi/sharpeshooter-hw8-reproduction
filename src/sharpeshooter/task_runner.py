"""Deterministic structured-task workflow through authenticated HTTP tools."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Annotated, Literal
from uuid import uuid4

import httpx2 as httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

import sharpeshooter.ledger as ledger_module
from .domain import ActorContext
from .evaluator import EvaluationResult
from .http_app import create_app
from .ledger import Ledger
from .receipts import verify_receipt
from .research_task import (
    ResearchTaskError,
    ResearchTaskV1,
    canonical_task_bytes,
    parse_research_task,
    research_task_digest,
)


LIMITATIONS = [
    "The task is bounded and structured; it is not unrestricted prose research.",
    "Task content controls provenance and tested specifications, but the deterministic evaluator does not understand the economic thesis.",
    "Synthetic metrics do not validate strategy performance.",
    "Town proves transport and attributed requester checks; SharpeShooter proves its workflow/receipt; cross-system evidence correlates them.",
    "A receipt hash is tamper-evidence, not an independently signed truth attestation.",
    "The run does not prove real-agent reasoning, A2A/MCP conformance, hostile-code sandboxing, production readiness, or arbitrary interoperability.",
    "A `started` journal fails closed after interruption; v1 does not promise automatic project-level resumption.",
]


class TaskRunError(RuntimeError):
    pass


class _StrictResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Slug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")]


class CandidateResultV1(_StrictResult):
    candidate_id: Slug
    is_run_id: Identifier
    strategy_hash: Digest


class ProjectResearchResultV1(_StrictResult):
    schema_version: Literal["sharpeshooter.research-result.v1"]
    client_task_id: str
    task_digest: Digest
    title: str
    hypothesis: str
    sources_digest: Digest
    agent_runtime: Literal["fake"]
    idea_id: Identifier
    family_id: Identifier
    candidate_results: list[CandidateResultV1]
    selected_candidate_id: Slug
    selected_is_strategy_hash: Digest
    oos_run_id: Identifier
    oos_strategy_hash: Digest
    family_oos_trial_number: Literal[1]
    budget_before: Literal[0]
    budget_after: Literal[1]
    author_agent_id: Identifier
    reviewer_agent_id: Identifier
    review_id: Identifier
    review_recommendation: Literal["accept"]
    receipt_id: Identifier
    receipt: dict[str, Any]
    receipt_integrity_hash: Digest
    receipt_verification: Literal["VERIFIED"]
    receipt_consumed_by_scout: Literal[True]
    operator_approval: Literal["approved"]
    operator_verdict: Literal["accept"]
    synthetic_metrics: Literal[True]
    limitations: list[str]

    @model_validator(mode="after")
    def exact_contract(self):
        if self.limitations != LIMITATIONS:
            raise ValueError("invalid limitations")
        if self.author_agent_id == self.reviewer_agent_id:
            raise ValueError("reviewer must be independent")
        if self.selected_is_strategy_hash != self.oos_strategy_hash:
            raise ValueError("selected strategy mismatch")
        if self.receipt.get("receipt_id") != self.receipt_id:
            raise ValueError("receipt mismatch")
        receipt_bytes = json.dumps(
            self.receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        if len(receipt_bytes) > 32_768 or not verify_receipt(
            self.receipt, self.receipt_integrity_hash
        ).valid:
            raise ValueError("invalid receipt")
        if len({value.candidate_id for value in self.candidate_results}) != len(self.candidate_results):
            raise ValueError("duplicate candidate result")
        projected = self.model_dump(mode="json")
        if len(json.dumps(projected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()) > 65_536:
            raise ValueError("result too large")
        return self


class _DeterministicEvaluator:
    def evaluate(self, request):
        seed = int(request.strategy_hash[-8:], 16)
        return EvaluationResult(
            metrics={
                "annualized_return": round(0.08 + (seed % 7) / 100, 4),
                "annualized_volatility": 0.2,
                "sharpe_ratio": round((0.08 + (seed % 7) / 100 - 0.06) / 0.2, 4),
                "max_drawdown": -0.2,
                "observations": 100,
            },
            checks={
                "opened_split": request.split,
                "dataset_version": request.dataset_version,
                "acceptance": "pending",
                "dataset_split_hash": request.dataset_split_hash,
                "date_min": "2006-01-03" if request.split == "is" else "2019-01-02",
                "date_max": "2018-12-31" if request.split == "is" else "2026-06-19",
                "observations": 100,
                "synthetic_metrics": True,
            },
            evaluator_name="deterministic_synthetic_stub",
            evaluator_version="1",
            synthetic_metrics=True,
        )


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _strategy_hash(value: str) -> str:
    return value if value.startswith("sha256:") else "sha256:" + value


def _tool_arguments(task: ResearchTaskV1, candidate_index: int) -> dict:
    return task.candidates[candidate_index].strategy_spec.model_dump(mode="json")


async def _execute(task: ResearchTaskV1, digest: str, db_path: Path) -> tuple[ProjectResearchResultV1, list[str]]:
    original_manifest = ledger_module.selected_manifest
    service = None
    try:
        ledger_module.selected_manifest = lambda _root, split: {
            "dataset_version": "hw8-deterministic-fixture",
            "split_hash": "sha256:" + ("1" if split == "is" else "2") * 64,
        }
        service = Ledger(
            db_path,
            evaluator=_DeterministicEvaluator(),
            is_root=db_path.parent / "is",
            oos_root=db_path.parent / "oos",
        )
        service.initialize()
        owner = service.create_operator("HW8 deterministic test operator")
        admin = ActorContext.operator(owner.operator_id)
        issued = {
            name: service.issue_key(admin, role)
            for name, role in (
                ("scout1", "Scout"),
                ("scout2", "Scout"),
                ("builder", "Builder"),
                ("skeptic", "Skeptic"),
            )
        }
        app = create_app(ledger=service)

        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
            ) as client:
                async def tool(identity: str, name: str, arguments: dict) -> dict:
                    response = await client.post(
                        "/v1/tools/" + name,
                        json=arguments,
                        headers={"Authorization": "Bearer " + issued[identity].plaintext_key},
                    )
                    value = response.json()
                    if response.status_code >= 400 or value.get("ok") is not True:
                        raise TaskRunError("SharpeShooter task workflow failed.")
                    return value

                registration = await tool(
                    "scout1",
                    "register",
                    {
                        **task.idea.model_dump(mode="json"),
                        "parent_idea_id": None,
                        "idempotency_key": str(uuid4()),
                    },
                )
                idea_id = registration["idea_id"]
                service.approve(admin, idea_id, "approve", "Approved registered HW8 task digest")
                claim = await tool(
                    "builder",
                    "claim",
                    {
                        "queue": "build",
                        "idea_id": idea_id,
                        "lease_seconds": 900,
                        "idempotency_key": str(uuid4()),
                    },
                )
                is_results = []
                for index, candidate in enumerate(task.candidates):
                    run = await tool(
                        "builder",
                        "submit_test",
                        {
                            "idea_id": idea_id,
                            "claim_token": claim["claim_token"],
                            "split": "is",
                            "strategy_spec": _tool_arguments(task, index),
                            "confirm_oos": False,
                            "idempotency_key": str(uuid4()),
                        },
                    )
                    is_results.append((candidate, run))
                selected_index = next(
                    index
                    for index, candidate in enumerate(task.candidates)
                    if candidate.candidate_id == task.selected_candidate_id
                )
                selected_is = is_results[selected_index][1]
                oos = await tool(
                    "builder",
                    "submit_test",
                    {
                        "idea_id": idea_id,
                        "claim_token": claim["claim_token"],
                        "split": "oos",
                        "strategy_spec": _tool_arguments(task, selected_index),
                        "confirm_oos": True,
                        "idempotency_key": str(uuid4()),
                    },
                )
                review_claim = await tool(
                    "skeptic",
                    "claim",
                    {
                        "queue": "review",
                        "idea_id": idea_id,
                        "lease_seconds": 900,
                        "idempotency_key": str(uuid4()),
                    },
                )
                review = await tool(
                    "skeptic",
                    "submit_review",
                    {
                        "idea_id": idea_id,
                        "run_id": oos["run_id"],
                        "claim_token": review_claim["claim_token"],
                        "assessment": "Independent review of the bounded deterministic research task.",
                        "concerns": ["Synthetic metrics are not performance evidence."],
                        "recommendation": "accept",
                        "idempotency_key": str(uuid4()),
                    },
                )
                receipt_result = await tool(
                    "scout2", "get_result", {"idea_id": idea_id, "receipt_id": None}
                )
                receipt = receipt_result["receipt"]
                integrity_hash = receipt_result["integrity_hash"]
                if not verify_receipt(receipt, integrity_hash).valid:
                    raise TaskRunError("SharpeShooter receipt verification failed.")
                service.record_verdict(admin, idea_id, "accept", "Accepted after verified receipt")

        author = service.get_idea(idea_id).author_agent_id
        candidate_results = [
            CandidateResultV1(
                candidate_id=candidate.candidate_id,
                is_run_id=run["run_id"],
                strategy_hash=_strategy_hash(run["strategy_hash"]),
            )
            for candidate, run in is_results
        ]
        result = ProjectResearchResultV1(
            schema_version="sharpeshooter.research-result.v1",
            client_task_id=task.client_task_id,
            task_digest=digest,
            title=task.idea.title,
            hypothesis=task.idea.hypothesis,
            sources_digest=_sha256(
                json.dumps(
                    [source.model_dump(mode="json") for source in task.idea.sources],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            ),
            agent_runtime="fake",
            idea_id=idea_id,
            family_id=registration["family_id"],
            candidate_results=candidate_results,
            selected_candidate_id=task.selected_candidate_id,
            selected_is_strategy_hash=_strategy_hash(selected_is["strategy_hash"]),
            oos_run_id=oos["run_id"],
            oos_strategy_hash=_strategy_hash(oos["strategy_hash"]),
            family_oos_trial_number=oos["oos_trial_number"],
            budget_before=selected_is["budget_used"],
            budget_after=oos["budget_used"],
            author_agent_id=author,
            reviewer_agent_id=review["reviewer_agent_id"],
            review_id=review["review_id"],
            review_recommendation="accept",
            receipt_id=receipt["receipt_id"],
            receipt=receipt,
            receipt_integrity_hash=integrity_hash,
            receipt_verification="VERIFIED",
            receipt_consumed_by_scout=True,
            operator_approval="approved",
            operator_verdict="accept",
            synthetic_metrics=True,
            limitations=LIMITATIONS,
        )
        lines = [
            "SharpeShooter automated end-to-end demo",
            "agent_runtime=fake",
            "agent_request=Scout-1 tool=register",
            "agent_request=Builder tool=claim",
            *["agent_request=Builder tool=submit_test split=is" for _ in is_results],
            "agent_request=Builder tool=submit_test split=oos",
            "synthetic_metrics=true",
            "family_oos_trial_number=1",
            "oos_budget_before=0 oos_budget_after=1",
            "agent_request=Skeptic tool=submit_review",
            "distinct_reviewer=true",
            "agent_request=Scout-2 tool=get_result",
            f"agent_returned_result=Scout-2 receipt_id={receipt['receipt_id']}",
            "receipt_verification=VERIFIED",
            "operator_verdict=accept",
            "LIMITATION: synthetic metrics do not validate strategy performance",
        ]
        return result, lines
    except TaskRunError:
        raise
    except Exception:
        raise TaskRunError("SharpeShooter task workflow failed.") from None
    finally:
        try:
            if service is not None:
                service.close()
        finally:
            ledger_module.selected_manifest = original_manifest


def run_research_task(
    raw_task: bytes,
    *,
    db_path: Path,
    capture_path: Path,
    approved_task_digest: str | None,
    confirm_oos: bool,
    verdict: str,
) -> ProjectResearchResultV1:
    """Validate trusted controls before state, then execute the bounded lifecycle."""
    try:
        task = parse_research_task(raw_task)
    except ResearchTaskError as exc:
        raise TaskRunError("SharpeShooter task input is invalid.") from exc
    digest = research_task_digest(task)
    if approved_task_digest != digest or confirm_oos is not True or verdict != "accept":
        raise TaskRunError("SharpeShooter task is not authorized.")
    db_path, capture_path = Path(db_path), Path(capture_path)
    if any(path.exists() for path in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm"), capture_path)):
        raise TaskRunError("SharpeShooter task runtime is not fresh.")
    result, lines = asyncio.run(_execute(task, digest, db_path))
    text = "\n".join(lines) + "\n"
    if len(text.encode("utf-8")) > 32_768:
        raise TaskRunError("SharpeShooter capture exceeded its limit.")
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    capture_path.write_text(text, encoding="utf-8")
    return result
