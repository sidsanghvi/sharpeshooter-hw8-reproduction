"""Packaged command-line intake for bounded SharpeShooter research tasks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .research_task import MAX_TASK_BYTES, ResearchTaskError, parse_research_task, research_task_digest
from .task_runner import TaskRunError, run_research_task


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sharpeshooter-task")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--task", required=True)
    run = commands.add_parser("run")
    run.add_argument("--task", required=True)
    run.add_argument("--db", type=Path, required=True)
    run.add_argument("--capture", type=Path, required=True)
    run.add_argument("--approved-task-digest", required=True)
    run.add_argument("--confirm-oos", action="store_true")
    run.add_argument("--verdict", choices=("accept",), required=True)
    return parser


def _read_task(value: str) -> bytes:
    if value == "-":
        raw = sys.stdin.buffer.read(MAX_TASK_BYTES + 1)
    else:
        with Path(value).open("rb") as source:
            raw = source.read(MAX_TASK_BYTES + 1)
    if len(raw) > MAX_TASK_BYTES:
        raise ResearchTaskError("Research task is invalid.")
    return raw


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        raw = _read_task(args.task)
        if args.command == "validate":
            print(research_task_digest(parse_research_task(raw)))
            return 0
        result = run_research_task(
            raw,
            db_path=args.db,
            capture_path=args.capture,
            approved_task_digest=args.approved_task_digest,
            confirm_oos=args.confirm_oos,
            verdict=args.verdict,
        )
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0
    except (OSError, ResearchTaskError, TaskRunError):
        print("SharpeShooter task command failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
