# SharpeShooter MVP

SharpeShooter is a controlled workspace for testing how research agents collaborate. A Scout proposes an idea, a human approves it, a Builder tests it, and an independent Skeptic reviews it before the human makes the final decision. The shared ledger records each step, prevents agents from seeing hidden evaluation data, limits repeated use of that data, and makes completed work verifiable.

Homework 6 is complete, and Homework 7 benchmark execution is complete. Homework 8 Nanda Town integration planning is active under [tasks/hw8/](tasks/hw8/). Homework 6 records and evidence are archived under [tasks/hw6/](tasks/hw6/); the completed Homework 7 benchmark record starts at [tasks/hw7/HW7_AGENTS.md](tasks/hw7/HW7_AGENTS.md); the Homework 8 continuity stack starts at [tasks/hw8/HW8_AGENTS.md](tasks/hw8/HW8_AGENTS.md).

Run the deterministic local demo, which makes no model calls:

```bash
uv run python scripts/demo.py --agent-runtime fake --reset-demo-state --capture runtime/logs/demo-fake.txt
```

The real-agent demo additionally requires Docker, the staged research data, and Codex logged in with the user's ChatGPT subscription inside the restricted agent container. Verify the login and isolation checks before starting the ledger, then run:

```bash
docker compose run --rm agent-login codex login status
docker compose run --rm agent-check
docker compose up --build -d ledger
uv run python scripts/demo.py --agent-runtime codex --reset-demo-state --capture runtime/logs/demo-codex.txt
```

The evaluator's metrics are deterministic and synthetic. They demonstrate the workflow and its safeguards; they do not measure real strategy performance or support an investment decision. See [docs/architecture.md](docs/architecture.md) for the system boundaries and operator command names, including the canonical `sharpeshooter-admin set-policy` command.

## Structured research task intake

SharpeShooter also provides a reusable deterministic command for a bounded research idea with prespecified strategy candidates. Validation is side-effect-free:

```bash
sharpeshooter-task validate --task tasks/hw8/fixtures/research-task-v1.json
```

After a trusted operator separately approves the emitted digest, a fresh runtime can execute the controlled Scout–Builder–Skeptic lifecycle:

```bash
TASK_DIGEST="$(sharpeshooter-task validate --task tasks/hw8/fixtures/research-task-v1.json)"
RUN_ROOT="$(mktemp -d)"
sharpeshooter-task run --task - \
  --db "$RUN_ROOT/sharpeshooter.sqlite3" \
  --capture "$RUN_ROOT/capture.txt" \
  --approved-task-digest "$TASK_DIGEST" \
  --confirm-oos --verdict accept \
  < tasks/hw8/fixtures/research-task-v1.json
```

The task supplies research provenance and candidate specifications only. It cannot approve itself, select identities or the reviewer, confirm out-of-sample use, set the budget/runtime/paths, provide review content, or dictate the verdict. The deterministic evaluator produces synthetic metrics for workflow verification; it does not validate investment performance or accept unrestricted prose research.
