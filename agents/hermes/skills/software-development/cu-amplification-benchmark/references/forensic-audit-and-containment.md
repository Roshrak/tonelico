# Depth Reference: Forensic Artifact Synchronization & Kernel Containment

Depth reference for `cu-amplification-benchmark`:
- Exact hash verification in `baseline-manifest.json`, `capability-matrix.md`, `baseline-report.md`, `environment-manifest.json`, `run.json`.
- Dynamic recalculation of `sha256` in `artifacts.jsonl` upon any manifest text edit.
- Win32 `CREATE_SUSPENDED` + Job Object containment for 100% leak-proof process termination.
- Strict exact matching (`target == observed`) and omission of display `name` in `mutated_controls`.
