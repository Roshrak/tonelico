---
name: softfac-windows-remediation-automation
description: Use when auto-looping Builder and Sol in SoftFac v2.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, automation, builder, reviewer, windows, remediation]
---

# SoftFac v2 Automated Batch Remediation Protocol

## 1. Autonomous Orchestration Invariant
- **Fully Autonomous Turn-to-Turn Progression**: When Sol Reviewer rejects or outputs findings, Orchestrator MUST immediately prepare the single-shot prompt and spawn AGY Builder without pausing to ask the user ("bạn có muốn...", "có muốn tôi chuyển cho builder không?").
- The pipeline is self-driving A-Z until 100% findings reach `APPROVED`. Only stop when user credentials, interactive authentication, or hardware access is required.

## 2. Windows Child/Descendant Process Containment (CU-F009)
- Relying on polling (`psutil.process_iter`) or command-line signature matching (`Win32_Process.CommandLine`) fails when intermediate parent processes terminate rapidly before the monitoring thread samples them.
- **Canonical Windows Kernel Solution**: Use Windows Job Objects via `ctypes.WinDLL('kernel32')`:
  - Set `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000` (`JobObjectExtendedLimitInformation = 9`).
  - Call `AssignProcessToJobObject(h_job, h_process)` immediately upon process creation.
  - In `cleanup_all()`, closing the job object handle (`CloseHandle(h_job)`) causes the Windows NT kernel to terminate 100% of children, grandchildren, and detached descendant processes instantly and deterministically.

## 3. Provenance & Manifest Exact Matching (CU-F002)
- Sol Reviewer forensically verifies that `head_commit` and `head_tree` in manifests (`baseline-manifest.json`, `capability-matrix.md`, `baseline-report.md`, `run.json`) match the exact commit under review, not a sibling commit with the same parent.
- Always stage manifest documentation with exact hashes tied to the commit tree being evaluated.
