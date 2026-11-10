# Homework 8 Compatibility Contract

Status: Milestone 0 design-time freeze complete; final whole-range wheel-boundary re-review found the finding addressed, no new Critical/Important issues, spec PASS, and quality APPROVED. Milestone 1 freezes the reviewed ingress source/release and implementation-derived counts before any real compatibility run

Last updated: 2026-11-09

This tracked file carries execution-critical values across independent milestone sessions. Later sessions may not substitute a quote trigger, hard-coded demo, different task, weaker result, or different evidence predicate without a recorded decision and a new contract/evidence generation.

## Immutable source inputs

| Input | Milestone 0 frozen value |
| --- | --- |
| SharpeShooter authorized distribution | Future allowlisted source archive and wheel at `https://github.com/sidsanghvi/sharpeshooter-hw8-reproduction/releases`; immutable tag/release URLs and SHA-256 hashes; no full repository history |
| SharpeShooter base commit | `ac1aaed0ff12f462f2eacdce2b24b1032f671d3b` |
| SharpeShooter local branch/worktree | `codex/hw8-nanda-integration`; `.worktrees/hw8-nanda-integration` |
| SharpeShooter ingress commit/tag/release | `M1 — UNFROZEN`; publish/freeze only after ingress review |
| SharpeShooter package/Python | base package `0.1.0`; Python `>=3.11` |
| Nanda Town upstream | `https://github.com/projnanda/nandatown`; `6f9a7c064486c4a0ae9242f1ff341b8a4aad0244` |
| Nanda Town user fork | `https://github.com/sidsanghvi/nandatown` |
| Nanda local branch/worktree | `codex/hw8-sharpeshooter-research`; `.worktrees/nandatown-hw8`; base/head at M0 is the upstream commit above |
| Nanda package/Python | package `0.2.0`; declared Python `>=3.11`; upstream CI covers 3.11 and 3.12 |
| Historical quote evaluator | `0.5.0`, preserved with every shipped historical replay version |
| Research evaluator | design ID `sharpeshooter-research-0.1.0`; `M2 implementation version — UNFROZEN` |

The user authorized the GitHub destination on 2026-11-09. Milestone 0 creates no remote repository, release, tag, or branch. Milestone 1 may publish only after review and must record the immutable URLs and hashes here before a real Town compatibility run.

The reproduction source archive is built from the reviewed M1 allowlist projection, not from the unchanged repository tree. Its allowlist is: projected `pyproject.toml`, `uv.lock`, `README.md`, `docs/architecture.md`, `src/sharpeshooter/**`, `agents/**`, `scripts/demo.py`, `scripts/verify_receipt.py`, reviewed M1 `scripts/verify_hw8_distribution.py` and `scripts/smoke_hw8_wheel.py`, `tasks/hw8/HW8_CONTRACT.md`, and `tasks/hw8/fixtures/research-task-v1.json`. It excludes `.git`, `benchmarks/**`, the HW7 benchmark entry point, all HW6/HW7 records/deliverables, screenshots, DOCX/PDF files, runtime/data/evidence directories, databases, captures, logs, authentication material, credentials, and untracked files. Milestone 1 records the final projection/source/wheel manifests, artifact names, immutable URLs, and SHA-256 hashes before publishing; any addition requires review.

## HW8 reproduction distribution boundary

The repository/default development tree remains unchanged and continues to preserve archived HW7 code and history. Milestone 1 must not delete, rewrite, or hide `benchmarks/**`, the existing HW7 console entry point, or any archived HW7 source in the repository. Instead, it creates an ignored, owned staging projection from the frozen ingress commit using a reviewed deterministic allowlist copier and projected build metadata.

The projection manifest is canonical JSON containing the frozen ingress commit, projection-policy version, projected relative path, source relative path, byte size, and SHA-256 for every staged file, plus the SHA-256 of the projected `pyproject.toml`. Paths are sorted bytewise; duplicate, absolute, parent-traversal, symlink, device, socket, and undeclared paths reject the projection. M1 freezes the projection manifest hash, source-archive inventory/hash, and wheel inventory/hash before publication. Actual artifact filenames, tag, URLs, and hashes remain part of the existing M1 ingress-release reservation.

The projected `pyproject.toml` preserves project name/version/runtime dependencies but defines wheel packages as exactly `src/sharpeshooter` and `agents`. Its console entry points are exactly:

| Entry point | Target |
| --- | --- |
| `builder` | `agents.builder:main` |
| `scout` | `agents.scout:main` |
| `skeptic` | `agents.skeptic:main` |
| `sharpeshooter-admin` | `sharpeshooter.operator_cli:main` |
| `sharpeshooter-task` | `sharpeshooter.task_cli:main` |

The projected metadata omits the `benchmarks` package and `sharpeshooter-hw7-benchmark` entry point. The release wheel may contain members only below `sharpeshooter/**`, `agents/**`, and one standard `sharpeshooter-*.dist-info/**` metadata directory. It must contain exactly one `.dist-info` directory and no other top-level path/package. Forbidden wheel members include `benchmarks/**`, `tasks/**`, screenshots/docs/coursework, runtime/data/evidence, credentials/authentication material, and every undeclared top-level path.

M1 distribution validation is mandatory before publication or Town use:

1. Build the source archive and wheel only from the reviewed projection with `python -m build --sdist --wheel --outdir "$DIST_DIR" "$PROJECTION_ROOT"`.
2. List every wheel member with `python -m zipfile -l "$WHEEL"` and run `python scripts/verify_hw8_distribution.py --projection-manifest "$PROJECTION_MANIFEST" --source-archive "$SOURCE_ARCHIVE" --wheel "$WHEEL"`. The verifier rejects any forbidden/undeclared member, missing/extra top-level path, second `.dist-info` directory, inventory/hash mismatch, or unsafe archive member.
3. Parse the wheel's sole `*.dist-info/entry_points.txt` and require exactly the five mappings above; a missing, extra, or changed entry point—including `sharpeshooter-hw7-benchmark`—fails.
4. Create a clean Python 3.11 environment, install only the wheel plus declared runtime dependencies, run `sharpeshooter-task validate --task tasks/hw8/fixtures/research-task-v1.json`, and run the reviewed `scripts/smoke_hw8_wheel.py` package/receipt smoke against the installed wheel. Repeat on Python 3.12 where available.
5. Run the focused task/receipt tests, `python -m build`/any then-current project distribution checker as applicable, and `git diff --check` on the frozen ingress tree.

A wheel failing inventory, entry-point, clean-install, validation, receipt-smoke, build, or applicable distribution checks cannot be published, recorded as the ingress release, or used by Town.

## Registered cases and constants

| Generation | Town profile | Project mode | Required purpose |
| --- | --- | --- | --- |
| `clean` | `sharpeshooter-research-clean` | deterministic fake | submit one registered research task and return one reviewed result |
| `duplicate` | `sharpeshooter-research-duplicate-delivery` | deterministic fake | replay the same result after duplicate delivery with one project invocation |

| Field | Frozen value |
| --- | --- |
| Town requester/provider roles | existing `buyer` / `seller` lifecycle |
| Request kind | `research_request` |
| Result kind | `research_result` |
| Provider capability | `research.reviewed-receipt` |
| Stable request ID | `research-1` |
| Journal schema version | `1` |
| Research-profile lease | `45` seconds; do not alter global leases |
| Public Town harness timeout | `90` seconds; do not alter the current global default/minimum |

The Town message identity is the `request_id`. It is not duplicated as a task-controlled field. The result echoes it for correlation. No required case may be substituted after results are observed; supplemental runs use a separately named generation.

## Common strict types and canonicalization

Every new v1 model uses strict types and rejects unknown fields. A Boolean is never accepted as an integer. These patterns are frozen:

| Type | Rule |
| --- | --- |
| SHA-256 | `^sha256:[0-9a-f]{64}$` |
| Git commit | `^[0-9a-f]{40}$` |
| SharpeShooter identifier | `^[0-9a-f]{32}$` |
| Task/candidate slug | `^[a-z][a-z0-9-]{0,63}$` |
| RFC3339 UTC timestamp | timezone-aware UTC with a trailing `Z` |

Raw JSON parsing rejects a UTF-8 BOM, trailing content, duplicate object keys, lone surrogates, non-finite numbers, C0/C1/control-format characters, and strings not already normalized to NFC. After strict model validation and NFC verification, canonical bytes are:

```python
json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
```

There is no BOM, trailing newline, or other trailing byte in the canonical value. Array order is significant. Digests are `sha256:` plus the lowercase hexadecimal SHA-256 of those bytes. The adapter independently recomputes the task and request-envelope digests; supplied digests are never trusted alone.

## Research task schema

`ResearchTaskV1` is an exact strict object:

| Field | Type and frozen rule |
| --- | --- |
| `schema_version` | literal `sharpeshooter.research-task.v1` |
| `client_task_id` | task slug |
| `idea` | exact `ResearchIdeaV1` object |
| `candidates` | ordered array of 2–8 exact `ResearchCandidateV1` objects |
| `selected_candidate_id` | candidate slug present exactly once in `candidates` |

`ResearchIdeaV1` has exactly `title` (1–160 characters), `hypothesis` (1–1,000), `rationale` (1–2,000), and `sources` (1–8 exact `ResearchSourceV1` objects). `ResearchSourceV1` has exactly `uri`, `label`, and `accessed_on`: the URI is HTTPS, 1–2,048 characters, has a host and no userinfo; the label is 1–128 characters; the date is a valid exact `YYYY-MM-DD` calendar date.

`ResearchCandidateV1` has exactly a unique `candidate_id` slug and a complete strict `StrategySpec`. Candidate IDs and canonical strategy specifications are unique. Each canonical specification is at most 6,144 bytes and has exactly:

| Strategy field | Frozen rule |
| --- | --- |
| `name` | string, 1–128 characters |
| `universe` | string, 1–512 characters |
| `signal` | string, 1–512 characters |
| `entry_rule` | string, 1–512 characters |
| `exit_rule` | string, 1–512 characters |
| `position_sizing` | string, 1–512 characters |
| `rebalance` | string, 1–512 characters |
| `parameters` | object subject to the recursive rules below |

`parameters` is a JSON object with at most 32 keys. Every key is already NFC-normalized and matches `^[a-z][a-z0-9_]{0,63}$`; keys are never rewritten. Values may be only JSON `null`, Boolean, integer, finite float, string, array, or object. Booleans remain distinct from integers; every numeric absolute value is at most `1e12`; strings are at most 256 characters; nested depth is at most 4 below `parameters`; every object/array has at most 32 members. Objects use the same key rule recursively.

The following case-sensitive lowercase keys are exhaustively denied at every depth: `approval`, `approved`, `approval_status`, `approval_digest`, `approved_digest`, `approved_task_digest`, `task_digest`, `verdict`, `verdict_policy`, `confirm_oos`, `oos`, `oos_confirmation`, `oos_budget`, `oos_limit`, `oos_trial`, `budget`, `split`, `actor_id`, `agent_id`, `author`, `author_agent_id`, `reviewer`, `reviewer_id`, `reviewer_agent_id`, `operator`, `operator_id`, `identity`, `identities`, `role`, `review`, `review_content`, `review_assessment`, `review_recommendation`, `assessment`, `runtime`, `agent_runtime`, `executable`, `command`, `cwd`, `env`, `environment`, `dataset`, `dataset_version`, `is_dataset`, `oos_dataset`, `is_root`, `oos_root`, `db`, `database`, `db_path`, `capture`, `capture_path`, `path`, `project_root`, `state_dir`, `journal`, `town_url`, `run_id`, `request_id`, `message_id`, `evidence`, `evidence_policy`, `token`, `access_token`, `refresh_token`, `secret`, `credential`, `credentials`, and `authorization`.

Every task string is rejected if it matches any of these patterns: `ss_[0-9a-f]{12}_[A-Za-z0-9_-]{32,}`; `sk-[A-Za-z0-9_-]{16,}`; `gh[pousr]_[A-Za-z0-9]{20,}`; `github_pat_[A-Za-z0-9_]{20,}`; `AKIA[0-9A-Z]{16}`; case-insensitive `\bBearer\s+[A-Za-z0-9._~+/-]+=*`; or `-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----`. Source URIs separately reject userinfo. Validation errors are fixed/redacted and never echo input.

The raw task input and canonical task are each at most 65,536 UTF-8 bytes; total JSON depth is at most 8. The task controls only provenance and candidate specifications. It cannot control approval/verdict, OOS confirmation/budget, identities/roles, review content, runtime/evaluator/datasets, filesystem paths, or evidence policy.

The registered semantic fixture is `tasks/hw8/fixtures/research-task-v1.json`. Candidate order is digest-significant. Its canonical representation is 1,456 bytes with digest:

```text
sha256:cb03de74c7a8e08414d4d30cd84ad5ed1ef0b73bef3cf980095615e20d480a9a
```

It has two candidates, selects `momentum-6-1`, and may not be edited in place after registered evidence exists. A changed research question requires a contract version or new evidence generation.

## Town request envelope

`ResearchRequestV1` is an exact strict object:

| Field | Type and predicate |
| --- | --- |
| `schema_version` | literal `sharpeshooter.research-request.v1` |
| `task` | exact `ResearchTaskV1` |
| `task_digest` | SHA-256 equal to the canonical task digest |

Town message identity plus the canonical digest of this entire envelope defines one outer logical request. The registered request ID is `research-1`. The adapter recomputes both digests before writing state.

## SharpeShooter ingress and trusted operator policy

| Field | Frozen value |
| --- | --- |
| Validation command | `sharpeshooter-task validate --task <file-or-stdin>` |
| Run command | `sharpeshooter-task run --task - --db <ignored-runtime-path> --capture <ignored-runtime-path> --approved-task-digest <digest> --confirm-oos --verdict accept` |
| Workflow boundary | authenticated HTTP/application surface, never privileged ledger shortcuts |
| Runtime | deterministic fake; no model call |
| Reset behavior | no reset flag in registered cases |
| Approval policy | only the exact registered task digest is preauthorized by the trusted HW8 test operator |
| OOS/verdict | explicit trusted invocation flags, never task fields |
| Input transport | bounded standard input or an owned task file; no shell interpolation |

The one-shot flags select the frozen deterministic HW8 test-operator policy; they do not claim a human acted live. The runner keeps approval, OOS confirmation, review/receipt, and verdict as ordered separable phases. It rejects missing/mismatched approval before creating workflow state and applies the preselected verdict only after independent review and receipt verification succeed. All candidates receive one IS evaluation; the selected candidate's exact frozen specification receives one confirmed OOS evaluation. Scout 1 authors the task, a distinct Skeptic reviews it, and Scout 2 consumes the receipt. There is one submitted task idea, not a demonstration-only second idea.

## Adapter and subprocess boundary

| Field | Frozen value |
| --- | --- |
| Town inputs | `TOWN_URL`, `RUN_ID`, `NAME`, `TOKEN`, `STATE_DIR`, `DEADLINE` |
| Trusted operator inputs | exact adapter configuration variables defined below; none may come from the request body |
| Role/message | seller; `research_request` only |
| Shell | forbidden for the SharpeShooter child; fixed argv and `shell=False` |
| Process | absolute executable/cwd; new process group; reap on every outcome |
| Timeout | 30 seconds, based on the M0 deterministic measurement of 1.31 test seconds / 2.02 wall seconds |
| Termination | 2-second graceful terminate window, then kill and reap the process group |
| Child environment | constructed fixed map defined below; adapter configuration variables are not forwarded |
| Forbidden forwarding | `HOME`, `CODEX_HOME`, proxy variables, provider/auth keys, tokens, credentials, and all unrelated ambient variables |

The adapter has exactly five trusted operator configuration variables in addition to Town's six inputs:

| Adapter variable | Exact meaning and validation |
| --- | --- |
| `SHARPESHOOTER_ROOT` | absolute, resolved, existing directory for the frozen ingress checkout; no symlink component |
| `SHARPESHOOTER_TASK_EXECUTABLE` | absolute, resolved, executable regular file below `SHARPESHOOTER_ROOT`; the packaged `sharpeshooter-task` entry point |
| `SHARPESHOOTER_APPROVED_TASK_DIGEST` | exact registered task digest frozen above |
| `SHARPESHOOTER_DB` | absolute non-symlink leaf path named `sharpeshooter.sqlite3`; its canonical parent is the derived project runtime directory; file and SQLite sidecars are absent before a registered run |
| `SHARPESHOOTER_CAPTURE` | absolute non-symlink leaf path named `capture.txt`; its canonical parent is the same derived project runtime directory; file is absent before a registered run |

The adapter derives `PROJECT_RUNTIME_DIR` as the canonical parent of both `SHARPESHOOTER_DB` and `SHARPESHOOTER_CAPTURE`; the parents must resolve equal. That directory must already exist, be owned by the adapter user, contain no symlink component, and have no ancestor/descendant overlap with canonical `SHARPESHOOTER_ROOT`. This derived value is not a sixth configuration variable. The five values are adapter configuration only. The SharpeShooter child argv is exactly:

```text
[
  SHARPESHOOTER_TASK_EXECUTABLE,
  "run", "--task", "-",
  "--db", SHARPESHOOTER_DB,
  "--capture", SHARPESHOOTER_CAPTURE,
  "--approved-task-digest", SHARPESHOOTER_APPROVED_TASK_DIGEST,
  "--confirm-oos", "--verdict", "accept"
]
```

Its cwd is exactly resolved `SHARPESHOOTER_ROOT`. Its stdin is the bounded canonical task. Its environment is a newly constructed map containing exactly `LANG=C.UTF-8`, `LC_ALL=C.UTF-8`, `PYTHONUTF8=1`, `PYTHONDONTWRITEBYTECODE=1`, and `TMPDIR=<owned non-symlink directory below STATE_DIR>`. The executable is supplied by argv, not `PATH`; no adapter/Town variable is forwarded.

Frozen byte limits are measured on UTF-8/canonical bytes as applicable:

| Boundary | Maximum bytes |
| --- | ---: |
| task stdin and canonical task, each | 65,536 |
| strict project result JSON | 65,536 |
| canonical receipt payload | 32,768 |
| child stdout | 131,072 |
| child stderr | 16,384 |
| capture | 32,768 |
| Town result | 98,304 |
| journal | 131,072 |

Exceeding a limit terminates/fails closed. Errors never include truncated raw stdout/stderr, task content, or captures.

`AdapterErrorV1` is the strict object `{"schema_version":"sharpeshooter.adapter-error.v1","code":<literal>,"message":<literal>}` with no extra fields. Messages are fixed ASCII strings of at most 160 characters:

| Code | Message |
| --- | --- |
| `invalid_configuration` | `Adapter configuration is invalid.` |
| `invalid_request` | `Research request is invalid.` |
| `task_digest_mismatch` | `Research task digest is not approved.` |
| `state_conflict` | `Adapter state conflicts with this request.` |
| `interrupted` | `A prior workflow started but did not complete.` |
| `project_timeout` | `SharpeShooter workflow timed out.` |
| `project_failed` | `SharpeShooter workflow failed.` |
| `project_output_invalid` | `SharpeShooter returned an invalid result.` |
| `project_output_too_large` | `SharpeShooter output exceeded its limit.` |
| `internal_error` | `Adapter failed closed.` |

No message interpolates exception text, paths, environment, task data, stdout, or stderr.

## Strict project result

`ProjectResearchResultV1` is a strict object with exactly these fields:

| Field | Type and predicate |
| --- | --- |
| `schema_version` | literal `sharpeshooter.research-result.v1` |
| `client_task_id` | equals the validated task |
| `task_digest` | equals the canonical validated task digest |
| `title`, `hypothesis` | exactly equal the validated task idea fields |
| `sources_digest` | SHA-256 of the canonical submitted sources array |
| `agent_runtime` | literal `fake` |
| `idea_id`, `family_id` | project identifiers |
| `candidate_results` | ordered array covering every submitted candidate exactly once |
| `selected_candidate_id` | equals the task selection |
| `selected_is_strategy_hash` | SHA-256 from the selected candidate's IS result |
| `oos_run_id` | project identifier |
| `oos_strategy_hash` | exactly equals `selected_is_strategy_hash` |
| `family_oos_trial_number` | strict integer literal `1` |
| `budget_before`, `budget_after` | strict integer literals `0`, `1` |
| `author_agent_id`, `reviewer_agent_id` | project identifiers, present and unequal |
| `review_id` | project identifier |
| `review_recommendation` | literal `accept` |
| `receipt_id` | project identifier equal to the receipt payload's identifier |
| `receipt` | actual current canonical bounded SharpeShooter receipt payload |
| `receipt_integrity_hash` | SHA-256 verified over the canonical receipt payload |
| `receipt_verification` | literal `VERIFIED` |
| `receipt_consumed_by_scout` | literal `true` |
| `operator_approval` | literal `approved` |
| `operator_verdict` | literal `accept` |
| `synthetic_metrics` | literal `true` |
| `limitations` | exact ordered fixed limitation list below |

Each `candidate_results` member has exactly `candidate_id: Slug`, `is_run_id: ProjectId`, and `strategy_hash: Digest`; IDs and order match the submitted candidates. The receipt remains governed by the existing receipt schema and integrity verifier and must fit its byte limit. Unknown fields, credentials, tokens, paths, logs, raw captures, and separate/unbounded metric output are forbidden.

## Strict Town result envelope

`TownResearchResultV1` is a strict object with exactly:

| Field | Type and predicate |
| --- | --- |
| `schema_version` | literal `sharpeshooter.town-research-result.v1` |
| `request_id` | exact Town message identity `research-1` for registered cases |
| `request_digest` | SHA-256 of the canonical validated `ResearchRequestV1` |
| `project_result` | exact `ProjectResearchResultV1` |

This nesting carries task/candidate correlation, the safe lifecycle summary, the actual bounded canonical receipt and its existing integrity hash without creating a second receipt projection. The requester recomputes the request, task, sources, selected-strategy, and receipt digests; checks independent reviewer identity, accepted review, OOS/budget facts, receipt consumption, operator verdict, and limitations; then acknowledges only the allowlisted assertions below. The Town result never contains credentials, tokens, paths, logs, database content, raw captures, or unbounded text.

## Journal contract

The journal is a strict discriminated union under schema version integer `1`.

`StartedJournalV1` has exactly:

- `version: 1`;
- `state: "started"`;
- `request_id`, `request_digest`, and `task_digest`;
- `started_at`, an RFC3339 UTC timestamp and the only safe start marker.

It contains no PID, hostname, command, cwd, or path.

`CompletedJournalV1` has the same non-discriminator fields as `StartedJournalV1`: `version`, `request_id`, `request_digest`, `task_digest`, and `started_at`. It replaces the discriminator with `state: "completed"`, then adds exactly:

- `result_message_id`, the deterministic Town response identity (1–128 printable ASCII characters with no control characters);
- `result_body`, the exact bounded `TownResearchResultV1` required for identical replay;
- `result_body_digest`, `project_result_digest`, and `capture_digest`, each SHA-256;
- `replay_facts`, the strict object `{"project_invocations":1,"response_count":1}`.

The completed journal may retain the receipt only inside the strict bounded result required for replay. It contains no separate/raw/unbounded receipt, credential, raw subprocess output, database content, project root, private path, or log. Its live path is exactly `${STATE_DIR}/sharpeshooter-journal-v1.json`, where `STATE_DIR` is the existing owned non-symlink directory supplied by Town. It refuses symlinks/escapes, uses an owned sibling temporary file plus atomic replace, and fits the journal limit. The operator never supplies or overrides `STATE_DIR`.

State handling is frozen:

- absent → atomically write `started`, then launch once;
- matching `started` → return `interrupted` without launch;
- matching `completed` → replay the identical response identity/body without launch;
- identity/digest mismatch, unknown state/version/field, malformed JSON, symlink, or escape → fail closed without launch.

## Research evaluator contract

The research evaluator is separately versioned and dispatches only for the registered research profile/evaluator pair. Its ordered stages are:

```text
accepted
claimed
received
processed
response
task_bound
receipt_integrity
independent_review
control_complete
duplicate_recognized  # duplicate profile only
portable_identity
```

Transport stages derive from Town events. Semantic stages report the reference requester's attributed terminal acknowledgement checks and never claim Town independently proved project internals. The exact requester assertion allowlist is `task_bound`, `receipt_verified`, `independent_review`, `control_complete`, plus `duplicate_recognized` only for the duplicate profile. Bundle verification dispatches by recorded profile/evaluator pair, rejects unknown pairings, and replays every shipped historical quote evaluator unchanged. Quote evaluator `0.5.0` is not reinterpreted.

## Independent one-invocation predicate

Let `C` be the registered candidate count. M0 freezes `C = 2` and these exact formulas/invariants:

| Persisted or observed fact | Exact one-invocation value |
| --- | ---: |
| project invocations | `1` |
| submitted task ideas | `1` |
| successful IS test runs | `C = 2`; every candidate exactly once |
| successful OOS test runs | `1` |
| successful total test runs | `C + 1 = 3` |
| current-ledger strategy versions | `C + 1 = 3` |
| approvals | `1` |
| reviews | `1` |
| receipts | `1` |
| verdicts | `1` |
| family OOS trial number | `1` |
| budget transition | `0 → 1` |
| author/reviewer inequality | `true` |
| clean Town deliveries | `1` |
| duplicate Town deliveries | `2`, while every project count remains identical to clean |

The selected OOS strategy hash equals the selected candidate's IS strategy hash. Fixture tests use a counter owned by the fixture command, not the adapter. Exact implementation-derived audit-event types/counts remain `M1 — UNFROZEN` until reviewed task-runner tests and are frozen before the first real Town run.

Each registered real case uses a fresh runtime whose database and sidecars are proven absent. The command has no reset behavior. A read-only checker derives all counts, task-bound ledger fields, selected-strategy equality, receipt integrity, reviewer separation, and budget transition independently of the adapter journal/stdout. A second launch must accumulate and fail this predicate rather than erase its predecessor.

## Evidence schemas

All evidence JSON uses the common strict/canonical rules. Reused primitives are exact: `Digest` is the frozen SHA-256 pattern; `Commit` is the frozen Git pattern; `ProjectId` is the frozen project-ID pattern; `Slug` is the frozen slug pattern. `VersionText` is ASCII, 1–64 characters, and matches `^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$`. `HttpsUrl` is 1–2,048 characters with scheme HTTPS, a host, and no userinfo. `RelativePath` is a 1–240 character POSIX-relative path whose nonempty segments each match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` and are never `.` or `..`. `EvidenceText` is NFC, has no control characters, and is 1–512 characters. `RedactedCommand` is one ASCII line of 1–2,048 characters, uses only documented variables/relative paths, and contains no credential, private absolute path, carriage return, or newline.

`CaseEvidenceV1` has exactly:

| Field | Exact type/value |
| --- | --- |
| `schema_version` | literal `sharpeshooter.hw8-evidence.v1` |
| `case` | literal `clean` or `duplicate` |
| `profile` | corresponding registered profile literal |
| `sources` | `EvidenceSourcesV1` |
| `contract` | `EvidenceContractV1` |
| `town_observation` | `TownObservationV1` |
| `project_observation` | `ProjectObservationV1` |
| `cross_system_binding` | `CrossSystemBindingV1` |
| `predicate_verified` | literal `true`, set only by the independent promoter |
| `observed_outcome` | literal `passed` |
| `limitations` | exact seven-item ordered fixed limitation list |

`EvidenceSourcesV1` has exactly these required fields: `sharpeshooter_base_commit`, `sharpeshooter_ingress_commit`, `nanda_upstream_commit`, `nanda_feature_commit`, and `evidence_generator_commit` are `Commit`; `sharpeshooter_distribution_kind` is literal `github-release`; `sharpeshooter_source_url` and `sharpeshooter_wheel_url` are `HttpsUrl`; `sharpeshooter_source_sha256`, `sharpeshooter_wheel_sha256`, and `adapter_sha256` are `Digest`; `sharpeshooter_package_version`, `nanda_package_version`, `python_version`, `quote_evaluator_version`, and `research_evaluator_version` are `VersionText`.

`EvidenceContractV1` has exactly: the four schema fields `task_schema_version`, `request_schema_version`, `project_result_schema_version`, and `town_result_schema_version`, each its frozen literal; `task_digest` and `request_digest` as `Digest`; `candidate_count` as strict integer literal `2`; `selected_candidate_id` as literal `momentum-6-1`; `profile` as the corresponding profile literal; and `redacted_command` as `RedactedCommand`.

`TownObservationV1` has exactly: `request_id` literal `research-1`; `request_body_digest`, `response_body_digest`, `bundle_sha256`, and `bundle_fingerprint` as `Digest`; `delivery_count` strict integer `1` clean/`2` duplicate; `response_count` strict integer `1`; `duplicate_offer_count` strict integer `0` clean/`1` duplicate; `bundle_verified` literal `true`; `requester_assertions`; and `evaluator_stages`.

For clean, `requester_assertions` has exactly four literal-true fields: `task_bound`, `receipt_verified`, `independent_review`, and `control_complete`. Duplicate adds exactly `duplicate_recognized: true`. Each `EvaluatorStageEvidenceV1` has exactly `name`, `status`, `evidence`, and `note`: `name` is the corresponding frozen stage literal; `status` is one of `passed`, `failed`, `not_enough_evidence`, `not_tested`, or `error`; `evidence` is an ordered array of 0–16 unique `EvidenceText` items, each further limited to 256 characters; `note` is an NFC/control-free string of 0–512 characters. Clean has exactly 10 stage records in frozen evaluator order: the first nine are `passed` and `portable_identity` is `not_tested`. Duplicate has exactly 11 records: the first ten, including `duplicate_recognized`, are `passed`, and final `portable_identity` is `not_tested`.

`CandidateRunEvidenceV1` is bound to the project result candidate member and has exactly `candidate_id: Slug`, `is_run_id: ProjectId`, and `strategy_hash: Digest`. `ProjectObservationV1` has exactly:

- `project_invocations: 1`, `successful_is_runs: 2`, `successful_oos_runs: 1`, `successful_total_runs: 3`, `strategy_versions: 3`, `approval_count: 1`, `review_count: 1`, `receipt_count: 1`, `verdict_count: 1`, `family_oos_trial_number: 1`, `budget_before: 0`, and `budget_after: 1`, all strict integers;
- `project_result_digest`, `capture_digest`, `adapter_journal_digest`, `selected_is_strategy_hash`, `oos_strategy_hash`, `receipt_integrity_hash`, and `receipt_payload_digest` as `Digest`, with the two strategy hashes equal;
- `idea_id`, `family_id`, `oos_run_id`, `author_agent_id`, `reviewer_agent_id`, `review_id`, and `receipt_id` as `ProjectId`, with author and reviewer unequal;
- `candidate_is_results` as exactly two ordered `CandidateRunEvidenceV1` records matching the registered candidate order;
- `selected_candidate_id` literal `momentum-6-1`;
- `receipt_verification` literal `VERIFIED`, `receipt_consumed_by_scout: true`, `operator_approval` literal `approved`, `operator_verdict` literal `accept`, and `synthetic_metrics: true`.

`CrossSystemBindingV1` has exactly: `town_task_digest` and `project_task_digest` as `Digest` plus `task_digest_equal: true`; `town_request_digest` and `adapter_request_digest` as `Digest` plus `request_digest_equal: true`; `town_selected_strategy_hash` and `project_selected_strategy_hash` as `Digest` plus `selected_strategy_hash_equal: true`; `town_receipt_id` and `project_receipt_id` as `ProjectId` plus `receipt_id_equal: true`; `town_receipt_integrity_hash` and `project_receipt_integrity_hash` as `Digest` plus `receipt_hash_equal: true`; and `source_pins_match: true`. All flags are independently derived.

Public evidence retains receipt ID/hash/verification and canonical receipt-payload digest, never receipt payload or metric values. It contains no raw bundle, logs, database content, private paths, credentials, unbounded text, or adapter-self-report as sole proof.

`ManifestV1` has exactly: `schema_version` literal `sharpeshooter.hw8-manifest.v1`; `task_digest: Digest`; `source_pins: EvidenceSourcesV1`; `case_files`, an exact object with keys `clean` and `duplicate`, each mapping to an exact object `{path: RelativePath, sha256: Digest}` whose paths are respectively `tasks/hw8/evidence/clean.json` and `tasks/hw8/evidence/duplicate.json`; `comparison_file`, exact `{path: "tasks/hw8/evidence/comparison.md", sha256: Digest}`; `reproduction_commands`, an ordered array of 1–32 unique `RedactedCommand` items; and `claim_boundaries`, the exact seven-item ordered fixed limitation list. The evidence generator commit is carried once inside `source_pins`.

`comparison.md` is UTF-8/NFC, at most 16,384 bytes, and may contain LF plus printable text but no other controls. It is generated only from validated case evidence and has exactly these H2 sections in order: `Claim`, `Frozen inputs`, `Clean observation`, `Duplicate observation`, `Independent one-invocation comparison`, and `Limitations`. Any URL is `HttpsUrl`; it adds no raw receipt, metrics, logs, paths, or claim absent from the JSON.

Promotion to `tasks/hw8/evidence/clean.json`, `duplicate.json`, `manifest.json`, and `comparison.md` is create-only and rejects existing destinations, unknown fields, mismatched heads/digests, missing raw verification, noncanonical JSON, secrets, private paths, or forbidden content.

## Schema and compatibility checks

Before registered evidence, tests must prove:

- the checked-in fixture validates and reproduces the exact canonical length/digest;
- duplicate keys, non-NFC/control strings, non-finite numbers, invalid dates/URI, credential-like content, authority fields, and every frozen bound fail closed;
- candidate reordering and semantic mutation of every task section change the digest;
- positive request/project/Town/journal/evidence examples validate and one negative example per authority/correlation boundary fails;
- task and request-envelope digests are independently recomputed;
- generated schemas are synchronized;
- quote schema fingerprints and every shipped historical quote evaluator replay remain byte/behavior compatible.

## Fresh runtime layout

Public instructions use only documented variables:

```text
SHARPESHOOTER_ROOT=<reviewer checkout of frozen ingress release>
NANDATOWN_ROOT=<reviewer checkout of frozen Nanda feature commit>
HW8_RUN_ROOT=<new ignored runtime root>
CASE_ROOT=$HW8_RUN_ROOT/<clean-or-duplicate>
CASE_ROOT/project/sharpeshooter.sqlite3
CASE_ROOT/project/capture.txt
CASE_ROOT/town-bundle/
```

Before each registered case, the whole case root is absent. The command creates only its owned project runtime directory; Town creates the output tree and supplies the seller's live `STATE_DIR`. Clean and duplicate use different case roots and no reset flag.

Current Nanda moves its generated scratch tree into the completed bundle at `<bundle>/state`. Therefore the adapter journal's final raw location is exactly `<bundle>/state/seller/sharpeshooter-journal-v1.json`. Development/raw checks discover `<bundle>` only by enumerating the direct child directories of that case's single `town-bundle` output, requiring exactly one directory with `run.json`, and then resolving the fixed relative journal path. They do not search outside that single case output or recurse for arbitrary journal names. The raw journal remains inside ignored raw Town output and is never committed; sanitized public evidence may retain only its SHA-256 and independently derived allowlisted facts, never journal content.

## Registered public commands

The implementation-derived release tag/URLs and feature heads are filled in at their reserved milestones. The portable variables and commands are otherwise exact. Validation is side-effect-free:

```bash
export TASK_DIGEST=sha256:cb03de74c7a8e08414d4d30cd84ad5ed1ef0b73bef3cf980095615e20d480a9a
export SHARPESHOOTER_ROOT=<reviewer-checkout-of-frozen-ingress-release>
export NANDATOWN_ROOT=<reviewer-checkout-of-frozen-nanda-feature-commit>
export HW8_RUN_ROOT=<new-ignored-runtime-root>

cd "$SHARPESHOOTER_ROOT"
"$SHARPESHOOTER_ROOT/.venv/bin/sharpeshooter-task" validate \
  --task tasks/hw8/fixtures/research-task-v1.json
```

This separate direct-user smoke is not a registered Town case and uses its own runtime:

```bash
export DIRECT_CASE_ROOT="$HW8_RUN_ROOT/direct-smoke"
mkdir -p "$DIRECT_CASE_ROOT/project"
test ! -e "$DIRECT_CASE_ROOT/project/sharpeshooter.sqlite3"
test ! -e "$DIRECT_CASE_ROOT/project/sharpeshooter.sqlite3-wal"
test ! -e "$DIRECT_CASE_ROOT/project/sharpeshooter.sqlite3-shm"
test ! -e "$DIRECT_CASE_ROOT/project/capture.txt"

cd "$SHARPESHOOTER_ROOT"
"$SHARPESHOOTER_ROOT/.venv/bin/sharpeshooter-task" run --task - \
  --db "$DIRECT_CASE_ROOT/project/sharpeshooter.sqlite3" \
  --capture "$DIRECT_CASE_ROOT/project/capture.txt" \
  --approved-task-digest "$TASK_DIGEST" --confirm-oos --verdict accept \
  < tasks/hw8/fixtures/research-task-v1.json
```

For each registered Town case, set `CASE` to exactly `clean` or `duplicate`, use a fresh case root, and export the exact adapter configuration:

```bash
export CASE=clean
export CASE_ROOT="$HW8_RUN_ROOT/$CASE"
test ! -e "$CASE_ROOT"
mkdir -p "$CASE_ROOT/project"
test ! -e "$CASE_ROOT/project/sharpeshooter.sqlite3"
test ! -e "$CASE_ROOT/project/sharpeshooter.sqlite3-wal"
test ! -e "$CASE_ROOT/project/sharpeshooter.sqlite3-shm"
test ! -e "$CASE_ROOT/project/capture.txt"
test ! -e "$CASE_ROOT/town-bundle"

export SHARPESHOOTER_ROOT
export SHARPESHOOTER_TASK_EXECUTABLE="$SHARPESHOOTER_ROOT/.venv/bin/sharpeshooter-task"
export SHARPESHOOTER_APPROVED_TASK_DIGEST="$TASK_DIGEST"
export SHARPESHOOTER_DB="$CASE_ROOT/project/sharpeshooter.sqlite3"
export SHARPESHOOTER_CAPTURE="$CASE_ROOT/project/capture.txt"

cd "$NANDATOWN_ROOT"
.venv/bin/nandatown test-agent \
  --profile sharpeshooter-research-clean --role seller \
  --cmd ".venv/bin/python examples/sharpeshooter_adapter.py" \
  --timeout 90 --out "$CASE_ROOT/town-bundle"
```

The duplicate command differs only in its fresh case root and profile:

```bash
export CASE=duplicate
export CASE_ROOT="$HW8_RUN_ROOT/$CASE"
test ! -e "$CASE_ROOT"
mkdir -p "$CASE_ROOT/project"
test ! -e "$CASE_ROOT/project/sharpeshooter.sqlite3"
test ! -e "$CASE_ROOT/project/sharpeshooter.sqlite3-wal"
test ! -e "$CASE_ROOT/project/sharpeshooter.sqlite3-shm"
test ! -e "$CASE_ROOT/project/capture.txt"
test ! -e "$CASE_ROOT/town-bundle"

export SHARPESHOOTER_ROOT
export SHARPESHOOTER_TASK_EXECUTABLE="$SHARPESHOOTER_ROOT/.venv/bin/sharpeshooter-task"
export SHARPESHOOTER_APPROVED_TASK_DIGEST="$TASK_DIGEST"
export SHARPESHOOTER_DB="$CASE_ROOT/project/sharpeshooter.sqlite3"
export SHARPESHOOTER_CAPTURE="$CASE_ROOT/project/capture.txt"

cd "$NANDATOWN_ROOT"
.venv/bin/nandatown test-agent \
  --profile sharpeshooter-research-duplicate-delivery --role seller \
  --cmd ".venv/bin/python examples/sharpeshooter_adapter.py" \
  --timeout 90 --out "$CASE_ROOT/town-bundle"
```

The registered case commands do not invoke the CLI directly before Town. The adapter reads the five trusted variables, uses the frozen argv/cwd, and constructs the separate narrow child environment. Adapter configuration is never a request field and public evidence redacts concrete absolute paths.

After either development/raw run, the bounded journal-location check is:

```bash
set -- "$CASE_ROOT"/town-bundle/*
test "$#" -eq 1
export BUNDLE_DIR="$1"
test -d "$BUNDLE_DIR"
test -f "$BUNDLE_DIR/run.json"
export RAW_ADAPTER_JOURNAL="$BUNDLE_DIR/state/seller/sharpeshooter-journal-v1.json"
test -f "$RAW_ADAPTER_JOURNAL"
```

`BUNDLE_DIR` and `RAW_ADAPTER_JOURNAL` are development/raw-check variables only; they are not adapter configuration and their concrete values never enter sanitized public evidence.

Current-main verification command shapes are:

```bash
python -m pytest -q \
  tests/test_records.py tests/test_coordinator.py \
  tests/test_duplicate_delivery_binding.py tests/test_evaluator.py \
  tests/test_evaluator_replay_rules.py tests/test_evaluator_strictness.py \
  tests/test_bundle.py tests/test_historical_replay_docs.py \
  tests/test_replay_cli.py tests/test_schema_sync.py \
  tests/test_track_timeout_floor.py

nandatown schemas --out schemas
python -m pytest -q tests/test_schema_sync.py
git diff --exit-code -- schemas
python -m pytest -q
python -m build
python scripts/check_distributions.py dist
git diff --check

nandatown verify "$BUNDLE"
nandatown replay "$BUNDLE"
```

`verify` is the integrity/evaluator-replay gate; `replay` is a rendering aid, not an independent correctness claim.

## Focused Nanda pull-request boundary

The allowed implementation surface is limited to current-main equivalents of:

- `src/nandatown/records.py`, `profiles.py`, `coordinator.py`, `runner.py`, `participants/buyer.py`, `evaluator.py`, `bundle.py`, `report.py`, and `schemas.py`;
- a dedicated research requester/evaluator helper only if needed for a closed dispatcher;
- research SkillMD files already supported by package data;
- `examples/sharpeshooter_adapter.py` and a deterministic fixture command;
- focused research/adapter tests, affected generated `schemas/*.schema.json`, and bounded reproduction documentation.

Dashboard files are outside scope. `pyproject.toml` changes only for a demonstrated packaging requirement. The PR does not vendor SharpeShooter, add it as a core dependency, change quote meaning, or add a generalized plugin/role system.

## Fixed limitations

The exact ordered limitation list used in project/Town results and evidence is:

1. The task is bounded and structured; it is not unrestricted prose research.
2. Task content controls provenance and tested specifications, but the deterministic evaluator does not understand the economic thesis.
3. Synthetic metrics do not validate strategy performance.
4. Town proves transport and attributed requester checks; SharpeShooter proves its workflow/receipt; cross-system evidence correlates them.
5. A receipt hash is tamper-evidence, not an independently signed truth attestation.
6. The run does not prove real-agent reasoning, A2A/MCP conformance, hostile-code sandboxing, production readiness, or arbitrary interoperability.
7. A `started` journal fails closed after interruption; v1 does not promise automatic project-level resumption.
