"""Run exactly one final delta recheck after canonical closure gates."""

from __future__ import annotations

from pathlib import Path


SOURCE = Path(r"C:\Users\HH18\run_sol_softfac_v2_final_delta5.py")


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    replacements = {
        "d8f425f136d7a9e010bfaf0fd494506d0cb13682": "d0514305b6a91e169d7be32634174e5541c756a7",
        "sol_softfac_v2_final_delta4_verdict.json": "sol_softfac_v2_final_delta8_verdict.json",
        "sol_softfac_v2_final_delta5.raw_output.txt": "sol_softfac_v2_final_delta9.raw_output.txt",
        "sol_softfac_v2_final_delta5.stderr.txt": "sol_softfac_v2_final_delta9.stderr.txt",
        "sol_softfac_v2_final_delta5_usage.json": "sol_softfac_v2_final_delta9_usage.json",
        "sol_softfac_v2_final_delta5_verdict.json": "sol_softfac_v2_final_delta9_verdict.json",
        "previous final delta4": "previous final delta8",
        "PREVIOUS FINAL DELTA4": "PREVIOUS FINAL DELTA8",
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    namespace = {"__name__": "delta9_launcher"}
    exec(compile(source, str(SOURCE), "exec"), namespace)
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())
