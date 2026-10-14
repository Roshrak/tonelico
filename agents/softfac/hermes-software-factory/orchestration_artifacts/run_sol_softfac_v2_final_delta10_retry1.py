"""Run one F007-only retry using the last protocol-valid delta9 verdict."""

from pathlib import Path


SOURCE = Path(r"C:\Users\HH18\run_sol_softfac_v2_final_delta10.py")


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    for old, new in {
        "aaf07edfba107c0bf3f391d5b634ff5a757fafb8": "1a179c50265477f3dffcdf3c161cc3d7eeda8d81",
        "sol_softfac_v2_final_delta10": "sol_softfac_v2_final_delta10_retry1",
    }.items():
        source = source.replace(old, new)
    namespace = {"__name__": "delta10_retry1_launcher"}
    exec(compile(source, str(SOURCE), "exec"), namespace)
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())
