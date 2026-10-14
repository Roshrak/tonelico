---
name: tiered-agent-architecture
description: "Use when designing tiered multi-agent coding pipelines."
version: 1.0.0
author: Hermes Curator
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Multi-Agent, Codex, Architecture, Planning, Debugging, Code-Review]
---

# Tiered Multi-Agent Coding Architecture

Use this skill when designing, configuring, or running tiered multi-agent software engineering pipelines (such as Hermes Software Factory / SoftFac or custom autonomous agent chains).

## Optimal Role Allocation & Reasoning Levels

In high-assurance coding pipelines, separating planning, building, debugging, and reviewing across specialized models and reasoning tiers maximizes code quality while preventing hallucination and scope drift.

| Role | Ideal Model | Reasoning Effort | Core Responsibility & Rationale |
|---|---|---|---|
| **Planner** | `gpt-6-astra` | `high` (or `max`) | **Zero Out-of-Scope Planning:** Astra delivers 0% out-of-scope violations and top-tier planning benchmarks. Using `high` reasoning conserves 5-hour quota windows while providing deep context lookups to define immutable file boundaries (`candidate_files`), acceptance criteria, and invariant specifications. |
| **Builder** | `Aider + Gemini 3.8 Flash High` | Fast / Native High | **Atomic Step Execution:** Fast, high-throughput code implementation strictly within the boundary files defined by the Planner. Consumes low cost and token budget while executing atomic commits. |
| **Debugger** | `gpt-5.6-luna` | `xhigh` | **Surgical Failure Isolation:** Luna excels at terminal and codebase debugging (Terminal-Bench 2.1: 84.7%). With `xhigh` reasoning, it diagnoses root causes directly from test failures and `git diff` without introducing unsolicited refactoring or scope creep. |
| **Reviewer / Gatekeeper** | `gpt-5.6-sol` | `high` (or `xhigh`) | **Immutable Security & Invariant Audit:** Sol validates candidate diffs against expected SHA256 hashes, ensures all test suites pass, and confirms zero regression before approving git commits. Paired with deterministic pre-review gates, `high` reasoning provides robust verification while preventing quota exhaustion. |

## Execution Guidelines & Tooling Quirks

### 1. OpenAI Codex CLI Integration
- **Version Requirement:** Support for `gpt-6-astra` and updated reasoning tiers requires `@openai/codex >= 0.153.4`. Older CLI versions fail with `Model metadata not found` or return 404 when querying newly rolled-out models.
- **Non-Interactive Windows Subprocesses & Prompt Piping:**
  - When passing short queries in CLI automation, append `</dev/null` to prevent stdin hang:
    ```bash
    codex exec --ephemeral --skip-git-repo-check -m gpt-6-astra "prompt" </dev/null
    ```
  - **Crucial for Long Prompts (Windows Command Line Length Limit):** Windows `cmd.exe` / Win32 `CreateProcess` has a hard command line limit of 8,191 / 32,767 characters (`The command line is too long`). For large prompts (planning requests, codebase summaries), DO NOT pass the prompt as an argv argument. Instead, pass `-` as the argument and stream the prompt via `stdin`:
    ```python
    codex_bin = shutil.which("codex") or "codex"
    cmd = [codex_bin, "exec", "--ephemeral", "--skip-git-repo-check", "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = p.communicate(input=long_prompt, timeout=timeout)
    ```
  - Note: On Windows, `shutil.which("codex")` resolves to `codex.CMD`, which native Win32 `CreateProcess` requires to invoke correctly without `shell=True`.
- **Packaging & Production Handoff Defaults:**
  - When packaging or exporting pipelines for end-users, default Planner to `gpt-5.6-sol` (`xhigh`) or `gpt-6-astra` (`high`), and Reviewer to `gpt-5.6-sol` (`high`). This maintains optimal reasoning depth while safeguarding the 5-hour API quota window from depletion during continuous operation.
- **Reasoning Effort Levels & CLI Syntax:**
  - Pass via CLI config override: `--config 'model_reasoning_effort="<level>"'`.
  - Supported levels:
    - `gpt-6-astra`, `gpt-5.6-luna`: 5 levels (`low`, `medium`, `high`, `xhigh`, `max`).
    - `gpt-5.6-sol`: 6 levels (`low`, `medium`, `high`, `xhigh`, `max`, `ultra`).
- **Integration Test Mock Safety:** When extending role clients with `--reasoning`, ensure engine wrappers inspect the caller signature (`inspect.signature`) before passing `reasoning` kwargs down, preserving compatibility with unit test mocks that do not accept reasoning arguments.

### 2. Live Git Diff vs. Premature Commits
- Builders must not commit directly to the repository during work in progress.
- Debuggers (like Luna) must inspect the live worktree `git diff --binary HEAD --` paired with condensed error logs (`failure_evidence`), keeping the repository history clean until the Reviewer gates the final commit.

### 3. Aider CLI vs. Antigravity CLI (`agy`) for Builder Execution

#### Infeasibility of Direct Google OAuth in Aider for Antigravity:
- **Architecture Barrier:** Aider connects to LLMs via LiteLLM, which only supports standard public Gemini API keys (`GEMINI_API_KEY`) or Google Cloud Vertex AI ADC (`gcloud auth application-default login` with standard GCP billing projects).
- **Proprietary Antigravity Protocol:** Antigravity credentials use an internal Google OAuth client (`antigravity_enterprise`, `project_id: aicode-consumers`) requiring specialized device profiling headers (`machine_id`, `dev_device_id`, `mac_machine_id`) and dynamic session signature caches. LiteLLM cannot synthesize these headers or handle this authentication protocol directly.
- **The Proxy Dependency:** To use Aider with Antigravity accounts, a local proxy bridge (such as `antigravity-tools` on `http://127.0.0.1:8045/v1`) is strictly required to translate between OpenAI API format and Google's internal endpoint. Bypassing the local proxy to authenticate Aider directly with Google OAuth is impossible.

#### Root Causes of Aider Token Limits in SoftFac:
- **Zero-Token Registration Pitfall (`0 of 0 tokens`):** When passing an unmapped model name like `openai/gemini-3.8-flash-high` to Aider via local proxies, LiteLLM cannot look up model costs or context limits and returns empty metadata. Aider then initializes `max_input_tokens = 0` and `max_output_tokens = 0`. In `base_coder.py` (`show_exhausted_error`), Aider calculates token consumption against max tokens (`inp_tokens of max_tokens`). Because `max_tokens == 0`, any prompt triggers `inp_err = 'possibly exhausted context window!'`, falsely logging `Model openai/... has hit a token limit!` and aborting the session.
- **Silent Fallback to `whole` Edit Format:** Without registered model settings, Aider falls back to `whole` format instead of `diff-fenced`. Under `whole` format, the model rewrites 100% of entire files instead of minimal hunk patches, burning 5x–10x output tokens and hitting real output limits.
- **Compounding Context Bloat & Retries:** Aider couples repo map generation (`--map-tokens`), AST indexing, system prompts, whole-file copies (`--file`), and full multi-turn chat history. If a diff hunk or truncated response fails, Aider appends the entire failed transaction into the conversation and retries, multiplying token consumption exponentially.

#### Hardening Aider Configuration (Mandatory When Retaining Aider):
To prevent `hit a token limit` errors when driving Aider with Gemini models over local OpenAI-compatible proxies:
1. **Model Metadata File (`--model-metadata-file`):** Provide an explicit JSON file defining full context and token ceilings:
   ```json
   {
     "openai/gemini-3.8-flash-high": {
       "max_input_tokens": 1048576,
       "max_output_tokens": 65536,
       "input_cost_per_token": 0.0,
       "output_cost_per_token": 0.0,
       "litellm_provider": "openai",
       "mode": "chat"
     }
   }
   ```
2. **Model Settings File (`--model-settings-file`):** Explicitly enforce `diff-fenced` to prevent fallback to `whole`:
   ```yaml
   - name: openai/gemini-3.8-flash-high
     edit_format: diff-fenced
     weak_model_name: openai/gemini-3.8-flash-high
     use_repo_map: true
     examples_as_sys_msg: true
   ```
3. **Deterministic Builder Flags:** Always pass `--no-auto-commits --no-suggest-shell-commands --no-show-model-warnings --yes --exit` and route slice prompts via `--message-file`.

#### Antigravity CLI (`agy`) as Native Alternative:
- Replacing Aider with `agy` (`C:\Users\HH18\AppData\Local\agy\bin\agy.EXE`) eliminates the LiteLLM proxy bridge entirely:
  - **Native Quotas & Windows:** Direct interaction with Google Antigravity backend natively respects full multi-million token context and large output limits of Gemini 3.8 / Claude 4.6 without artificial capping.
  - **Autonomous File Edits:** Using `--mode accept-edits` and `--dangerously-skip-permissions` applies workspace changes directly without relying on fragile diff-block parsing.
  - **Standard Non-Interactive Builder Invocation:**
    ```bash
    agy -p "<builder_prompt>" \
        --model gemini-3.8-flash-high \
        --mode accept-edits \
        --dangerously-skip-permissions
    ```

#### LiteLLM Quirks & Workarounds (If Aider is retained):
When driving Aider CLI programmatically via local proxies (e.g. Agy Bridge, Ollama, LiteLLM proxy) with newer or custom model IDs (such as `openai/gemini-3.8-flash-high`):
- **Explicit `max_output_tokens` Registration:** In model metadata dictionaries, explicitly provide high output token headroom (`max_output_tokens: 65536`, `max_input_tokens: 1048576`). If `max_output_tokens` is omitted or set to 8192, LiteLLM caps completions prematurely:
  ```json
  {
    "openai/gemini-3.8-flash-high": {
      "max_tokens": 65536,
      "max_input_tokens": 1048576,
      "max_output_tokens": 65536,
      "input_cost_per_token": 0.0000003,
      "output_cost_per_token": 0.0000025,
      "litellm_provider": "openai",
      "mode": "chat"
    }
  }
  ```
  ```yaml
  - name: openai/gemini-3.8-flash-high
    edit_format: diff-fenced
    weak_model_name: openai/gemini-3.8-flash-high
    use_repo_map: true
  ```
- **Edit Format Selection:** Use `--edit-format diff-fenced` with `--yes-always` when working with advanced models like Gemini 3.8 Flash High. Bare `diff` format frequently causes parsing mismatches where Aider applies zero edits or generates 0-byte stubs.
- **FastMCP Typing Collision Pitfall:** FastMCP (MCP SDK) parses tool parameters via runtime inspection: `issubclass(param.annotation, Context)`. Never allow builders to add `from __future__ import annotations` into files using FastMCP, as stringified annotations (`'bool'`, `'str'`) cause `TypeError: issubclass() arg 1 must be a class` and crash server discovery.
- **Pre-staging Missing Allowed Files:** If the Planner specifies `allowed_files` that do not yet exist on disk, touch/create stub files in the worktree before invoking Aider. Aider will otherwise skip creating untracked files if diff hunks cannot find an existing file anchor.
- **Binary-Safe Windows Worktree Isolation:** On Windows, do not naively normalize line endings across all files with `.replace(b'\r\n', b'\n')` in git worktree isolation guards. Apply line-ending normalization strictly to verified text files (via git attributes); binary files must be hashed byte-for-byte to prevent masked mutations.
- **Streaming in Automated Subprocesses:** Always add `--no-stream` in non-interactive batch invocations. Certain local gateways or proxies deliver non-standard SSE chunks that trigger premature `FinishReasonLength` in Aider's stream parser.

## Theoretical Foundations & Advanced HoH Patterns

See [`references/hoh-autonomous-software-engineering.md`](references/hoh-autonomous-software-engineering.md) for detailed empirical guidelines based on Shanghai AI Lab's HoH paper (arXiv:2609.01481):
- **Structure beats raw compute:** Iterative micro-sprints with verified checkpoints prevent context drift and catastrophic regressions.
- **Strict permissions (Single-Writer):** Builder has sole code write access; QA has read-only testing access.
- **Filesystem Memory & Versioned Ledgers:** Retain plans, constraints, and audit logs on disk rather than ephemeral context:
  - `MemoryLedger`: Tracks `issue_ledger.json` and `trajectory.json` under durable run directories with SHA-256 integrity and sync sequence checks.
  - `Progressive Disclosure`: Exposes prior-run context via `--prior-run <id>`, summarizing open issues and recent milestones with explicit budget truncation rather than raw context dumps.
  - `File Tree Skeleton Index`: Replaces full codebase dumps with NUL-delimited tracked git tree signatures, saving ~75% Planner context tokens.
  - `Deterministic Pre-Review Gate`: Python-level syntax, AST, and scope validation that intercepts errors before calling expensive Reviewer LLMs.
  - `Safe Rollback Gate`: Uses durable git refs (`refs/factory/checkpoints/*`) and indexed stash restoration to prevent compounding regressions.

### 1. Standardized Task Description & Plan Contract (Sol / Luna Schemas)
When formulating or validating task specifications in tiered architectures (e.g. Sol planning or Luna failure diagnosis), all models and orchestrators must adhere to the fail-closed schema contract:

- **Sol Plan Specification (`sol_plan.json`):**
  ```json
  {
    "objective": "Clear, single-goal technical description of capability growth or repair (non-empty string)",
    "allowed_files": ["Strict list of repository relative paths permitted for edit (string array, subset of candidate boundary)"],
    "implementation_steps": ["Ordered atomic implementation steps (string array)"],
    "acceptance_criteria": ["Unambiguous, verifiable conditions required for review approval (string array)"],
    "recommended_tests": ["Explicit test commands / suites to execute for the Evidence Packet (string array)"],
    "risks": ["Identified failure modes, dependency risks, or boundary caveats (string array)"]
  }
  ```
  *Key invariant:* `allowed_files` acts as a fail-closed scope boundary. If a user defines `--files`, `allowed_files` must be a strict subset; any expansion aborts the run before execution starts.

- **Luna Diagnosis Specification (`luna_diagnosis.json`):**
  ```json
  {
    "root_cause": "Surgical diagnosis of test failure or regression (string)",
    "repair_steps": ["Targeted repair instructions strictly within scope (string array)"],
    "files": ["Subset of allowed_files needing modifications (string array)"],
    "tests_to_rerun": ["Specific test cases to reproduce and verify fix (string array)"]
  }
  ```

### 2. Direct User Mandate: Full Automation Delegation
- When the user directs to engage SoftFac or autonomous multi-agent pipelines for feature building/architecture extensions, **always delegate the iterative build and debug cycle to the multi-agent automation loop (SoftFac / Codex / Aider / subagents)** rather than manually writing all incremental components inline. Manual inline implementations bypass the multi-agent review and evidence verification gates that the user explicitly relies on.

### 3. Pipeline Recovery, Rollback, & Rigorous Smoketesting
When recovering or undoing changes to a software factory / agent pipeline from a known-good backup archive (zip/bundle):
- **Byte-level Verification:** Do not rely solely on timestamps or filenames. Compare file byte sizes or hashes across the archive and working tree to detect silent drift in default parameters, prompts, or cached bytecode (`__pycache__`).
- **Comprehensive Smoketest Battery (Non-Negotiable):** A restore is incomplete until verified with a multi-layered smoketest battery:
  1. **Full Test Suite:** Run the entire test suite (e.g. `pytest -v`) to confirm invariant gates, mock contracts, and schema validators pass.
  2. **CLI Entrypoint Preflight:** Verify all CLI verbs (`--help`, subcommands like `run --help`, `plan --help`) execute with exit code 0.
  3. **Module & Engine Invariants:** Programmatically instantiate core engine classes (`FactoryEngine`, `Config`) in an isolated temporary git workspace to verify helper utilities (`classify_objective`, `build_file_tree_skeleton`, `parse_json_object`, memory ledgers) without unhandled exceptions.


