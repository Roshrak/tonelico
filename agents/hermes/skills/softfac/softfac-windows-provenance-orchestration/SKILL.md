---
name: softfac-windows-provenance-orchestration
description: Use when managing SoftFac review loops and provenance.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, provenance, git, review, orchestrator, sol, agy]
---

# SoftFac v2 Provenance & Review Orchestration Protocol

Grounded protocol for orchestrating multi-round adversarial reviews with Sol (`gpt-6-sol`) and AGY Builder (`gemini-3.8-flash-high`) on Windows, preventing cyclic rejections on provenance and immutable verification.

## 1. Provenance Commit Model (Break the Self-Referential Cycle)

A Git commit cannot record its own SHA within tracked files without changing its tree hash and creating an infinite regression. To prevent provenance rejections:

Distinguish and isolate three explicit identities in documentation, manifests, and test suites:
1. **Historical Execution Provenance**: The commit where benchmark runs, telemetry, or baseline episodes were physically executed (e.g. `2bc166e2...`). Preserve this truthfully; do not overwrite it with remediation commits.
2. **Remediation / Fixed-Runner Code Commit**: The commit containing the actual code, schema, and runner bug fixes (e.g. `47974ad...`). Both line-item labels, headers, and narrative references must strictly use this identical SHA.
3. **Attestation / Review Commit**: The head commit subjected to reviewer evaluation. Manifest and tree verification in external evidence should point to the code commit being evaluated.

## 2. Immutable Raw Git Object Verification

When reviewers require proof that committed artifacts cannot be spoofed by dirty checkout files:
- **Zero Checkout Reliance**: Never use local filesystem paths or `os.path.exists()` for committed ledger checks. Never fall back to mutable checkout bytes when git commands return dirty or missing states.
- **Strict `git cat-file -p`**: Read files directly from Git object storage via `git cat-file -p <target_commit>:<path>`.
- **Target Freezing**: Resolve and freeze `target_commit` into a full 40-character hexadecimal SHA once. Prohibit mutable references (`HEAD`, `main`, branch names, tags) and short SHAs in validation runners; fail closed if invalid.
- **Negative Rejection Test**: Always pair raw-object tests with an adversarial negative test proving that modifying, corrupting, or deleting working directory files has zero impact on verification.

## 3. Builder Orchestration & Anti-Reactive Discipline

- **Beyond Literal Prompting**: Do not prompt Builder merely with "Fix the exact findings in one turn". That causes reactive patching where Builder addresses only reviewer wording rather than auditing invariant families.
- **Autonomous Invariant Audit**: Require Builder to inspect all related records (e.g., verifying both step and episode records, checking both success and failure branches, auditing all documentation references) before declaring completion.
- **Orchestrator Acceptance Gate**: Before creating the review commit, Orchestrator must independently run:
  1. Full unit test suite discovery (`python -m unittest discover`).
  2. Hard invariant suite (zero violations allowed).
  3. Adversarial oracle controls (100% false-positive rejection).
  4. Git working tree audit: ensure evidence logs and scratch scripts remain untracked; stage and commit only declared deliverable files.
