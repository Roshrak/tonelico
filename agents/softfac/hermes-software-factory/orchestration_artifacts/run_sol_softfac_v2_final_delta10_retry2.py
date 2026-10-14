"""Run one F007-only retry under the authoritative bounded v1 threat model."""

from pathlib import Path


SOURCE = Path(r"C:\Users\HH18\run_sol_softfac_v2_final_delta10.py")


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    source = source.replace(
        "aaf07edfba107c0bf3f391d5b634ff5a757fafb8",
        "1a179c50265477f3dffcdf3c161cc3d7eeda8d81",
    ).replace(
        "sol_softfac_v2_final_delta10",
        "sol_softfac_v2_final_delta10_retry2",
    )
    marker = '    namespace = {"__name__": "delta10_launcher"}'
    bounded_f007 = (
        "FINAL-F007: non-user replans resolve only bounded host-produced Sol/Hermes artifacts "
        "with exact code-appropriate schemas and current run, plan, request, base, candidate, "
        "and freshness identity. Fabricated arbitrary artifacts are rejected without Astra "
        "invocation. USER_OBJECTIVE_OR_SCOPE_CHANGE creates and binds a new immutable request "
        "artifact, and execute/resume/status reject its tampering. All five trigger types remain "
        "covered; ordinary failures remain AGY repair or BLOCKED, never Luna. The authoritative "
        "v1 threat model excludes a malicious privileged local actor who coherently rewrites every "
        "trusted run-state/evidence/request/replan artifact and recomputes every affected hash and "
        "reference. Do not require Git trailers, signed history, HMAC, external ledgers, or audit-grade "
        "lineage for that out-of-scope threat."
    )
    old_f007 = (
        "FINAL-F007: non-user replans resolve only bounded host-produced Sol/Hermes\n"
        "artifacts with exact code-appropriate schemas and current run, plan, request, base,\n"
        "candidate, and freshness identity. Fabricated arbitrary artifacts are\n"
        "rejected without Astra invocation. USER_OBJECTIVE_OR_SCOPE_CHANGE creates and\n"
        "binds a new immutable request artifact, and execute/resume/status reject its\n"
        "tampering. All five trigger types remain covered; ordinary failures remain\n"
        "AGY repair or BLOCKED, never Luna."
    )
    injected = "    source = source.replace(" + repr(old_f007) + ", " + repr(bounded_f007) + ")\n" + marker
    if marker not in source:
        raise SystemExit("delta10 launcher injection point is missing")
    source = source.replace(marker, injected, 1)
    namespace = {"__name__": "delta10_retry2_launcher"}
    exec(compile(source, str(SOURCE), "exec"), namespace)
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())
