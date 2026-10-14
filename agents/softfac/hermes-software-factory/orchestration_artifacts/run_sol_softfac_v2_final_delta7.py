"""Run the next single bounded final delta recheck without mutating prior evidence."""

from __future__ import annotations

from pathlib import Path


SOURCE = Path(r"C:\Users\HH18\run_sol_softfac_v2_final_delta5.py")


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    replacements = {
        "d8f425f136d7a9e010bfaf0fd494506d0cb13682": "6bff5ccdefee718d848397a2fa2d81ebe45dff75",
        "sol_softfac_v2_final_delta4_verdict.json": "sol_softfac_v2_final_delta6_verdict.json",
        "sol_softfac_v2_final_delta5.raw_output.txt": "sol_softfac_v2_final_delta7.raw_output.txt",
        "sol_softfac_v2_final_delta5.stderr.txt": "sol_softfac_v2_final_delta7.stderr.txt",
        "sol_softfac_v2_final_delta5_usage.json": "sol_softfac_v2_final_delta7_usage.json",
        "sol_softfac_v2_final_delta5_verdict.json": "sol_softfac_v2_final_delta7_verdict.json",
        "previous final delta4": "previous final delta6",
        "PREVIOUS FINAL DELTA4": "PREVIOUS FINAL DELTA6",
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    namespace = {"__name__": "delta7_launcher"}
    exec(compile(source, str(SOURCE), "exec"), namespace)
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())
