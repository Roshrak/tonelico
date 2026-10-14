---
name: software-factory
description: "Build and fix code with Astra master planning, AGY implementation, deterministic Runner verification, independent Sol review, and exact Hermes commits."
version: 3.0.0
author: Hermes Agent
license: MIT
platforms: [windows, linux]
metadata:
  hermes:
    tags: [coding, builder, agy, astra, sol, git, workflow]
---

# Software Factory v2

## Overview

SoftFac v2 uses one strategic planning call followed by a deterministic
Hermes-controlled task graph:

```text
Astra master plan -> Hermes ready task -> AGY -> Runner -> Sol -> Hermes commit
                                                   ^       |
                                                   |       |
                                                   +-- AGY repair
```

Hermes selects ready tasks from the immutable master-plan artifact. A normal
project does not call Astra again after each commit. Astra is called again only
when verified evidence proves that the plan is invalid/incomplete or the user
changes the objective or authorized scope.

Exceptional replanning requires a structured, verified reason with one of
`ASSUMPTION_DISPROVED`, `REQUIRED_GAP_UNCOVERED`,
`ARCHITECTURE_DEPENDENCY_CONFLICT`, `PLAN_EXHAUSTED_OBJECTIVE_INCOMPLETE`, or
`USER_OBJECTIVE_OR_SCOPE_CHANGE`. Test failure, repair, rejection, stagnation,
and ordinary resume are not replan triggers.

## How to execute

```bash
hermes-code-factory-v2 run "<repo_path>" "<task_description>"
```

CLI Argument Contract:
- `<repo_path>` and `<task_description>` are strictly POSITIONAL arguments for `run` and `plan`. Never pass `--repo` or `--request` flags.

Optional arguments:

- `--files "src/auth.py,src/models.py"` sets a hard edit boundary.
- `--test-cmd "pytest -q"` sets deterministic verification.
- `--agy-bin "<path>"` pins the AGY executable when it is not on `PATH`.
- `plan`, `execute`, `status`, and `resume` are available as separate modes.
- `--agy-navigation-recovery off|observe|adaptive` controls the bounded
  host-side navigation recovery path; `adaptive` is the default for new runs.

The active AGY runtime is pinned by platform: Windows uses the audited `1.2.2`
identity, and this NixOS Linux deployment uses its verified `1.2.0` identity.
A changed or unavailable executable, model capability,
authentication state, or isolation boundary fails closed; the factory does not
auto-update, substitute, or install AGY.

On Linux, the Builder runs in a Bubblewrap mount and PID namespace with only a
disposable file mirror. A private Secret Service receives the single AGY OAuth
item; the host home, session bus, Git metadata, and factory run state are not
mounted. Check `factory_health` through the Hermes factory MCP before starting
a run, then use `factory_plan` and `factory_execute` or the CLI. If a run fails,
inspect its evidence with `factory_status` before resuming it.

Adaptive recovery is Python-only and single-symbol. It uses exact AST/source
hash binding and the existing candidate synchronization boundary; it does not
add a planner, reviewer, task database, LSP, vector index, or Luna route.
For recovery discovery, explicit file/line and symbol hints remain first; a
bounded exact AST definition lookup then resolves one real function, method or
class before occurrence fallback. Ambiguity remains path-reduced and does not
consume an additional Builder attempt.

The repository must be its Git top-level directory. The factory uses a
host-owned candidate worktree; AGY receives a disposable mirror without
`.git`. AGY cannot accept work, stage, commit, merge, or push.

## Ownership rules

1. Astra owns strategy and task contracts, not routine scheduling.
2. Hermes owns sequencing, budgets, state, repair, resume, completion, and
   commit.
3. AGY owns implementation and repair within the current task scope.
4. Runner owns scope/integrity checks, deterministic tests, staging, and
   `git write-tree`.
5. Sol independently judges the fixed candidate and returns APPROVE/REJECT.
6. Only Hermes may run `git commit`.
7. Luna is outside the v1 production runtime. Stagnation or exhausted repair
   budget is recorded as `BLOCKED` with evidence.

## Safety and completion

Every accepted candidate is identified by `{base_commit, candidate_id}`, where
`candidate_id` is the Git tree OID from `git write-tree`. Sol approval and the
Hermes commit gate must match both values; any candidate, base, index, or
unstaged mutation invalidates approval.

COMPLETE requires all required tasks committed, every global criterion backed
by current verified evidence, no unresolved blocking finding, and no pending
or ambiguous candidate/commit. If implementation does not converge while the
plan remains valid, the run is BLOCKED; Astra is not used to rescue it.

## Resume and evidence

Run state is written atomically and contains execution progress, current task,
attempt count, candidate/review/verification references, completed commits,
and block/replan evidence. Task definitions remain in the immutable master
plan and are not copied into state.

Resume does not refund attempts or invoke Astra for ordinary crashes. A
pending commit is reconciled only when its parent and tree exactly match the
recorded `{base_commit, candidate_id}`; otherwise the run fails closed.

Keep offline deterministic tests separate from authenticated/live AGY tests.
Do not claim live runtime, UI, hardware, LAN, or deployment behavior from
fake-provider tests. Do not install, update, substitute, merge, push, or deploy
without the required explicit authority.
