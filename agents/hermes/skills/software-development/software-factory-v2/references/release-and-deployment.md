# Release and Deployment Protocol for SoftFac v2

This document governs the release lifecycle, packaging, deployment, and verification of Software Factory v2 (SoftFac v2).

## Core Principles

1. **Source of Truth Immutability**
   - Once Sol issues `APPROVE` / `authorized_for_release=true`, the source repository tree is frozen.
   - Never edit constants, code, or documentation directly in an approved release worktree to satisfy deployment-specific preferences (such as `--planner-reasoning medium`).
   - Any commit or file modification after Sol approval invalidates the release status and creates an unreviewed candidate.
   - Deployment-specific tuning belongs in launcher wrappers, environment flags, or deployment metadata.

2. **Source vs. Runtime Separation**
   - **Source Repository**: `E:/Downloads/hermes-software-factory-v2-hoh/migration-worktree-recovered2` (or canonical Git repository).
   - **Runtime Snapshot**: `%LOCALAPPDATA%\hermes\software-factory\v2`.
   - **Launcher / PATH Wrappers**: `%LOCALAPPDATA%\hermes\bin\hermes-code-factory-v2[.cmd]`.
   - The runtime must be decoupled from the development worktree so daily development does not destabilize production agents.

3. **Deterministic Packaging on Windows**
   - Windows Git often defaults `core.autocrlf=true`. A naive `git archive` converts LF to CRLF in text files, mutating file lengths and breaking SHA-256 checksums against Git blob hashes.
   - Always export archives with `-c core.autocrlf=false`:
     ```bash
     git -c core.autocrlf=false -C "<source_repo>" archive --format=tar -o "<temp_tar>" <commit_oid>
     ```
   - Never pipe `git archive | tar` across Windows PowerShell or MSYS stdout/stdin streams. On Windows, native `tar.exe` (or MSYS `/usr/bin/tar`) treats paths with colons (e.g. `C:\...`) as remote host addresses unless passed `--force-local` (`Cannot connect to C: resolve failed`). Prefer Python's stdlib `tarfile` module or pass `--force-local` when extracting tar archives on Windows:
     ```python
     with tarfile.open(archive_path) as tar:
         tar.extractall(target_staging_dir)
     ```

4. **Atomic Staging, Exact Commit Helper, and Safe Rotation**
   - **Authoritative Commit Helper**: When committing an approved candidate, do NOT hand-roll raw `git commit-tree` / `git update-ref` / `git reset --mixed` scripts. Use the production helper `_commit_exact_candidate_tree(worktree, candidate_id=..., base_commit=..., message=...)`. It atomically verifies index fingerprints, holds the index lock, and enforces old-HEAD CAS. If the helper raises or verification fails, abort deployment immediately and inspect Git state without guessing or force-rewriting refs.
   - **Dynamic Commit & Dual-Identity Gates**: Do not rely on ephemeral shell variables surviving across deployment phases. Dynamically re-resolve `commit = git rev-parse HEAD`, `commit^{tree}`, and `commit^` at the beginning of each phase. Enforce dual identity gates (`commit^{tree} == candidate_id` AND `commit^ == base_commit`) before running `git archive`, writing `DEPLOYED_VERSION.json`, promoting runtime, or executing smoke tests.
   - **Pipeline Exit Code Validation**: When piping `git -c core.autocrlf=false archive | tar`, always check BOTH return codes (`p1_rc = p1.wait()` and `p2.returncode == 0`). Never treat tar extraction success alone as proof that git archive succeeded.
   - **Dynamic Manifest Audit (POSIX Paths Only)**: Validate regular files in staging and active runtime against `git ls-tree -r --name-only <commit>` + `{'DEPLOYED_VERSION.json'}`. Use POSIX relative paths (`item.relative_to(root).as_posix()`); do not use `pathlib.os` or platform-dependent separators. Reject missing files, unexpected files, symlinks, `.pyc`, and `__pycache__`.
   - **Transaction-State Bookkeeping Outside Active Runtime**: Keep deployment state outside `v2`, `v2.previous`, and `v2.staging` (e.g. in `software-factory/deployment-state/exact-definition-discovery-<commit>.json`) to prevent polluting the exact active runtime manifest.
   - **Single Authoritative, Phase-Bound Skill Rollback**:
     - All skill restores must execute strictly via Phase 10; never perform ad-hoc skill copies in Phase 8 failure blocks.
     - Phase 10 rollback must parse the exact `FAILED_PHASE` (7, 8, or 9):
       - `FAILED_PHASE == 7`: Phase 8 was not entered; active skill was never touched (`skill_rolled_back: not_applicable`).
       - `FAILED_PHASE == 8`: If transaction state does not exist, skill modification could not have occurred (Phase 8 writes state before modifying skill) -> safely skip (`skill_rolled_back: not_applicable`). If transaction state exists, perform full verified rollback.
       - `FAILED_PHASE == 9`: Phase 8 completed, so transaction state and `skill_backup_created_this_run == True` are mandatory. Missing state or backup is a fatal rollback failure (`skill_rolled_back: false`, `deployment_status: FAIL`).
     - Prior to restoring, verify `SHA256(backup) == previous_skill_sha256`. After restore, verify `SHA256(target) == previous_skill_sha256`.
     - Retain transaction skill backups (`SKILL.md.bak.<commit>`) alongside `v2.previous` for the full release cycle.
   - **Deterministic Export**: Extract releases strictly from the verified commit into a staging directory first (`v2.staging`) using `git -c core.autocrlf=false archive`.
   - **Staging Validation Gate**:
     - Verify 100% of tracked file checksums against `SHA256SUMS`.
     - Verify `DEFAULT_BUILDER_MODEL == "gemini-3.8-flash-high"`.
     - Verify AGY executable version (`1.2.2`) and SHA-256 (`80a029a8...`).
     - Verify wrappers resolve to the active `v2` target with `python -B`; fail-closed with immediate ABORT on wrapper error.
   - **Promotion Sequence & Coupled Skill Rollback**:
     1. Validate `v2.staging`.
     2. Atomic swap: `v2 -> v2.previous`, `v2.staging -> v2`.
     3. Post-promotion verification: assert BOTH `source_commit` and `source_tree` in `DEPLOYED_VERSION.json`, rerun `SHA256SUMS` against the active promoted `v2`, and verify module imports.
     4. Promote active skill (`docs/software-factory-SKILL.md -> %LOCALAPPDATA%\hermes\skills\...\SKILL.md`) ONLY AFTER runtime promotion passes; backup previous skill to `.bak` and verify the candidate SHA-256 hash.
     5. Offline smoke tests: verify both discovery layer (`discover_exact_python_definition() -> dict`) and surface engine (`FactoryEngine._select_builder_surface()`) separately, ensuring call sites without definitions return `NOT_FOUND` and fixtures avoid leading-indentation syntax bugs.
     6. If any post-promotion or skill step fails, rollback BOTH runtime (`v2.failed -> v2.previous -> v2`) and skill (`SKILL.md.bak -> SKILL.md`).

5. **Hash and Identity Verification Gates**
   - Distinguish **Git tree OID** from **Blob SHA-256**:
     - `git rev-parse <commit>^{tree}` produces the Git Tree object ID (e.g. `d5ee88bd...`).
     - `git show <commit>:<file> | sha256sum` produces the SHA-256 digest of that specific file.
   - Compare runtime file SHA-256 directly against the blob output of Git show, not against the tree OID.
   - Verify AGY runtime executable SHA-256 against `APPROVED_AGY_SHA256` (`80a029a8f22dccc123fd39453bd4d51c93d6384d4f365993a3d5accfa4af4b47`).

6. **Discovery Layer Fail-Closed and Exact Definition Lookup Principles**
   - **Fail-Closed Discovery**: Discovery layer benchmarks must strictly separate `UNIQUE` targets from `MUST_ABSTAIN` decoy targets. `WRONG_TARGET == 0` is an absolute requirement.
   - **3-Tier S1.1 Architecture**: (1) Fast-path S0 explicit `file:line`, (2) Exact AST Definition Lookup: map candidate file via `rg -l` -> match exact `FunctionDef`/`ClassDef`/`method` name -> if single definition, return `UNIQUE` ignoring all call-sites, (3) Fallback Lexical Grep + enclosing AST for body constants/error codes.
   - **Benchmark Conclusion (2026-09-14)**: S1.1 achieved **8/9 UNIQUE (88.9%)**, **3/3 MUST_ABSTAIN (100%)**, **0 WRONG_TARGET**. The gate was officially passed. **Decision: STOP and do NOT adopt ast-grep**. S1.1 solves discovery with zero extra dependencies.

7. **Launcher Wrapper Rules**
   - For subcommands that invoke Astra (`plan`, `run`): inject `--planner-reasoning medium` if the caller did not specify an explicit `--planner-reasoning` or `--planner-reasoning=...`.
   - For `resume`: do not re-inject reasoning; allow the engine to read the persisted `planner_reasoning` from `run_dir/config.json`.
   - Always run Python with `-B` in production wrappers to prevent `.pyc` and `__pycache__` accumulation.
