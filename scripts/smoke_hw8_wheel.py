#!/usr/bin/env python3
"""Installed-wheel smoke for task validation, workflow, and receipt integrity."""
from __future__ import annotations

import argparse
from pathlib import Path
import tempfile

from sharpeshooter.receipts import verify_receipt
from sharpeshooter.research_task import parse_research_task, research_task_digest
from sharpeshooter.task_runner import run_research_task


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.task.read_bytes()
    digest = research_task_digest(parse_research_task(raw))
    with tempfile.TemporaryDirectory(prefix="sharpeshooter-hw8-smoke-") as directory:
        root = Path(directory)
        result = run_research_task(
            raw, db_path=root / "sharpeshooter.sqlite3", capture_path=root / "capture.txt",
            approved_task_digest=digest, confirm_oos=True, verdict="accept",
        )
        if not verify_receipt(result.receipt, result.receipt_integrity_hash).valid:
            return 1
        if result.task_digest != digest or result.receipt_verification != "VERIFIED":
            return 1
    print("HW8 wheel smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
