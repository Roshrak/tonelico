---
name: softfac-windows-provenance-and-audit
description: Use when verifying provenance and audit in SoftFac.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, provenance, git, sol, audit]
---

# SoftFac Provenance & Empirical Audit Protocols

## 1. Resolution of the Commit-Hash Recursion Paradox
Under standard Git object hashing mechanics:
$$\text{Commit SHA} = \text{SHA-1}(\text{tree } H_{\text{tree}} \,\|\, \text{parent } H_{\text{parent}} \,\|\, \text{metadata})$$
The tree hash $H_{\text{tree}}$ is recursively computed from directory entries and file contents (blobs). Consequently, if a committed artifact or report attempts to record its own commit SHA within its tracked file content, modifying that content alters the blob hash, which alters $H_{\text{tree}}$, and thereby changes the commit SHA. Resolving $H = f(H)$ is computationally infeasible without an astronomically improbable SHA-1 fixed point.

## 2. Non-Self-Referential Provenance Scheme (`git_source_tree_and_base_commit`)
To establish mechanically verifiable provenance without circular recursion:
1. **Immutable Candidate Code Commit**: Empirical evaluation targets the immutable candidate code commit implementing the feature or engine under review.
2. **Evaluated Source Tree Hash**: Record the Git tree hash via `git rev-parse HEAD^{tree}` or `git write-tree` to pin the exact clean snapshot of the source files.
3. **Working Tree Cleanliness**: Verify `working_tree_clean: true` via `git status --porcelain` to prove the tree state is pristine and immutable. Clean up all untracked test fixtures or sandbox seeds prior to running the trial harness.
4. **Attestation Commit & Runner Validation Flexibility**: The evaluation artifact and decision report reside in a subsequent attestation commit that points back to the evaluated code commit and source tree hash. Any harness verifying `candidate_commit` must accept either `git rev-parse HEAD`, its parent commit, or an explicit `--candidate-commit <SHA>` flag so that creating the attestation commit does not invalidate the artifact.
5. **Source-to-Revision Binding (Anti-Mislabeling)**: When an override like `--candidate-commit <SHA>` is supplied, the runner must verify that the executed working tree matches the revision via source tree comparison (`git rev-parse <SHA>^{tree}` equals `git rev-parse HEAD^{tree}` or `git diff <SHA> -- <target_dirs>` is empty). The artifact must record both `candidate_commit` and `source_tree_hash` to guarantee executed source authenticity.

## 3. Real Provider Observation & Identity Disclosures (Sol Auditing Requirement)
When evaluating multi-provider suitability or candidate projection across desktop, browser, and legacy surfaces:
- **No Preset Scenario Summaries**: Artifact records must not consist of predetermined scenario tables or synthetic Boolean assertions alone.
- **Auditable Per-Trial Identification**: Each trial record must explicitly disclose:
  1. Application name, version, and binary path (e.g. `chrome.exe`, `msedge.exe`, `code.exe`, `notepad.exe`).
  2. Operating Process ID (`PID`) and native Window Handle (`HWND`).
  3. Stable object identity per provider (UIA RuntimeID, CDP backendNodeId, MSAA childId).
  4. Raw observation payloads and selected provider disposition.
  5. Explicit verification against silent substitution, process-binding leakage, cross-session crossover, and expired deadlines.
- **Negative & Edge Cases**: Explicitly execute and preserve records for `CDP_UNAVAILABLE` (fallback without automatic endpoint launch) and `MULTIPLE_TARGET` ambiguity.
- **Offline Simulation Scope Gating**: Benchmark artifacts produced via deterministic simulation harnesses must explicitly scope their protocol (e.g. `validated under offline deterministic simulation harness protocol`) and keep simulated gate outcomes separate from live production task-completion claims.
- **Honest Evaluator Failure Preservation**: Evaluators testing live external vision or AI gateways must never substitute cached historical answers upon network/gateway outage. Live call failures must be preserved honestly (`engine_available=False`), yielding an `INCONCLUSIVE_GATEWAY_UNAVAILABLE` or degraded verdict instead of masking outages behind synthetic 100% scores.
- **Paired Comparison Gating (Both Arms Must Be Live)**: When evaluating paired comparative pipelines (e.g. Pipeline A vs Pipeline B in an ablation or amplifier study), a definitive architectural verdict (such as `NO-GO` or `RECONSIDER`) REQUIRES that live calls succeed on BOTH paired arms for all evaluated samples. If either arm experiences gateway outages (`is_live_call=False`), that arm's failure MUST NOT be used to compute a negative delta to declare `NO-GO`; the verdict must fail closed to `INCONCLUSIVE_GATEWAY_UNAVAILABLE` or `EVALUATION_DEGRADED`.
- **Dynamic Freshness Timestamps in Interruption Contracts**: In state-machine or ledger tests validating fresh observations against interrupt deadlines, NEVER use static hardcoded timestamps that can predate live execution time. Always construct fresh observation timestamps dynamically (`datetime.now(timezone.utc) + timedelta(...)`) relative to the recorded interrupt timestamp to prevent test suite regressions across time.

## 4. Review Endpoint & Quota Traceability
- When querying Sol Reviewer via OpenAI-compatible completion endpoints (e.g. `Codex CLI () connected to API pool http://localhost:13844/v1` with model `gpt-6-sol`):
  - Record token usage from the response payload (`res["usage"]`, `reasoning_tokens`) into a structured JSON log.
  - Transparently attribute usage to the specific API key and proxy endpoint being utilized.
