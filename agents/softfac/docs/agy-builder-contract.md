# AGY Builder Contract — Astra Migration Step 2 and M3 Runtime Pin

Status: **Step 2 evidence is retained as historical contract evidence; M3
activates the separately audited AGY 1.2.2 executable identity below.** The
1.2.0 fixture paths in this document remain historical observations and are not
the active runtime pin.

## 0. Active M3 runtime identity

The production preflight accepts only the exact identity recorded in source:

| Item | Active value | Evidence |
|---|---|---|
| Executable | `C:/Users/HH18/AppData/Local/agy/bin/agy.exe` | host-local CLI probe |
| Version | `1.2.2` | bare `agy.exe --version` stdout |
| SHA-256 | `80a029a8f22dccc123fd39453bd4d51c93d6384d4f365993a3d5accfa4af4b47` | host-local file hash |
| Required model | `gemini-3.8-flash-high` | host-local `agy.exe models` |

This identity update does not reinterpret or rewrite the retained 1.2.0
fixtures. The active preflight still independently verifies capabilities,
model catalog, fresh completion, effective `cwd`, and the approved isolation
boundary before dispatch. A version/hash probe alone is not live-runtime or
containment evidence.

Step 2 establishes the contract that must be satisfied before Hermes can rely
on direct `agy.exe` execution. Observed CLI facts, executed capability probes,
and later implementation gaps are kept separate.

## 1. Observed CLI facts

The local executable observed for this increment is:

| Item | Observation | Evidence |
|---|---|---|
| Executable | `C:/Users/HH18/AppData/Local/agy/bin/agy.exe` | local `--version`/help probe |
| Version | `1.2.0` | bare semantic-version stdout |
| Required model | `gemini-3.8-flash-high` is listed | local `agy.exe models` |
| Print mode | `--print` and `--prompt` are available | local help |
| Structured output | `--output-format stream-json` is available | local help |
| Permission flag | `--dangerously-skip-permissions` auto-approves tool permission requests | local help |
| Slash-command flag | `--disable-slash-commands` is available | local help |
| CLI deadline | `--print-timeout` is available | local help |
| CLI sandbox flag | `--sandbox` is available and describes terminal restrictions | local help only |
| Conversation reuse | `--continue` and `--conversation` are available | local help |
| Extra workspace roots | `--add-dir` is available | local help |
| Unsupported probe label | `agy help headless` returned `unknown subcommand: headless` | negative local probe |

A bounded no-edit print probe also completed with exit code `0`. Its sanitized
evidence is in `tests/fixtures/agy/1.2.0/runtime_probe.json`. The `init` event
reported the exact model, the disposable probe `cwd`, 57 available tools, and
`permission_mode=always-proceed`; four NDJSON events terminated in a
`result.status=SUCCESS` with one turn and the expected sentinel response. The
conversation identity was consistent across the events. The prompt prohibited
all tool calls, so this proves only the basic stream/completion path and
effective model/cwd for that no-edit turn. It does not prove containment,
timeout/cancellation behavior, or discovery isolation. The CLI also warned
that `--mode plan` has no effect while slash-command expansion is disabled.

A bounded `--print-timeout 1s` probe is recorded in
`tests/fixtures/agy/1.2.0/timeout_probe.json`. AGY returned exit code `0`, but
the structured result had zero turns and stderr reported that the print timed
out and returned partial output. This is an explicit parser requirement: exit
code `0` must not be accepted as completion without terminal-result and
timeout evidence.

A second probe ran inside Windows Sandbox with the candidate/output mappings
writeable and source, migration, Git, trusted, review, and unrelated mappings
read-only. Its sanitized boundary evidence is in
`tests/fixtures/agy/1.2.0/sandbox_probe.json`: all protected-host write
attempts were blocked, the protected sentinels stayed unchanged, and the main
and migration HEAD/status snapshots stayed unchanged. The in-candidate
out-of-scope write succeeded as expected and remains the acceptance gate's
responsibility. AGY `--version` returned `1.2.0` inside the sandbox. The live
no-edit turn in that first boundary run returned `ERROR` (`authentication
failed or timed out`), and the sandbox was closed by the probe operator after
its report was written; therefore that fixture is not proof of authenticated
live runtime or outer cancellation/descendant quiescence. A separate
OAuth-authenticated, scratch-only no-edit probe is recorded in
`tests/fixtures/agy/1.2.0/authenticated_runtime_probe.json`; it completed with
the exact model, guest cwd, consistent conversation identity, and a successful
five-event stream. It does not add protected mappings or prove cancellation.

An OAuth-authenticated AGY tool-write probe then ran with the full protected
Windows Sandbox mapping. Its sanitized evidence is in
`tests/fixtures/agy/1.2.0/authenticated_tool_probe.json`: AGY wrote the
authorized candidate file and the deliberate in-candidate out-of-scope file,
while attempts against the mapped main checkout, trusted state, trusted
review artifact, and Git metadata all returned tool errors before a host file
changed. The final stream result was `SUCCESS` with the sentinel
`STEP2_TOOL_PROBE_OK` and empty stderr. This binds the native AGY write tool to
the tested boundary; it does not prove Hermes' future supervisor ownership or
effective discovery isolation.

The direct fresh-runtime probe is recorded in
`tests/fixtures/agy/1.2.0/complete_runtime_probe.json`. It launched two
separate processes with requested `cwd=C:/step2/candidate`; both reported
that effective cwd, the pinned model, `permission_mode=always-proceed`, five
structured events, one turn, and distinct conversation identities. Inside the
confined guest, `mcp list` and `plugin list` were empty and discovery recorded
only names/presence, never file contents.

The deterministic scope-gate result is recorded in
`tests/fixtures/agy/1.2.0/scope_acceptance_probe.json`: the deliberate
in-candidate out-of-scope file was detected and rejected before downstream
gates, while the authorized file remained accepted. This is a fixture-level
acceptance proof; production Hermes still owns the corresponding implementation
in later steps.

The outer-stop probe is recorded in
`tests/fixtures/agy/1.2.0/cancellation_probe.json`. A descendant was armed to
write to the writable candidate after 15 seconds; the host stopped the
Windows Sandbox after its ready marker, waited 20 seconds, and observed no late
write. The protected sentinel stayed unchanged. This proves the tested
Windows Sandbox process-stop path for that disposable fixture; it is not a
claim that Hermes' future supervisor already owns every AGY descendant.

The sanitized source facts are stored in
`tests/fixtures/agy/1.2.0/cli_facts.json`.

## 2. Required invocation contract

The future Hermes adapter must construct an argument list equivalent to:

```text
agy.exe
  --model gemini-3.8-flash-high
  --dangerously-skip-permissions
  --output-format stream-json
  --disable-slash-commands
  --print-timeout 90s
  --print "Run only the current bounded step using the supplied editable files and report completion."
```

The adapter must resolve and pin an absolute executable before dispatch. It
must use `shell=False`, a non-interactive stdin, and the exact disposable
candidate directory as `cwd`. Options must precede the final prompt argument.
The prompt must be bounded, contain no NUL, and contain only the current
objective, allowed files, and relevant constraints.

The following are prohibited until separately audited and explicitly modeled:

- `--continue`, `--conversation`, `--project`, `--new-project`, or `--add-dir`;
- inherited workspace/configuration overrides that add another writable root;
- API-key or bridge fallbacks, automatic installation/login/update, and model
  substitution;
- Builder staging, committing, resetting, merging, changing refs, or writing
  trusted run/review state.

`--dangerously-skip-permissions` is an operation-approval switch. It is not an
isolation mechanism. Likewise, `cwd`, prompt instructions, and the presence of
`--sandbox` are not proof that native file tools or descendant processes are
confined.

## 3. Two independent boundaries

### 3.1 Execution isolation

The process boundary must allow authoritative writes only inside the disposable
candidate root. The probe also uses a host-backed output folder, but that
folder is explicitly untrusted guest output: AGY may write it, the host reads
it only after writer quiescence, and no review or commit decision trusts its
contents without host attestation. The process boundary must prevent direct or
descendant writes to:

- the approved source/main checkout;
- the linked worktree's shared Git directory, index, refs, config, and hooks;
- Hermes run state, ledgers, checkpoints, approvals, review packets, and logs;
- unrelated host paths, credentials, user configuration, and service files.

The Windows boundary was established before the executed probes, not inferred
from a post-run status check. The selected boundary is Windows Sandbox with
read-only protected mappings, writeable candidate plus untrusted-output
mappings, and a
process-stop descendant check. Exact configuration, controller hashes, exit
codes, output hashes, and invariant mapping are in
`tests/fixtures/agy/1.2.0/step2_evidence_manifest.json`. The active Hermes
supervisor now owns the bounded process lifecycle and fail-closed
writer-quiescence checks; the retained fixture remains evidence for the
boundary itself, not a substitute for those production checks.

### 3.2 Candidate acceptance scope

Even inside an isolated candidate, Hermes must independently reject changes
outside the plan's `allowed_files` and the current slice's editable-file set.
The runner owns snapshots, scope checks, source-integrity checks, tests,
review evidence, staging, and commit decisions. A prompt or a clean-looking
status output cannot replace these checks.

## 4. Discovery and evidence contract

Before a production dispatch, the preflight must record sanitized evidence for:

1. resolved executable path, exact version, and binary identity;
2. exact model catalog entry and effective model;
3. effective `cwd` and every additional workspace root;
4. CLI/configuration roots, repository rules, hooks, plugins, MCP servers,
   credential discovery, and log/state locations;
5. fresh-conversation identity (no implicit resume);
6. stream event/result shape, terminal completion, non-zero exit, malformed
   output, timeout, cancellation, and output-overflow behavior;
7. files created outside the candidate during and after cancellation;
8. parent and descendant process termination after timeout/cancellation.

Evidence must be machine-readable, retained outside the candidate, and bound
to the pinned executable identity. Generated prose claiming success is not
completion evidence.

## 5. Disposable probe matrix

The sanitized matrix in
`tests/fixtures/agy/1.2.0/isolation_probe_matrix.json` defines the required
cases:

- an allowed candidate edit;
- an out-of-scope candidate edit;
- a source-checkout write;
- a write to `run_state.json`;
- a write to a trusted review/approval artifact;
- Git index/ref/config/hook mutation;
- a delayed descendant write after cancellation.

Protected-host writes must be blocked by the external execution boundary. An
in-candidate out-of-scope edit may instead be rejected by the independent
candidate-acceptance gate before tests or review. The runner must detect both
classes of unexpected change. The boundary cases were executed and their
sanitized results are recorded in `sandbox_probe.json`; the delayed-child
outer-stop result is recorded in `cancellation_probe.json`. The matrix keeps
the out-of-scope write as `WROTE` because the independent acceptance gate, not
the filesystem boundary, owns that rejection.

## 6. Fail-closed release rule

For this Step 2 contract increment, the independent evidence now covers the
selected Windows Sandbox boundary, native authenticated AGY write attempts,
fresh direct invocations from the candidate cwd, the timeout signal, the
outer-stop delayed-child case, the trusted review-artifact case, and the
deterministic scope gate. Missing or ambiguous containment, completion, or
writer-quiescence evidence remains a blocker for production dispatch. Hermes
must not silently run unrestricted, downgrade to a weaker safety mode, or
switch the production Builder here. M3's active source pin and live preflight
identity are recorded in section 0 above.

Step 2 is retained as the reviewed runtime/isolation contract and
capability-evidence increment. M3 activates the audited runtime identity and
the production supervisor already present in the migration worktree.
Malformed/overflow parser behavior remains covered by the active deterministic
tests. Deployment remains a separate explicitly authorized operation.
