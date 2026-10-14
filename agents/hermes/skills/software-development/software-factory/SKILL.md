---
name: software-factory
description: "Build and fix code with HoH issue-ledger continuity, Sol planning/review, lean Aider/Gemini building, Luna debugging, strict scope/tests, and a hash-checked Git commit gate."
version: 2.2.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [coding, builder, aider, sol, git, workflow]
---

# Software Factory v2

## Overview
This skill routes implementation through the fail-closed v2 factory. Hermes orchestrates; capability preflight runs before planning; fresh Sol contexts plan and review through the `openai-codex` ChatGPT/Codex OAuth route by default; Aider is a lean single-model Gemini Medium builder using `diff-fenced`; fresh Luna diagnoses failures through the same subscription route; Git commits only the exact staged diff approved by Sol. HoH runs preserve a versioned issue ledger and trajectory, and may pass a bounded disclosure of a prior run's unresolved evidence to the next planner. Sol is not injected into Aider's context, and Aider does not run a second architect pass. The installed `prompt-master` skill is applied to every role prompt: explicit goal, context, constraints, output contract, and done criteria, without hidden chain-of-thought requests.

## When to Use
- The user requests building a new feature, refactoring code, or fixing bugs in a repository.
- Examples:
  - "In `/path/to/my-project`, add rate limiting to API routes."
  - "Refactor `db.py` to use async connection pooling in `~/code/api`."
  - "Fix the failing test in `~/projects/bot`."

## How to Execute
For a complete task, invoke the factory runner via the terminal tool:

```bash
hermes-code-factory-v2 run "<repo_path>" "<task_description>"
```

Optional arguments:
- Specify a hard target-file boundary when known:
  `hermes-code-factory-v2 run "<repo_path>" "<task_description>" --files "src/auth.py,src/models.py"`
- Specify a custom test command:
  `hermes-code-factory-v2 run "<repo_path>" "<task_description>" --test-cmd "npm test"`
- Separate planning from execution:
  `hermes-code-factory-v2 plan ...`, then `hermes-code-factory-v2 execute <run-id>`.
- Continue a related task with bounded prior-run evidence:
  `hermes-code-factory-v2 run ... --prior-run <run-id>`.
- Inspect or retry:
  `hermes-code-factory-v2 status <run-id>` / `hermes-code-factory-v2 resume <run-id>`.

## Rules
1. Never edit repo files manually line-by-line in the conversation. Delegate code changes to `hermes-code-factory-v2`.
2. Do not use the legacy runner unless the user explicitly asks for v1. Never silently downgrade when v2 is blocked.
3. Do not auto-merge to `main`. The runner uses `hermes/task-<run-id>` in a separate worktree.
4. Report the run ID, phase, branch, commit, changed files, tests, review cycles, and reviewed diff hash.
5. If the runner reports `blocked`, report the exact missing/misrouted provider or base-state condition. Do not substitute another model.
6. For long-running work, retain the factory defaults (15 minutes per role and one hour for builds/tests) unless the task has a tighter explicit budget.
