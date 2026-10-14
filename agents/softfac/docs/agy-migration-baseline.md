# Step 1: Baseline Architecture & Provenance Inventory

## 1. Baseline Commit & Repository Provenance
- Approved source/main checkout: `C:/Users/HH18/Downloads/hermes-software-factory-v2-hoh/hermes-software-factory-v2`
- Dedicated migration worktree: `C:/Users/HH18/Downloads/hermes-software-factory-v2-hoh/migration-worktree`
- Approved baseline commit: `066e885966420b14d470dc159f0ff39acf2099a9`
- Migration branch: `hermes/agy-migration-v2`
- The migration worktree was created from the approved baseline commit. The source/main checkout and migration worktree are distinct repositories/worktree views. The source/main checkout is provenance evidence only during this migration; Step 1 does not reset, clean, overwrite, or merge it.
- Current live source/main HEAD is recorded separately by the review packet and is not asserted here as the approved baseline.
- Baseline commit: `066e885966420b14d470dc159f0ff39acf2099a9`
- Branch: `hermes/agy-migration-v2`
- Commit message: `fix(builder): use diff-fenced and 8192 max output tokens for aider gemini`
- Python runtime: `Python 3.11.16` (64-bit Windows)
- Git runtime: `git version 2.53.0.windows.2`
- Baseline test status: 29 tests pass (`OK` across all suites in baseline `test_factory_v2.py`).

## 2. Complete Baseline Tracked File Hash Inventory (All 19 Files)
All 19 tracked files at baseline commit `066e885966420b14d470dc159f0ff39acf2099a9` verified deterministically via `git ls-tree -r` and blob SHA-256:

| # | File Path | SHA-256 |
|---|---|---|
| 1 | `.gitignore` | `728d8d75e80aabe18881ae12eb67ef02d35335e15f6e2ab630345a0cd5cd693f` |
| 2 | `README.md` | `b4c183eda5466774f515ced753890e4b43dad6135eddf2767f9c30cc0b0346a1` |
| 3 | `SHA256SUMS` | `418f39d517f630c13054f5ba5732dec9e73830fac7cae328d3754f10e157acfc` |
| 4 | `bin/hermes-code-factory-v2` | `1ad5903336180b38176c5d3c8f508910b94d1892db333f899e597f2aa93b1c3f` |
| 5 | `bin/hermes-code-factory-v2.cmd` | `7485a0ab6e23ff5ae093ea2cb094af5adc15e4743d20841bfdbc5240f1502983` |
| 6 | `bridge/agy_bridge.py` | `34fef2349d95f57feb584d64e286c6adc716284bd1a1b5120d70f02123a8280a` |
| 7 | `docs/reference/HOH_PAPER_SUMMARY.txt` | `d74a2aecfaeb873b98545200ee704e3c88bae9e1f4ab5b252a2d4f728d19c1bf` |
| 8 | `docs/reference/HOH_SPEC.md` | `83f9ed58b02f42accc6a9fc90b5cebc64b24c6641ecd6985e45f2c5e3e196a87` |
| 9 | `docs/software-factory-SKILL.md` | `490d3ce374de5e4a8515ae50b03505fb2d24d3ee12dc3396bce412534e6cc02a` |
| 10 | `lib/__pycache__/hermes_factory_v2.cpython-310.pyc` | `166ce8108e47be4df9ed95ee0b55213c893f40f2f0f5af187be09de4aaf9c9a8` |
| 11 | `lib/__pycache__/hermes_factory_v2.cpython-312.pyc` | `f283beee6d7407593382ab810162cf9587acd20fe3e5d29ce16a964ed6bb71c6` |
| 12 | `lib/hermes_factory_v2.py` | `cbd02c65cafd49f76cb3a5da9882b8632ecd05eb032d660b82e7cb4ef3547c91` |
| 13 | `systemd/agy-bridge.service.example` | `df97b7ce08ffe248274111389864f77609b77df1b1af66a7ec4c5f2499763928` |
| 14 | `task_self_improvement.txt` | `73dbdea68eaffcbcfc4aa0988a8e2e500b2721a181d5766f92fc8f5096368a4d` |
| 15 | `tests/__pycache__/test_factory_v2.cpython-310-pytest-9.0.2.pyc` | `5f5b39e09212f56f41d1e6cbdbeb6414bc5b989e1b2ca2d072caeeea96caa867` |
| 16 | `tests/__pycache__/test_factory_v2.cpython-310.pyc` | `8e6f8d1e6feb1444187bba7b1e3eabd05f2b8c02f87745d236ad65055a331706` |
| 17 | `tests/__pycache__/test_factory_v2.cpython-311.pyc` | `28c548862d02bcdc0f651b6dd0b7be86944e92d1740ef1883bdbb228443822c0` |
| 18 | `tests/__pycache__/test_factory_v2.cpython-312-pytest-9.1.1.pyc` | `86ee02d123a3d9631e5fb98bcf55d1ec4675503927ae6dca0557e70102b515f8` |
| 19 | `tests/test_factory_v2.py` | `02e0af43fd0833598f8c33a7d10874fe1647bbeef596eea1bbff80e33c836806` |

## 3. Legacy Aider / LiteLLM Components Scheduled for Retirement
Derived strictly from baseline commit `066e885966420b14d470dc159f0ff39acf2099a9` and active host deployment assets to be retired in Step 13/14:

### A. Core Engine Symbols & Constants (`lib/hermes_factory_v2.py`)
- `DEFAULT_BUILDER_MODEL = "openai/gemini-3.8-flash-high"` (line 40): Default builder model targeting the direct/legacy Aider boundary.
- `DEFAULT_AIDER_MODEL = DEFAULT_BUILDER_MODEL` (line 42): Explicit legacy model alias.
- `DEFAULT_BUILDER_ARCHITECT_MODEL = "openai/gemini-3.8-flash-high"` (line 41): Legacy architect model constant.
- `DEFAULT_AIDER_URL = "http://127.0.0.1:8045/v1"` (line 43): Legacy Aider bridge endpoint.
- `DEFAULT_BRIDGE_URL = "http://127.0.0.1:8045/v1"` (line 44): Legacy bridge endpoint alias.
- `Config.builder_model: str = DEFAULT_BUILDER_MODEL` (line 780): Dataclass field for the builder model.
- `Config.builder_architect_model: str | None = None` (line 782): Retained for loading v2.0 run records; the Lean Builder does not use it.
- `Config.bridge_url: str = DEFAULT_BRIDGE_URL` (line 783): Dataclass field for the bridge endpoint.
- There is **no** `Config.aider_model` field in the approved baseline.
- CLI argument parsing (lines 2439-2445):
  - `--builder-model` (line 2439): required builder model option.
  - hidden `--builder-architect-model` (lines 2440-2444): present with `argparse.SUPPRESS`.
  - `--bridge-url` (line 2445): bridge endpoint option.
  - `--aider-model` is **absent** from baseline CLI parsing.
- `class AiderBuilder` (lines 918-1050): The entire legacy builder implementation executing Aider via subprocess.
- `AiderBuilder.__init__(aider_bin: str | None = None)` (lines 919-920): `aider_bin` is an AiderBuilder member (`self.aider_bin`), not a Config field or CLI argument.
- **AiderBuilder Methods:** The exact baseline methods are `__init__`, `preflight`, and `run`; no `_check_bridge` method exists.
- `clean_aider_generated_artifacts(worktree)` (lines 911-916): Legacy artifact cleanup targets only `.aider.tags.cache.v4` and removes that exact directory if present.
- `AiderBuilder.run()` subprocess execution (lines 969-1047):
  - Subprocess invocation of `aider_bin = "aider"` (line 1008).
  - Sensitive hard-coded Builder credential fallback mechanism: A legacy hard-coded Builder credential fallback exists structurally in `preflight()` (the `api_key` assignment at baseline line 933) and `run()` (the `gemini_token` assignment at baseline lines 1005-1006) when environment variables are unset. It is scheduled for retirement in Step 13; its secret value is intentionally not reproduced.
  - Actual Aider transport argument: `--openai-api-base` (`"--openai-api-base", config.bridge_url`, lines 1026-1027) points Aider to LiteLLM OpenAI-compatible endpoint.
  - CLI arguments passed to Aider, extracted from the baseline `argv` list (lines 1007-1038): `--model`, `--model-metadata-file`, `--model-settings-file`, `--edit-format`, `--yes-always`, `--no-stream`, `--no-auto-commits`, `--no-gitignore`, `--no-add-gitignore-files`, `--no-check-update`, `--no-analytics`, `--no-show-model-warnings`, `--no-restore-chat-history`, `--openai-api-base`, `--input-history-file`, `--chat-history-file`, `--llm-history-file`, `--message-file`, and `--` followed by allowed files.
  - Model metadata and settings files (`model metadata/settings`): `gemini_metadata.json` (lines 991-993) and `gemini_settings.yml` (lines 995-1002).
  - Runtime generated histories (`run_dir`): `aider.input.history`, `aider.chat.history.md`, and `aider.llm.history` (lines 1028-1033). These are distinct from the candidate cache directory.
  - Candidate cache directory: `.aider.tags.cache.v4` (baseline lines 911-916). This is distinct from the run-directory histories.
  - Git ignore pattern: `.aider*` (`.gitignore` line 1). This broad pattern is distinct from both the exact cache directory and the configured history filenames.

### B. Auxiliary Assets, Service Templates & Documentation
- `urllib.error` and `urllib.request` are imported at baseline lines 23-24. They are used by `AiderBuilder.preflight()` for the bridge HTTP request (`urllib.request.Request` line 943), response open (`urllib.request.urlopen` line 949), and bridge error handling (`urllib.error.URLError` line 952); both are retirement surfaces for the legacy bridge-preflight path.
- `README.md`: Active baseline Aider/bridge surface. Lines 10, 26-27, 32, 61-78, and 112 describe the Aider/Gemini builder, `bridge/agy_bridge.py`, `systemd/agy-bridge.service.example`, Aider as a requirement, bridge installation/activation, the expected medium model, and the AI write-authority split. Scheduled for Step 13/14 synchronization.
- `bridge/agy_bridge.py`: Direct OpenAI-compatible `aiohttp` adapter that invokes the `agy` executable; it is not a LiteLLM proxy runner. The baseline source contains `AGY_BIN`, `run_agy_turn`, and `asyncio.create_subprocess_exec`; it does not import or invoke LiteLLM. Scheduled for review/synchronization in Step 13/14.
- `lib/hermes_factory_v2.py` additional active retirement call sites: line 6 (`Hermes -> Sol planner -> Aider/Gemini builder`), line 1061 (`AiderBuilder()` default construction), line 1443 (Aider as Lean Builder instruction), line 1488 (Aider/Gemini Luna repair instruction), and line 1885 (`clean_aider_generated_artifacts` call). These are in addition to the symbol/argv inventory above.
- `task_self_improvement.txt`: Lines 6-8 contain active Aider fenced-diff and allowed-file initialization instructions. Scheduled for Step 13/14 synchronization.
- Repository baseline skill copy `docs/software-factory-SKILL.md`: tracked retirement surface, not modified during Step 1. Exact Aider-related baseline references are: frontmatter description line 3 (`lean Aider/Gemini building`), metadata tags line 10 (`aider`), and overview line 16 (Aider as the lean Gemini builder; Aider context/architect behavior). These tracked references are scheduled for Step 13/14 synchronization.
- `systemd/agy-bridge.service.example`: service template with `ExecStart=/usr/bin/env python3 %h/.hermes/agy_bridge.py` at line 8 and `AGY_BRIDGE_TIMEOUT_SECONDS=600` at line 10; scheduled for Step 13/14 review/removal only after consumer verification.
- Installed host skill copy `C:/Users/HH18/AppData/Local/hermes/skills/software-development/software-factory-v2/SKILL.md`: external deployment inventory surface, not modified during Step 1. Its active Aider compatibility/dispatch rules are cataloged separately below.
- `.gitignore`: Contains `.aider*` exclusion rule for tags and chat history files.
- `SHA256SUMS`: Checksums bundle containing legacy checksums to be updated in Step 14.
- **Tests & Test Mock Infrastructure (`tests/test_factory_v2.py`):** The baseline test method `test_aider_runs_lean_gemini_builder` is at lines 386-410. It exercises the legacy `AiderBuilder` path and mocks the builder command/bridge interaction.
- **Inventory-Only Status:** This installed skill is an external inventory source during Step 1 and is NOT modified in Step 1.
- Active legacy Aider-related references and dispatch instructions cataloged:
  - Line 14: Mentions `AiderBuilder` backward-compatibility alias.
  - Line 34: `Dispatch each approved implementation step to Aider as a separate concise instruction.`
  - Line 37: `Stop immediately if a slice fails, violates scope, or triggers an Aider response-length signal.`
  - Line 63: Mentions `.aider.tags.cache.v4` removal.
  - Lines 75-78: Operational rules on passing files to Aider, context bloat, prompt truncation, and slice sizing.
  - Line 81: Rule on purging `.aider.tags.cache.v4` cache directories.
  - Line 85: Rule on diff boundaries and Aider test-runner interference.
- These items are cataloged for synchronized replacement/removal during Step 13/14.

## 4. Host Environment, Deployment Provenance & Audit Demarcation
- **Verified Absence of Host Launchers:**
  - `where.exe hermes-code-factory`: Not found on PATH (clean host state, verified absence).
  - `where.exe hermes-code-factory-v2`: Not found on PATH (clean host state, verified absence).
- **Installed Software-Factory Skill Location:** `C:/Users/HH18/AppData/Local/hermes/skills/software-development/software-factory-v2/SKILL.md` (present; external deployment inventory only; not modified in Step 1).
- **Installed Python module discovery:** Isolated command `python -I -c "import importlib.util; print(importlib.util.find_spec('hermes_factory_v2'))"` using the host interpreter, with repository paths excluded, returned `None`; `hermes_factory_v2` is verified absent from the isolated host Python environment.
- **Audit Worktree Demarcation:**
  - **Audit Worktree Path:** `C:/Users/HH18/softfac-audit-worktree`
  - **Branch:** `hermes/audit-self-improvement`
  - **HEAD Commit:** `78feff894dab1b3d546dc01b105cec81e07b0c1b`
  - **Working State:** Active development worktree with **staged changes, unstaged changes, and untracked files** (NOT clean).
  - **Policy:** Strictly preserved and isolated. Never mutated, reset, cleaned, stashed, checked out, or committed by migration operations.
  - **Regression Baseline:** Running `python -B -m unittest tests/test_factory_v2.py` in the audit worktree produces: **58 tests run, 57 passed, 1 opt-in skipped, exit code 0**.
- **Audit Protections Cataloged for Selective Porting:**
  The following hardening mechanisms developed in the audit worktree are cataloged for selective architectural porting in later steps (Steps 8, 9, 10):
  - **Per-Slice Editable-File Confinement:** Binding builder prompts and target file sets strictly to the individual slice scope rather than whole-plan `allowed_files` (`_builder_slice_instruction`).
  - **Per-Slice Manifests:** Generating and atomically saving `builder_slices.json` to the durable run directory before dispatch (`action="persist_builder_slices"`).
  - **Per-Call Scope Verification (`_scope_check`; audit source `def _scope_check`):** Rigorous post-slice and post-test check comparing working tree diff against explicit `allowed_files`, recording evidence in `scope_{label}.json` (f-string construction) and failing closed on any out-of-scope modifications.
  - **Per-Call Source-Integrity Verification (`_assert_source_unchanged`):** Validating that the source checkout remains untouched during builder operations in the worktree.
  - **Monotonic / Durable Builder Budget Accounting:** Preserving and validating non-negative step/debug/review counters across process resume to prevent loop reset.
  - **Reservation-Before-Dispatch:** Recording execution manifests, run locks, and baseline status on disk before spawning subprocesses.
  - **Single-Writer Concurrency Locking (`SingleWriterLock`):** File-based run locking (`.run.lock`) preventing concurrent orchestrator instances from colliding on the same candidate run directory.
  - **Durable Rollback & Checkpoint Management:** Implemented by `FactoryEngine._create_checkpoint` (audit source line 2141), not `capture_checkpoint`; binary-safe worktree snapshotting supports rollback on failure.


## 5. Complete Tracked-File Inspection Matrix

Every path returned by `git ls-tree -r --name-only 066e885966420b14d470dc159f0ff39acf2099a9` was inspected. The baseline contains no dependency manifest (`pyproject.toml`, `requirements.txt`, `setup.py`, `Pipfile`, or `package.json`): dependency manifest = **VERIFIED ABSENT**.

| Path | Inspected | Retirement surface | Role / reason |
|---|---:|---:|---|
| `.gitignore` | yes | yes | `.aider*` ignore pattern; distinguish from exact cache and histories. |
| `README.md` | yes | yes | Aider/Gemini role, bridge setup, service installation, requirements, model and write-authority statements. |
| `SHA256SUMS` | yes | yes | Integrity manifest; stale entries are future/non-blocking checksum maintenance. |
| `bin/hermes-code-factory-v2` | yes | yes | Tracked launcher; legacy factory entrypoint and Aider-era dispatch surface. |
| `bin/hermes-code-factory-v2.cmd` | yes | yes | Windows launcher wrapper; tracked deployment/launch surface. |
| `bridge/agy_bridge.py` | yes | yes | Direct aiohttp OpenAI-compatible adapter invoking AGY subprocess; not LiteLLM. |
| `docs/reference/HOH_PAPER_SUMMARY.txt` | yes | no | Reference material; no active Aider/bridge execution role found. |
| `docs/reference/HOH_SPEC.md` | yes | no | Reference specification; no active Aider/bridge execution role found. |
| `docs/software-factory-SKILL.md` | yes | yes | Repository tracked skill copy with Aider/Gemini builder instructions. |
| `lib/__pycache__/hermes_factory_v2.cpython-310.pyc` | yes | yes | Generated tracked runtime artifact associated with legacy module; integrity-only retirement surface. |
| `lib/__pycache__/hermes_factory_v2.cpython-312.pyc` | yes | yes | Generated tracked runtime artifact associated with legacy module; integrity-only retirement surface. |
| `lib/hermes_factory_v2.py` | yes | yes | Constants, Config, AiderBuilder, urllib bridge preflight, argv, prompts, cleanup and dispatch wiring. |
| `systemd/agy-bridge.service.example` | yes | yes | AGY bridge service template: ExecStart, timeout environment, service deployment behavior. |
| `task_self_improvement.txt` | yes | yes | Aider fenced-diff and allowed-file operational instructions. |
| `tests/__pycache__/test_factory_v2.cpython-310-pytest-9.0.2.pyc` | yes | yes | Generated tracked test artifact; integrity-only retirement surface. |
| `tests/__pycache__/test_factory_v2.cpython-310.pyc` | yes | yes | Generated tracked test artifact; integrity-only retirement surface. |
| `tests/__pycache__/test_factory_v2.cpython-311.pyc` | yes | yes | Generated tracked test artifact; integrity-only retirement surface. |
| `tests/__pycache__/test_factory_v2.cpython-312-pytest-9.1.1.pyc` | yes | yes | Generated tracked test artifact; integrity-only retirement surface. |
| `tests/test_factory_v2.py` | yes | yes | Aider builder test and legacy bridge/mock behavior. |

### Explicit Surface and Dependency Evidence
- Repository baseline skill copy = `docs/software-factory-SKILL.md`; installed host skill copy = `C:/Users/HH18/AppData/Local/hermes/skills/software-development/software-factory-v2/SKILL.md`. They are distinct surfaces and neither is modified in Step 1.
- `bridge/agy_bridge.py` is a direct OpenAI-compatible `aiohttp` adapter, not a LiteLLM proxy runner. Its baseline source has `AGY_BIN`, `run_agy_turn`, and `asyncio.create_subprocess_exec`; it does not import or invoke LiteLLM.
- Dependency manifest: **VERIFIED ABSENT**. No `pyproject.toml`, `requirements.txt`, `setup.py`, `Pipfile`, or `package.json` is present in the 19-path baseline tree.

### Additional Exact Baseline Retirement Evidence
- `urllib.error` and `urllib.request`: imported at baseline lines 23-24; used by `AiderBuilder.preflight()` for `urllib.request.Request` line 943, `urllib.request.urlopen` line 949, and `urllib.error.URLError` line 952.
- `README.md`: lines 10, 26-27, 32, 61-78, and 112 cover Aider/Gemini builder role, bridge/service assets, Aider requirement, bridge installation and activation, expected model, and AI write authority.
- `task_self_improvement.txt`: lines 6-8 contain Aider fenced-diff and allowed-file initialization instructions.
- `lib/hermes_factory_v2.py`: additional active sites are line 6 role wiring, line 1061 `AiderBuilder()` construction, line 1443 Aider instruction, line 1488 Aider/Gemini repair instruction, and line 1885 cleanup invocation.
- `systemd/agy-bridge.service.example`: line 8 `ExecStart=/usr/bin/env python3 %h/.hermes/agy_bridge.py`; line 10 `AGY_BRIDGE_TIMEOUT_SECONDS=600`; it is a service template for the legacy bridge operation and is removed only after consumer verification in Step 13.
- `bridge/agy_bridge.py`: the baseline source contains `AGY_BIN`, `run_agy_turn`, and `asyncio.create_subprocess_exec`; it is an aiohttp OpenAI-compatible AGY adapter, not a LiteLLM runner.
- Repository `docs/software-factory-SKILL.md` and installed host `C:/Users/HH18/AppData/Local/hermes/skills/software-development/software-factory-v2/SKILL.md` are separate surfaces; both remain unmodified in Step 1.
