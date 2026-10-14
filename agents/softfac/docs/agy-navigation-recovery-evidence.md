# AGY Navigation Recovery v1 — Evidence

Status: **implementation candidate; independent Sol review is pending**.
The approved release baseline remains unchanged at commit
`b00ee96c16f61e258a90f34c594eb402ffbad5cb`.

## Runtime identity

| Item | Value |
|---|---|
| AGY | `1.2.2` |
| Executable SHA-256 | `80a029a8f22dccc123fd39453bd4d51c93d6384d4f365993a3d5accfa4af4b47` |
| Model | `gemini-3.8-flash-high` |
| Baseline source bytes | `473765` |
| Baseline source SHA-256 | `fd0ce0b56cfce3b82e21773f64d5cb18fcccfd416449eee942c05d7455b763d5` |

## Independent disposable reproduction

Report: `C:/Users/HH18/agy_navigation_reproduction.json`.
Report SHA-256: `958e0c54f9b8900092b05b2b4d02965ccc0a38605e1ea5a1a193eaa53961ecff`.

| Case | Result | Elapsed | First host-observed write | Changed paths | Unsolicited paths |
|---|---|---:|---:|---|---|
| Tiny | `NO_PATCH` | 58.532s | none | none | none |
| 473 KB full-file blind | `NO_PATCH` | 43.281s | none | none | none |
| 473 KB localized prompt | `SUCCESS` | 38.765s | 32.719s | source file | none |
| Physical single-symbol capsule | `SUCCESS` | 32.969s | 29.563s | `target.py` | none |

The capsule case exposed only the extracted `target.py`, not the original
473 KB source file. Token usage and event counts are recorded only when AGY
emitted them. The previous harness's `first_write_time=0.0` is not reused.

## Interpretation

The sample supports a bounded navigation-recovery hypothesis, but does not
support a reliability percentage, an online learning rule, or an aggressive
early timeout. Production acceptance remains owned by the disposable boundary,
Runner, Sol and exact candidate gates. AGY `SUCCESS` is never sufficient by
itself; unsolicited files and nonzero process exits remain fail-closed.

The first live `AgyBuilder` capsule smoke modified only the disposable target
surface but returned guest exit code `1` alongside a `SUCCESS` terminal stream
after a tool-context error. Hermes rejected synchronization, preserving the
nonzero-exit invariant. This is retained as a limitation, not converted into a
false production PASS.
