---
name: softfac-windows-provenance-gating
description: Use when gating commit provenance and reviews in SoftFac v2.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, provenance, git, sol, reviewer, orchestrator, windows]
---

# SoftFac v2 Windows Provenance Gating & Review Protocol

Protocol for orchestrating commit provenance, immutable verification, and artifact evidence gating between Builder, Orchestrator, and Sol Reviewer.

## 1. Commit Provenance Architecture (Strict Separation of Roles)
Never allow self-referencing commit cycles where a documentation commit attempts to record its own SHA as the subject commit. Maintain clear semantic separation across three distinct identities:

1. **Historical Execution Commit**:
   - The exact Git SHA where the baseline or historical run was originally executed.
   - Preserved immutably in run manifests (`initial_run.json`, `run.json`) and baseline reports.
   - Never backfilled or overwritten with subsequent remediation commits.

2. **Remediation / Fixed-Runner Code Commit**:
   - The exact Git SHA containing the code fixes and unit tests implemented by Builder and committed by Orchestrator.
   - Synchronized consistently across all report sections (headers, notes, and tables).

3. **Review / Attestation Commit**:
   - The commit on the tracking branch submitted to Sol Reviewer for evaluation.
   - Evidence logs, usage accounting, and review JSON artifacts belong in external uncommitted directories (e.g., `evidence_rounds_*/`), never committed into the subject commit itself.

## 2. Immutable Git Object Verification
Avoid tests that rely on mutable working tree files or dynamic Git references:
- **Zero Checkout Dependence**: Regression tests verifying committed artifacts must read raw Git blobs unconditionally via `git cat-file -p <target_commit>:<path>`.
- **Target Freezing**: Target commit parameters must resolve and freeze into an immutable 40-character hexadecimal SHA. References like `'HEAD'`, `'main'`, branches, tags, or short SHAs must fail closed with explicit assertion errors.
- **Negative Tamper Immunity**: Include dedicated adversarial test methods proving that dirty, modified, or deleted working tree files cannot alter validation of committed Git objects.

## 3. Builder Prompting & Closure Design
Avoid reactive prompts that ask Builder to fix only reviewer wording.
- **Proactive Invariant Auditing**: Do not prompt Builder with `"Fix the exact findings in ONE turn directly"`. Require Builder to audit the entire invariant family of the finding before concluding.
- **Fail-Closed Semantics**: For uncalled models or step-level failures prior to proposal, never manufacture availability (`available: true`, `status_code: 200`). Use canonical fail-closed identities (e.g., `C_UNAVAILABLE`, `available: false`, `status_code: null`).
- **Strict Schema Boundaries**: Always enforce `"additionalProperties": false` and action-specific contract validation on raw inputs prior to any normalization.

## 4. Evidence Retention & Audit Logging
- Collect all raw driver logs (`sol_r*_driver.log`), review JSONs (`sol_*_result.json`), token usage (`sol_*_usage.json`), Builder prompts, and pool logs into a dedicated untracked evidence directory (`evidence_rounds_<start>_<end>/`).
- Maintain an `INDEX_EVIDENCE.md` cataloging every round's artifact sizes, verdicts, and role descriptions for human inspection.
