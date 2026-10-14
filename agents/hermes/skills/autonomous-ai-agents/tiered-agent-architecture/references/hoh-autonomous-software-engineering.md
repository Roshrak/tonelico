# Harness-of-Harness (HoH) Architecture & Multi-Day Autonomous Development

Reference based on Shanghai AI Laboratory's paper (arXiv:2609.01481): *"Harness-of-Harness: Multi-Day Autonomous Software Development with Continual Improvement"*.

## Core Thesis: Structure Beats Raw Power

Standalone coding agents (even frontier models) fail on long-horizon multi-day development due to context drift, regressions, and false completions. HoH structures executions into iterative planning-coding-testing loops resembling agile software teams.

### 4 Core Invariants to Prevent Collapse
1. **Strict Role Separation:**
   - Planner sets verifiable micro-goals per sprint.
   - Developer/Builder is the ONLY agent with write access to code.
   - QA/Tester only has read + execute access; never touches source files.
2. **Empirical Evidence Requirement:**
   - Features and bugfixes are accepted ONLY when accompanied by live execution traces / test logs.
   - Absence of empirical proof is treated strictly as failure.
3. **Filesystem as Durable Memory:**
   - Memory must not live solely in model context windows or fuzzy vector embeddings.
   - Project specifications, constraints, API contracts, and conventions live directly as versioned files in the repository filesystem.
4. **Versioned Rollback Points:**
   - Every sprint builds strictly on top of verified checkpoints.
   - When a regression or broken invariant occurs, revert immediately to the last proven checkpoint rather than attempting unconstrained compounding fixes.

### Benchmark Evidence
- **GameCraft-Bench:** 2 structured HoH loops outperformed 3 unconstrained agent loops (64.84 vs 58.24) using fewer overall tokens.
- **FrontierSWE (Codex):** Win rate climbed from 27.33% to 72.67% across 10 iterations by building on verified milestones.
- **Multi-Day Capability:** 70 consecutive autonomous iterations produced a fully playable 3D FPS game from a single requirements document.

## 4 Token Reduction & Quality Enhancements Derived from HoH

1. **Planner File Tree Skeleton Index (Lazy Code Inspection):**
   - Replace full code dumps (e.g. 60k chars) with a compact repository directory tree and AST signature/class skeletons. Cuts Planner prompt token usage by ~80% while retaining structural awareness.
2. **Standardized Evidence Packets (Structured Diagnostics):**
   - Replace messy terminal dumps with a standardized `Evidence Packet` (provenance, target assertion, repro command, minimal failure slice). Reduces Reviewer and Debugger token usage by ~50% and removes noisy warnings.
3. **Artifact Warm-Start & Rollback Gate:**
   - When regressions occur during rework attempts, immediately rollback the isolated worktree to the clean base checkpoint rather than accumulating broken edits and bloated diffs.
4. **Deterministic Pre-Review Gate:**
   - Execute deterministic checks (lint, syntax, path boundary compliance, test execution) before invoking high-effort reasoning Reviewers (e.g. Sol Ultra/High). Unsound candidates are rejected with zero Reviewer tokens spent.
5. **Versioned Memory Ledger & Trajectory Tracking:**
   - Store `issue_ledger.json` and `trajectory.json` under isolated durable run roots (e.g. `run_dir/ledger/`). Track issue lifecycle transitions (`open`, `in_progress`, `resolved`, `wontfix`) to prevent premature issue closure before verified execution.
   - Maintain synchronization sequences (`sync_seq`) and cryptographic hashes to verify snapshot consistency between ledger and trajectory.
6. **Multi-Day Progressive Disclosure:**
   - When resuming or chaining subsequent loops across days, avoid re-injecting raw chat transcripts or full run histories. Expose only unresolved issues and bounded historical context (`selected_issues` with token truncation guards), preserving the context window for current implementation reasoning.
7. **Objective Classification & Mixed Policy Gating:**
   - Automatically classify prompts into `REPAIR` vs. `CAPABILITY_GROWTH` vs. `MIXED`. Prioritize regression resolution before expanding new features.
