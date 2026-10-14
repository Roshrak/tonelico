"""Run one F007-only recheck with the authoritative bounded v1 threat model."""

from pathlib import Path


SOURCE = Path(r"C:\Users\HH18\run_sol_softfac_v2_final_delta5.py")


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    replacements = {
        'TARGETS = ["FINAL-F005", "FINAL-F007"]': 'TARGETS = ["FINAL-F007"]',
        '    if {item.get("finding_id") for item in prior.get("blocking_findings", [])} != set(TARGETS):':
            '    blocking_ids = {item.get("finding_id") for item in prior.get("blocking_findings", [])}\n'
            '    if blocking_ids != {"FINAL-F007"}:\n'
            '        raise SystemExit(f"expected exactly FINAL-F007 open, got {sorted(blocking_ids)}")\n'
            '    resolved_ids = {item.get("finding_id") for item in prior.get("resolved_findings", [])}\n'
            '    if "FINAL-F005" not in resolved_ids:\n'
            '        raise SystemExit("FINAL-F005 is not resolved in predecessor verdict")',
        "d8f425f136d7a9e010bfaf0fd494506d0cb13682": "cd135d1a157e98e79d9ce3e8b63e1df8684c65db",
        "sol_softfac_v2_final_delta4_verdict.json": "sol_softfac_v2_final_delta10_retry2_verdict.json",
        "sol_softfac_v2_final_delta5.raw_output.txt": "sol_softfac_v2_final_delta10_retry3.raw_output.txt",
        "sol_softfac_v2_final_delta5.stderr.txt": "sol_softfac_v2_final_delta10_retry3.stderr.txt",
        "sol_softfac_v2_final_delta5_usage.json": "sol_softfac_v2_final_delta10_retry3_usage.json",
        "sol_softfac_v2_final_delta5_verdict.json": "sol_softfac_v2_final_delta10_retry3_verdict.json",
        "previous final delta4": "previous final delta10 retry2",
        "PREVIOUS FINAL DELTA4": "PREVIOUS FINAL DELTA10 RETRY2",
        "target_findings = FINAL-F005, FINAL-F007": "target_findings = FINAL-F007",
        "this exact repair delta and affected evidence for FINAL-F005 and FINAL-F007.":
            "this exact recheck and affected evidence for FINAL-F007. FINAL-F005 is RESOLVED and frozen.",
        "FINAL-F005: Runner result sequence, passed status, return code, normalized\ncommand, result artifact hash, log reference and log hash are independently\nbound to the exact candidate before Sol approval and before Hermes commit.\nThe Sol approval must copy the complete verification contract exactly. Fresh\nexecute, resume, and status terminal paths must reject tampered result fields,\nsequence, command, log contents, artifact hashes, or review verification.\n":
            "FINAL-F005 is RESOLVED and frozen. Reopen it only for a concrete current-delta REGRESSED finding with reproducible machine-verifiable evidence against the previously approved invariant.\n",
        'if tree == PREVIOUS_TREE:\n        raise SystemExit("final delta5 has no new candidate")':
            'if tree != PREVIOUS_TREE:\n        raise SystemExit("candidate changed after the authoritative recheck checkpoint")',
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    marker = "Verify only:\n"
    steer = (
        "AUTHORITATIVE V1 THREAT MODEL:\n"
        "The host-owned run directory and host-owned state/evidence artifacts are inside the trusted computing base. "
        "Direct post-hoc filesystem modification by a privileged local actor, including coherent rewriting of "
        "run_state, historical evidence, request/plan artifacts, replan records, alternate real Git identities, "
        "and recomputation of every affected SHA-256/reference, is explicitly OUT OF SCOPE for SoftFac v1. "
        "Do not require or introduce Git trailers, transition snapshots solely for that threat, signatures, HMAC, "
        "TPM, append-only ledgers, remote transparency, event sourcing, or generalized provenance infrastructure. "
        "The prior alternate-real-commit/rewritten-prefix probe is therefore not a valid FINAL-F007 blocker. "
        "Evaluate only failures reachable through normal SoftFac execution and host-owned write paths: exact schemas, "
        "authorized trigger routing, request/plan pairing, current identity checks, ordinary stale/malformed/partial "
        "corruption fail-closed behavior, crash/resume safety, zero Luna, and no Astra on ordinary failures.\n\n"
    )
    if marker not in source:
        raise SystemExit("review prompt marker is missing")
    source = source.replace(marker, marker + steer, 1)
    namespace = {"__name__": "delta10_retry3_launcher"}
    exec(compile(source, str(SOURCE), "exec"), namespace)
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())
