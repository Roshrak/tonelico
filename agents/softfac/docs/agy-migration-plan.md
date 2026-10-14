# SUPERSEDED HISTORICAL RECORD — AGY Migration Execution Plan

> This document is retained for historical provenance only. It is not an
> executable plan or active operational guidance. The active authority is the
> replacement SoftFac v2 plan: Astra creates one immutable master plan, Hermes
> executes it, AGY implements, Runner verifies, Sol reviews, and Luna is
> outside the v1 production path.

## 1. Migration Overview & Non-Negotiable Contracts
This document records the superseded migration of the Builder execution layer from Aider/LiteLLM to direct AGY CLI (`gemini-3.8-flash-high`) in Hermes Software Factory v2 (HOH Architecture).

### Core Architectural Invariants:
1. **Ownership Boundary**: Only the Builder execution boundary is replaced. Astra remains the planner; Hermes remains the orchestrator; Luna remains the repairer; Sol remains the independent reviewer; and the Git commit gate remains unchanged.
2. **Direct CLI Invocation**: AGY CLI is invoked directly (`agy.exe`). No intermediary proxy, LiteLLM server, or HTTP bridge is permitted.
3. **Fail-Closed Safety**: Any missing capability, boundary violation, or unverified containment causes an immediate `FactoryError`. Fallback to lower-safety modes is strictly prohibited.
4. **Strict Sequential Milestones**: The 14 migration steps defined in Astra Plan must be executed and approved one by one in exact dependency order. Skipping steps is forbidden.
5. **No Intermediate Skill/Launcher Pollution**: Host launchers and the installed software-factory skill at `C:/Users/HH18/AppData/Local/hermes/skills/software-development/software-factory-v2/SKILL.md` remain untouched until Step 13 & Step 14 cutover.

---

## 2. 14-Step Migration Sequence

### Step 1: Baseline Inventory & Repository Provenance (HISTORICAL)
- Scope: Dedicated worktree (`hermes/agy-migration-v2`), baseline commit `066e885`.
- Artifacts: `docs/agy-migration-plan.md`, `docs/agy-migration-baseline.md`. Complete cryptographic inventory of all 19 baseline files, exhaustive retirement catalog of legacy symbols, and audit worktree demarcation.

### Step 2: Real AGY Execution Isolation & Sandboxing
- Scope: Establish and prove deterministic filesystem and OS confinement for `agy 1.2.0` on Windows.
- Target: Verify that AGY cannot modify files outside candidate worktree or mutate main checkout/Git metadata.

### Step 3: Invariant Characterization Test Suite
- Scope: Write comprehensive offline characterization tests capturing all existing HOH invariants and legacy behaviors before refactoring.

### Step 4: AGY First-Class Configuration & Model Standards
- Scope: Refactor `Config` to make AGY (`gemini-3.8-flash-high`) the first-class builder model. Retire legacy aliases cleanly.

### Step 5: Strict Executable Resolution & Preflight Capability Probe
- Scope: Implement strict binary path resolution, hash/version validation, and confined capability preflight.

### Step 6: Dedicated Bounded Process Supervisor
- Scope: Implement asynchronous process supervisor with Windows JobObject containment, bounded stream draining, and hard print timeouts.

### Step 7: Audited AGY Event/Result Protocol Parser
- Scope: Parse streaming JSON responses, validate conversation identity, handle truncated outputs, and map structured `BuilderFailure` codes.

### Step 8: Centralized Builder Dispatcher (`_dispatch_builder`)
- Scope: Consolidate all builder calls (initial slice, Luna repair, Sol rework) through a single audited dispatch pipeline with durable reservations.

### Step 9: Safe Git Plumbing & Candidate Tree Confinement
- Scope: Replace unsafe artifact deletion with NUL-delimited safe Git status inspection (`git status -z`) and externalized runtime artifacts.

### Step 10: Resumable Lifecycle, Durable Budgets & OS Locks
- Scope: Fix checkpoint base64 encoding, implement single-writer file locks, and ensure durable attempt tracking across process restarts.

### Step 11: Append-Only JSONL Audit Journal & Crash Recovery
- Scope: Implement append-only event logging for complete execution trajectory replay and state reconstruction.

### Step 12: Deterministic Commit Gate & Tree Identity
- Scope: Cryptographically bind test passing, staged tree SHA, and Sol approval to exact Git tree OID before commit.

### Step 13: Complete Legacy Aider / Bridge Retirement & Skill Alignment
- Scope: Remove `bridge/agy_bridge.py`, `systemd/agy-bridge.service.example`, legacy bridge CLI arguments, and synchronize installed `software-factory-v2` skill only after consumer verification.

### Step 14: Multi-Tier Acceptance Testing & Final Release Gate
- Scope: Execute 4-tier acceptance suite (offline unit, subprocess fixtures, live AGY, 8 end-to-end scenarios), freeze checksums, and secure final Sol High approval.
