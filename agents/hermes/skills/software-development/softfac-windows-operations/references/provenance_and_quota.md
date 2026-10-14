# Provenance Architecture & Git Object Hashing Discipline

## 1. Resolution of the Commit-Hash Recursion Paradox
Under standard Git object hashing mechanics:
$$\text{Commit SHA} = \text{SHA-1}(\text{tree } H_{\text{tree}} \,\|\, \text{parent } H_{\text{parent}} \,\|\, \text{metadata})$$

The tree hash $H_{\text{tree}}$ is recursively computed from directory entries and file contents (blobs). Consequently, if a committed artifact or report attempts to record its own commit SHA within its tracked file content, modifying that content alters the blob hash, which in turn alters $H_{\text{tree}}$, and thereby changes the commit SHA.
Resolving $H = f(H)$ is computationally infeasible without an astronomically improbable SHA-1 fixed point.

## 2. Non-Self-Referential Provenance Scheme (`git_source_tree_and_base_commit`)
To establish mechanically verifiable, mathematically sound provenance without circular recursion:
1. **Immutable Candidate Code Commit**: The empirical evaluation targets the immutable candidate code commit (e.g. the commit implementing the feature or engine under review).
2. **Evaluated Source Tree Hash**: Record the Git tree hash via `git rev-parse HEAD^{tree}` or `git write-tree` to pin the exact clean snapshot of the source files.
3. **Working Tree Cleanliness**: Verify `working_tree_clean: true` via `git status --porcelain` to prove the tree state is pristine and immutable.
4. **Attestation Commit**: The evaluation artifact and decision report reside in a subsequent attestation commit that points to the evaluated code commit and source tree hash.
5. **Source-to-Revision Binding**: When using an override revision, the harness must compare `git rev-parse <rev>^{tree}` with `git rev-parse HEAD^{tree}` to mathematically prove that the executed source files match the evaluated revision.

## 3. Review Endpoint & Quota Verification
- When querying Sol Reviewer via an OpenAI-compatible completion endpoint (e.g. `Codex CLI () connected to API pool http://localhost:13844/v1` with model `gpt-6-sol`):
  - Record the actual token usage from the response payload (`res["usage"]`, `reasoning_tokens`) into a structured JSON log.
  - Transparently attribute usage to the specific API key and proxy endpoint being utilized.
