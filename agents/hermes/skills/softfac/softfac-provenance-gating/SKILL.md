---
name: softfac-provenance-gating
description: Use when validating Git provenance and benchmark artifacts.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, git, provenance, reviewer, sol, empirical-benchmark]
---

# SoftFac v2 Non-Self-Referential Provenance & Empirical Artifact Gating

Guidelines for orchestrating empirical benchmarks and formal adversarial reviews (Sol / Reviewer role) in SoftFac v2 without violating Git cryptographic invariants.

## 1. The Git Hashing Recursion Invariant (Pitfall & Rule)

### Pitfall
Never instruct the Builder or test harness to record the commit hash of the *current* in-flight commit inside tracked repository files (e.g. `artifact.json`, `decision.md`, `README.md`) prior to committing.
- **Mechanism**: A Git commit SHA depends on the exact tree hash of its contents (`git write-tree`). Inserting the final 40-character commit SHA into a tracked file within that commit changes the content of the file, which changes the tree hash, and recursively invalidates the commit SHA. Barring an impossible cryptographic fixed point, a commit cannot embed its own final hash.
- **Reviewer Rejection**: Adversarial reviewers like Sol (`gpt-6-sol`) will strictly reject this as internally inconsistent under Git semantics, invalidating the provenance of empirical trials and findings fixes.

### Correct Provenance Schemes
When an empirical trial or decision record requires immutable traceability to code under test, use one of the following non-self-referential methods:

1. **Base Candidate Commit + Source Tree Hash**:
   - Record `evaluated_candidate_commit`: The immutable predecessor commit providing the engine/code implementation (e.g. the initial feature commit).
   - Record `source_tree_hash`: The exact Git tree hash (`git rev-parse HEAD^{tree}` or `git write-tree`) verifying the exact clean tree state at execution time.
   - Record `working_tree_clean`: Boolean verifying `git status --porcelain` clean state.

2. **Sequential Attestation Commit**:
   - Commit 1 (`code`): Full implementation and automated test suites.
   - Commit 2 (`benchmark/attestation`): Runs empirical trial targeting the immutable commit SHA of Commit 1, committing the resulting artifacts and decision record referencing Commit 1.

3. **Runtime Git Revision Resolution**:
   - The trial harness must accept `--candidate-commit` and `--source-tree-hash` CLI parameters while falling back dynamically to Git commands (`git rev-parse HEAD` / `git rev-parse HEAD^{tree}`), never hardcoding stale or predicted commit hashes.

## 2. Matched-Budget Comparison Discipline

When evaluating model capabilities, multi-pass reasoning, or context expansions against baseline methods:
- **Rule**: Compare alternatives under a strictly MATCHED wall-clock or token budget.
- **Mechanism**: Showing that a second-pass inference achieves higher accuracy than a fast single-pass observation is methodologically invalid if second-pass took 125 ms and single-pass took 5 ms. To prove true held-out utility, allocate equal resources (e.g. 125 ms observation budget via multi-view / deep observation vs 125 ms semantic second-pass reasoning).
- **Ablation Control**: Hold candidate proposals, tool actions, examples, and environmental context strictly identical, altering only the single independent variable under ablation.

## 3. Real Wall-Clock Calibration vs Simulated Metrics

- When benchmark scripts output latency numbers (e.g. 100 samples with mean 125 ms), the total elapsed test execution time must mathematically align with the individual recorded latencies.
- If running simulated or offline replay fixtures, include actual calibrated delays matching the simulated latency so the harness wall-clock run is substantive and reproducible.
