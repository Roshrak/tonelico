---
name: softfac-linux-ops
description: Check and operate Hermes Software Factory v2 on this NixOS device with its isolated AGY builder and MCP tools.
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [coding, softfac, linux, agy, mcp, troubleshooting]
---

# SoftFac on Linux

Use this skill when a user asks Hermes to plan, run, inspect, or resume a
Software Factory coding task on this device.

1. Call `factory_health` from `hermes-factory-mcp`. If the AGY hash, version,
   or Bubblewrap check fails, stop and report the exact result. Never bypass
   an identity or isolation gate to make a run proceed.
2. For a new task, identify the Git repository top-level directory, the
   requested objective, the smallest allowed file set, and a deterministic
   test command. Use `factory_plan` to inspect the task graph before
   `factory_execute`, or `factory_run` when the user requested the full run.
3. On failure, use `factory_status` and inspect the run's preflight, attempt,
   test, and review evidence. Resume the same run when its recorded state
   allows it; do not start duplicate runs to work around a failed gate.
4. The Linux Builder sees a disposable mirror at `/workspace`. Its OAuth
   credential is copied into a private one-item keyring in the Bubblewrap
   namespace. The host home, session bus, Git metadata, and run state are
   outside that namespace. Only permitted file edits are synchronized back.
   Python bytecode and pytest caches go to the guest's disposable `/tmp`.
5. The factory creates a task branch. Review its commit and diff before
   merging into the user's branch. The factory never pushes or merges.

The pinned Linux runtime is AGY CLI 1.2.0 with the SHA-256 recorded in the
factory source. An AGY update requires a new capability and isolation audit
before changing that pin. Use `hermes-code-factory-v2 --help` for CLI syntax.
