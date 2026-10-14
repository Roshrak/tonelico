# Hermes Software Factory v2

Portable fail-closed coding pipeline:

```text
user objective
  -> Astra initial master plan
  -> Hermes selects ready task
  -> AGY edits disposable non-Git mirror
  -> boundary syncs only the allowed delta
  -> Runner verifies, stages, and writes candidate tree
  -> Sol independently approves or rejects
  -> Hermes commits the exact approved tree
  -> Hermes selects the next ready task
```

Normal execution calls Astra once. Runner failure and Sol rejection return to
AGY repair. Repeated stagnation or exhausted repair budget becomes `BLOCKED`;
Luna is not part of the v1 production path.

The bundle contains no API keys, OAuth tokens, conversation history, run
artifacts, or repository contents.

## Contents

- `bin/hermes-code-factory-v2`: portable CLI wrapper.
- `lib/hermes_factory_v2.py`: orchestration engine and AGY boundary.
- `tests/`: offline regression and process-boundary fixtures.
- `docs/agy-builder-contract.md`: AGY runtime and isolation contract.
- `docs/software-factory-SKILL.md`: Hermes skill definition.
- `docs/softfac-linux-ops-SKILL.md`: Linux operations skill for Hermes.
- `bridge/factory_mcp_adapter.py`: Hermes MCP tools for health, plan, run,
  status, execute, and resume.
- `lib/linux_agy_boundary.py`: disposable Linux Builder namespace and private
  one-item credential store.

## Requirements

Python 3.10+, Git, Hermes CLI, an authenticated supported provider, and the
platform-pinned AGY CLI. Windows uses AGY `1.2.2` and Windows Sandbox. This
NixOS Linux deployment uses AGY `1.2.0`, Bubblewrap, D-Bus, GNOME Keyring,
and libsecret. The factory does not install, update, or silently substitute a
runtime or model. Preflight checks the executable SHA-256 and the platform's
isolated no-edit probe before a Builder turn.

Authenticate the role provider separately. For a ChatGPT/Codex subscription:

```bash
hermes auth add openai-codex
hermes auth status openai-codex
```

AGY uses the exact configured model `gemini-3.8-flash-high`. Use `--agy-bin`
when the executable is not discoverable on `PATH`.

## Run offline tests

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 python3 -m pytest tests -q
```

The tests use temporary repositories and deterministic fake providers. They do
not consume model quota.

On this NixOS host, `factory_health` in `hermes-factory-mcp` reports the active
AGY identity and Bubblewrap availability without calling a model. A new run
then performs a live no-edit AGY preflight inside the Linux namespace. The
installed Hermes skill is `softfac-linux-ops`.

## Use it

```bash
hermes-code-factory-v2 run /path/to/git-repository \
  "Fix the bug and add tests" \
  --files src/app.py \
  --files tests/test_app.py \
  --test-cmd "pytest -q" \
  --agy-bin /path/to/agy
```

The repository must be its Git top-level directory. `--files` is a hard edit
boundary. The factory creates a task branch/worktree and never merges or
pushes automatically.

Other modes:

```bash
hermes-code-factory-v2 plan /path/to/repo "Implement the objective"
hermes-code-factory-v2 execute RUN_ID
hermes-code-factory-v2 status RUN_ID --json
hermes-code-factory-v2 resume RUN_ID
```

New runs support `--agy-navigation-recovery off|observe|adaptive`. `adaptive`
keeps the first Builder attempt unchanged; after a no-patch or explicit
navigation-related failure, Hermes may reduce the visible task surface and
use a deterministic Python single-symbol capsule. Capsule output is validated
and reintegrated into the real candidate before Runner verification. The
recovery path uses the same 12-attempt budget and never calls Astra, Sol, or
Luna for navigation help. Legacy run states without this setting retain the
original `off` behavior.

When recovery has an exact Python identifier, host discovery checks AST
definitions before lexical occurrences, so call-sites do not create false
ambiguity. Ambiguous or unsupported definitions use the existing safe
path-reduced fallback; discovery itself consumes no Builder attempt.

Review and merge deliberately after exact approval:

```bash
git -C /path/to/repo diff main...hermes/task-<run-id>
git -C /path/to/repo cherry-pick COMMIT_HASH
```

## Ownership

- Astra: one whole-project strategy, task graph, dependencies, criteria,
  invariants, assumptions, and exceptional replan only.
- Hermes: task selection, budgets, repair loop, state, candidate lifecycle,
  resume, completion, and the only `git commit` authority.
- AGY: implementation/repair in the disposable non-Git mirror.
- Runner: scope, deterministic verification, staging, and `git write-tree`.
- Sol: independent semantic review of the exact candidate.
- Luna: outside v1.

The reviewer receives the exact staged diff, candidate tree identity, test
evidence, and bounded read-only source context. Approval binds
`{base_commit, candidate_id}`. Any mutation after approval invalidates it.
