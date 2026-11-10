#!/usr/bin/env python3
"""Reproducible SharpeShooter demo with deterministic CI and real Codex modes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen
from agents.common import AgentClient, SubscriptionCodexRunner
from sharpeshooter.receipts import verify_receipt


LIMITATION = "synthetic metrics do not validate strategy performance"
REFERENCE_MODEL = "gpt-5.6-sol"
_FORBIDDEN_CAPTURE = (
    re.compile(r"ss_[A-Za-z0-9_-]+"),
    re.compile(r"claim_token", re.I),
    re.compile(r"authorization\s*:\s*bearer", re.I),
    re.compile(r"(?:access|refresh|codex|chatgpt)[_-]?token", re.I),
    re.compile(r"/home/node/\.codex"),
    re.compile(r"/Users/"),
    re.compile(r"dv003/", re.I),
    re.compile(r"/data/oos"),
)


class CaptureSafetyError(ValueError):
    """The proposed committed capture contains forbidden material."""


def validate_capture(text: str) -> None:
    if not isinstance(text, str) or not text.strip():
        raise CaptureSafetyError("capture must be nonempty")
    if any(pattern.search(text) for pattern in _FORBIDDEN_CAPTURE):
        raise CaptureSafetyError("capture contains forbidden material")




def run_fake_demo(db_path: Path, capture: Path) -> dict:
    from sharpeshooter.research_task import parse_research_task, research_task_digest
    from sharpeshooter.task_runner import run_research_task

    fixture = Path(__file__).resolve().parents[1] / "tasks" / "hw8" / "fixtures" / "research-task-v1.json"
    raw = fixture.read_bytes()
    digest = research_task_digest(parse_research_task(raw))
    project = run_research_task(
        raw,
        db_path=Path(db_path),
        capture_path=Path(capture),
        approved_task_digest=digest,
        confirm_oos=True,
        verdict="accept",
    )
    result = project.model_dump(mode="json")
    validate_capture(Path(capture).read_text(encoding="utf-8"))
    return {
        "agent_runtime": "fake",
        "scout_identities": 2,
        "is_attempts": len(result["candidate_results"]),
        "synthetic_metrics": result["synthetic_metrics"],
        "family_oos_trial_number": result["family_oos_trial_number"],
        "budget_before": result["budget_before"],
        "budget_after": result["budget_after"],
        "author_agent_id": result["author_agent_id"],
        "reviewer_agent_id": result["reviewer_agent_id"],
        "receipt_id": result["receipt_id"],
        "receipt_consumed_by_scout": result["receipt_consumed_by_scout"],
        "receipt_verification": result["receipt_verification"],
        "operator_verdict": result["operator_verdict"],
    }


def archive_demo_database(db_path: Path, archive: Path) -> Path:
    """Move only the exact generated SQLite database and sidecars to a recovery directory."""
    db_path, archive = Path(db_path), Path(archive)
    archive.mkdir(parents=True, exist_ok=False)
    for source in (db_path, Path(str(db_path) + "-shm"), Path(str(db_path) + "-wal")):
        if source.exists():
            source.replace(archive / source.name)
    return archive


def _compose_prefix(root: Path) -> list[str]:
    return [
        "docker", "compose", "--project-directory", str(root), "--project-name", "sharpeshooter",
        "--env-file", "/dev/null", "-f", str(root / "compose.yaml"),
    ]


def _command(argv: list[str], root: Path, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(argv, cwd=root, env=env, text=True, capture_output=True, timeout=600)
    if completed.returncode != 0:
        raise RuntimeError("demo subprocess failed") from None
    return completed


def _json_command(argv: list[str], root: Path) -> dict:
    try:
        value = json.loads(_command(argv, root).stdout)
    except (json.JSONDecodeError, TypeError):
        raise RuntimeError("operator command returned invalid output") from None
    if not isinstance(value, dict):
        raise RuntimeError("operator command returned invalid output")
    return value


def _wait_for_ledger() -> None:
    for _ in range(100):
        try:
            with urlopen("http://127.0.0.1:8000/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError("ledger did not become healthy")


def _admin(root: Path, command: str, *arguments: str) -> dict:
    return _json_command(
        _compose_prefix(root) + ["exec", "-T", "ledger", "sharpeshooter-admin", command,
                                 "--db", "/state/sharpeshooter.sqlite3", *arguments],
        root,
    )


def _prepare_real_state(root: Path, reset: bool) -> None:
    compose = _compose_prefix(root)
    if reset:
        _command(compose + ["stop", "ledger"], root)
        db = root / "runtime" / "state" / "sharpeshooter.sqlite3"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = root / "runtime" / "state" / "archive" / ("pre-demo-" + stamp)
        if any(path.exists() for path in (db, Path(str(db) + "-shm"), Path(str(db) + "-wal"))):
            archive_demo_database(db, archive)
        _json_command(
            compose + ["run", "--rm", "--no-deps", "ledger", "sharpeshooter-admin", "init-db",
                       "--db", "/state/sharpeshooter.sqlite3"],
            root,
        )
    _command(compose + ["up", "--build", "-d", "ledger"], root)
    _wait_for_ledger()


def _workspace(root: Path, name: str, guidance: str) -> Path:
    workspace = root / "runtime" / "agents" / ("demo-" + name)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "craft_memory.md").write_text(guidance.rstrip() + "\n", encoding="utf-8")
    return workspace


def _event(result: dict, tool: str) -> list[dict]:
    return [event for event in result.get("events", []) if event.get("tool") == tool]


def _one_event(result: dict, tool: str) -> dict:
    events = _event(result, tool)
    if len(events) != 1:
        raise RuntimeError(f"real {tool} evidence is missing or ambiguous")
    return events[0]


def selected_spec_was_tested(is_events: list[dict], oos_event: dict) -> bool:
    selected = oos_event.get("correlation", {}).get("strategy_hash")
    return isinstance(selected, str) and any(
        event.get("correlation", {}).get("strategy_hash") == selected for event in is_events
    )


def _run_role(root: Path, role: str, key: str, workspace: Path) -> dict:
    runner = SubscriptionCodexRunner(key, project_root=root)
    return AgentClient(role, runner, workspace, REFERENCE_MODEL).run_once()


def _json_object(value: str, label: str) -> dict:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        raise RuntimeError(label + " is malformed") from None
    if not isinstance(parsed, dict):
        raise RuntimeError(label + " is malformed")
    return parsed


def _verify_real_correlations(db: Path, roles: dict[str, dict], agent_ids: dict[str, str]) -> None:
    connection = sqlite3.connect("file:" + str(db.resolve()) + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if set(roles) != set(agent_ids):
            raise RuntimeError("role identity evidence is incomplete")
        observed_counts: dict[tuple[str, str], int] = {}
        for role, result in roles.items():
            agent_id = agent_ids[role]
            for event in result["events"]:
                tool = event.get("tool")
                if not isinstance(tool, str):
                    raise RuntimeError("tool evidence is malformed")
                observed_counts[(agent_id, tool)] = observed_counts.get((agent_id, tool), 0) + 1
                correlation = event.get("correlation", {})
                if not isinstance(correlation, dict):
                    raise RuntimeError("correlation evidence is malformed")
                key = correlation.get("idempotency_key")
                if key is None:
                    for idea_id in correlation.get("idea_ids", []):
                        if connection.execute("SELECT 1 FROM ideas WHERE idea_id=?", (idea_id,)).fetchone() is None:
                            raise RuntimeError("read correlation failed")
                    idea_id = correlation.get("idea_id")
                    if idea_id is not None and connection.execute("SELECT 1 FROM ideas WHERE idea_id=?", (idea_id,)).fetchone() is None:
                        raise RuntimeError("read correlation failed")
                    receipt_id = correlation.get("receipt_id")
                    if receipt_id is not None and connection.execute("SELECT 1 FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone() is None:
                        raise RuntimeError("read correlation failed")
                    continue
                rows = connection.execute(
                    "SELECT response_json FROM idempotency_keys WHERE agent_id=? AND tool_name=? AND key=?",
                    (agent_id, tool, key),
                ).fetchall()
                if len(rows) != 1:
                    raise RuntimeError("idempotency correlation failed")
                response = _json_object(rows[0][0], "idempotency response")
                if response.get("ok") is not True:
                    raise RuntimeError("idempotency response is not successful")

                if tool == "register":
                    fields = ("idea_id", "family_id")
                    domain_event = "idea.register"
                elif tool == "claim":
                    fields = ("claim_id", "idea_id", "queue")
                    domain_event = "claim.acquire"
                elif tool == "submit_test":
                    fields = ("run_id", "version_id", "strategy_hash", "split")
                    domain_event = "test.succeeded"
                elif tool == "submit_review":
                    fields = ("review_id", "idea_id", "run_id")
                    domain_event = "review.submitted"
                    if response.get("reviewer_agent_id") != agent_id:
                        raise RuntimeError("review actor correlation failed")
                else:
                    raise RuntimeError("unexpected idempotent tool evidence")
                if any(response.get(field) != correlation.get(field) for field in fields):
                    raise RuntimeError("domain ID correlation failed")

                audit_rows = connection.execute(
                    "SELECT actor_agent_id,subject_idea_id,subject_id,payload_json FROM audit_events WHERE event_type=? AND actor_agent_id=?",
                    (domain_event, agent_id),
                ).fetchall()
                parsed_rows = [(row, _json_object(row[3], "audit payload")) for row in audit_rows]
                idea_id = correlation.get("idea_id")
                if tool == "register":
                    matched = [payload for _, payload in parsed_rows if payload.get("idea_id") == response["idea_id"] and payload.get("family_id") == response["family_id"]]
                elif tool == "claim":
                    matched = [payload for row, payload in parsed_rows if payload.get("claim_id") == response["claim_id"] and payload.get("idea_id") == response["idea_id"] and payload.get("queue") == response["queue"] and row[1] in (None, response["idea_id"])]
                elif tool == "submit_test":
                    matched = [payload for row, payload in parsed_rows if row[1] == idea_id and payload.get("run_id") == response["run_id"] and payload.get("split") == response["split"] and payload.get("synthetic_metrics") is True]
                    tool_rows = connection.execute(
                        "SELECT payload_json FROM audit_events WHERE event_type='tool.submit_test' AND actor_agent_id=?",
                        (agent_id,),
                    ).fetchall()
                    tool_payloads = [_json_object(row[0], "tool audit payload") for row in tool_rows]
                    if not any(payload.get("run_id") == response["run_id"] and payload.get("version_id") == response["version_id"] and payload.get("strategy_hash") == response["strategy_hash"] and payload.get("split") == response["split"] for payload in tool_payloads):
                        raise RuntimeError("tool audit correlation failed")
                else:
                    matched = [payload for row, payload in parsed_rows if row[1] == response["idea_id"] and row[2] == response["review_id"] and payload.get("review_id") == response["review_id"] and payload.get("run_id") == response["run_id"]]
                if len(matched) != 1:
                    raise RuntimeError("audit correlation failed")

        for (agent_id, tool), count in observed_counts.items():
            actual = connection.execute(
                "SELECT count(*) FROM audit_events WHERE event_type=? AND actor_agent_id=?",
                ("tool." + tool, agent_id),
            ).fetchone()[0]
            if actual != count:
                raise RuntimeError("tool audit count does not match captured calls")
    finally:
        connection.close()


def run_codex_demo(root: Path, capture: Path, *, reset: bool) -> dict:
    root, capture = Path(root).resolve(), Path(capture)
    _prepare_real_state(root, reset)
    compose = _compose_prefix(root)
    status = _command(
        compose + ["run", "--rm", "--no-deps", "-T", "agent-login", "sh", "-c",
                   "exec codex login status 2>&1"],
        root,
    )
    if status.stdout != "Logged in using ChatGPT\n":
        raise RuntimeError("exact agent container is not authenticated using ChatGPT")

    operator = _admin(root, "create-operator", "--display-name", "Reproducible demo operator")
    operator_id = operator["operator_id"]
    issued = {}
    for name, role in (("scout1", "Scout"), ("scout2", "Scout"), ("builder", "Builder"), ("skeptic", "Skeptic")):
        issued[name] = _admin(root, "issue-key", "--operator-id", operator_id, "--role", role)

    workspaces = {
        "scout1": _workspace(root, "scout1", "Method: search momentum work, then register one sourced falsifiable momentum idea."),
        "scout2": _workspace(root, "scout2", "Method: search specifically for reviewed work and consume its returned receipt with get_result before proposing anything new."),
        "builder": _workspace(root, "builder", "Method: search approved momentum work, claim it, run multiple IS variants, then submit the selected identical specification once to OOS with explicit confirmation."),
        "skeptic": _workspace(root, "skeptic", "Method: search tested work, claim review, and submit an independent review of the successful OOS run."),
    }

    lines = ["SharpeShooter automated end-to-end demo", "agent_runtime=codex", f"model={REFERENCE_MODEL}"]
    roles: dict[str, dict] = {}
    try:
        lines.append("agent_request=Scout-1")
        roles["scout1"] = _run_role(root, "scout", issued["scout1"]["plaintext_key"], workspaces["scout1"])
        register = _one_event(roles["scout1"], "register")
        idea_id = register["correlation"]["idea_id"]
        lines.append(f"response_id={idea_id} status=proposed idempotency_key={register['correlation']['idempotency_key']}")
        _admin(root, "approve", "--operator-id", operator_id, "--idea-id", idea_id,
               "--decision", "approve", "--note", "Reproducible demo approval")
        lines.append(f"status_transition={idea_id}:proposed->approved")

        lines.append("agent_request=Builder")
        roles["builder"] = _run_role(root, "builder", issued["builder"]["plaintext_key"], workspaces["builder"])
        tests = _event(roles["builder"], "submit_test")
        is_tests = [event for event in tests if event["correlation"].get("split") == "is"]
        oos_tests = [event for event in tests if event["correlation"].get("split") == "oos"]
        if len(is_tests) < 2 or len(oos_tests) != 1:
            raise RuntimeError("real Builder did not produce the required IS/OOS sequence")
        oos = oos_tests[0]
        oos_run = oos["correlation"]["run_id"]
        if not selected_spec_was_tested(is_tests, oos):
            raise RuntimeError("real Builder did not freeze the selected IS specification")
        for event in tests:
            lines.append(
                "response_id={run} split={split} status=succeeded idempotency_key={key}".format(
                    run=event["correlation"]["run_id"], split=event["correlation"]["split"],
                    key=event["correlation"]["idempotency_key"],
                )
            )
        lines.append("synthetic_metrics=true")
        lines.append(f"family_oos_trial_number={oos['result']['oos_trial_number']}")
        lines.append(f"oos_budget_before=0 oos_budget_after={oos['result']['budget_used']}")

        lines.append("agent_request=Skeptic")
        roles["skeptic"] = _run_role(root, "skeptic", issued["skeptic"]["plaintext_key"], workspaces["skeptic"])
        review = _one_event(roles["skeptic"], "submit_review")
        review_id = review["correlation"]["review_id"]
        lines.append(f"response_id={review_id} status=reviewed idempotency_key={review['correlation']['idempotency_key']}")
        lines.append("distinct_reviewer=true")

        lines.append("agent_request=Scout-2")
        roles["scout2"] = _run_role(root, "scout", issued["scout2"]["plaintext_key"], workspaces["scout2"])
        consumed = _one_event(roles["scout2"], "get_result")
        receipt_id = consumed["correlation"]["receipt_id"]
        lines.append(f"agent_returned_result=Scout-2 receipt_id={receipt_id}")
        _admin(root, "verdict", "--operator-id", operator_id, "--idea-id", idea_id,
               "--decision", "accept", "--note", "Reproducible demo verdict")
        lines.append("operator_verdict=accept")
    finally:
        for value in issued.values():
            value.pop("plaintext_key", None)

    _command(compose + ["stop", "ledger"], root)
    db = root / "runtime" / "state" / "sharpeshooter.sqlite3"
    _verify_real_correlations(db, roles, {role: issued[role]["agent_id"] for role in roles})
    connection = sqlite3.connect("file:" + str(db.resolve()) + "?mode=ro", uri=True)
    row = connection.execute("SELECT payload_json,integrity_hash FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
    connection.close()
    if row is None or not verify_receipt(json.loads(row[0]), row[1]).valid:
        raise RuntimeError("receipt verification failed")
    lines.append("receipt_verification=VERIFIED")
    lines.append("LIMITATION: " + LIMITATION)
    text = "\n".join(lines) + "\n"
    validate_capture(text)
    capture.parent.mkdir(parents=True, exist_ok=True)
    capture.write_text(text, encoding="utf-8")
    return {
        "agent_runtime": "codex", "scout_identities": 2, "is_attempts": len(is_tests),
        "synthetic_metrics": True, "family_oos_trial_number": oos["result"]["oos_trial_number"],
        "budget_before": 0, "budget_after": oos["result"]["budget_used"],
        "receipt_id": receipt_id, "receipt_consumed_by_scout": True,
        "receipt_verification": "VERIFIED", "operator_verdict": "accept",
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument("--agent-runtime", choices=("codex", "fake"), required=True)
    root.add_argument("--reset-demo-state", action="store_true")
    root.add_argument("--capture", type=Path, required=True)
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.agent_runtime == "fake":
        db = Path("runtime/state/demo-fake.sqlite3")
        if args.reset_demo_state:
            for suffix in ("", "-shm", "-wal"):
                (Path(str(db) + suffix)).unlink(missing_ok=True)
        result = run_fake_demo(db, args.capture)
        print(json.dumps(result, sort_keys=True))
        return 0
    result = run_codex_demo(Path(__file__).resolve().parents[1], args.capture, reset=args.reset_demo_state)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
