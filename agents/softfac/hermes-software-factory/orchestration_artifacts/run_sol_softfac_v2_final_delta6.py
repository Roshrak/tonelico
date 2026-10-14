"""Run the next single bounded final delta recheck without mutating prior evidence."""

from __future__ import annotations

from pathlib import Path


SOURCE = Path(r"C:\Users\HH18\run_sol_softfac_v2_final_delta5.py")


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    source = source.replace(
        "sol_softfac_v2_final_delta4_verdict.json",
        "__PREVIOUS_FINAL_VERDICT__",
    )
    replacements = {
        "d8f425f136d7a9e010bfaf0fd494506d0cb13682": "a8ead80be8dd34b8e10c9e27dbd9a31ded65db06",
        "sol_softfac_v2_final_delta5.raw_output.txt": "sol_softfac_v2_final_delta6.raw_output.txt",
        "sol_softfac_v2_final_delta5.stderr.txt": "sol_softfac_v2_final_delta6.stderr.txt",
        "sol_softfac_v2_final_delta5_usage.json": "sol_softfac_v2_final_delta6_usage.json",
        "sol_softfac_v2_final_delta5_verdict.json": "sol_softfac_v2_final_delta6_verdict.json",
        "previous final delta4": "previous final delta5",
        "PREVIOUS FINAL DELTA4": "PREVIOUS FINAL DELTA5",
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    source = source.replace(
        "__PREVIOUS_FINAL_VERDICT__",
        "sol_softfac_v2_final_delta5_verdict.json",
    )
    namespace = {"__name__": "delta6_launcher"}
    exec(compile(source, str(SOURCE), "exec"), namespace)
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())
