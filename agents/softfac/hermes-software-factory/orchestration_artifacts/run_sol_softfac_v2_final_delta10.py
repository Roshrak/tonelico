"""Run exactly one final delta recheck after the F007 host-lineage repair."""

from __future__ import annotations

from pathlib import Path


SOURCE = Path(r"C:\Users\HH18\run_sol_softfac_v2_final_delta5.py")


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    source = source.replace(
        'TARGETS = ["FINAL-F005", "FINAL-F007"]',
        'TARGETS = ["FINAL-F007"]',
    )
    source = source.replace(
        'if {item.get("finding_id") for item in prior.get("blocking_findings", [])} != set(TARGETS):',
        'blocking_ids = {item.get("finding_id") for item in prior.get("blocking_findings", [])}\n'
        '    if blocking_ids != {"FINAL-F007"}:\n'
        '        raise SystemExit(f"expected exactly FINAL-F007 open, got {sorted(blocking_ids)}")\n'
        '    resolved_ids = {item.get("finding_id") for item in prior.get("resolved_findings", [])}\n'
        '    if "FINAL-F005" not in resolved_ids:\n'
        '        raise SystemExit("FINAL-F005 is not resolved in predecessor verdict")',
    )
    replacements = {
        "d8f425f136d7a9e010bfaf0fd494506d0cb13682": "aaf07edfba107c0bf3f391d5b634ff5a757fafb8",
        "sol_softfac_v2_final_delta4_verdict.json": "sol_softfac_v2_final_delta9_verdict.json",
        "sol_softfac_v2_final_delta5.raw_output.txt": "sol_softfac_v2_final_delta10.raw_output.txt",
        "sol_softfac_v2_final_delta5.stderr.txt": "sol_softfac_v2_final_delta10.stderr.txt",
        "sol_softfac_v2_final_delta5_usage.json": "sol_softfac_v2_final_delta10_usage.json",
        "sol_softfac_v2_final_delta5_verdict.json": "sol_softfac_v2_final_delta10_verdict.json",
        "previous final delta4": "previous final delta9",
        "PREVIOUS FINAL DELTA4": "PREVIOUS FINAL DELTA9",
        "target_findings = FINAL-F005, FINAL-F007": "target_findings = FINAL-F007",
        "this exact repair delta and affected evidence for FINAL-F005 and FINAL-F007.": "this exact repair delta and affected evidence for FINAL-F007. FINAL-F005 is RESOLVED and frozen.",
        "FINAL-F005: Runner result sequence, passed status, return code, normalized\ncommand, result artifact hash, log reference and log hash are independently\nbound to the exact candidate before Sol approval and before Hermes commit.\nThe Sol approval must copy the complete verification contract exactly. Fresh\nexecute, resume, and status terminal paths must reject tampered result fields,\nsequence, command, log contents, artifact hashes, or review verification.\n": "FINAL-F005 is RESOLVED and frozen. Reopen it only for a concrete current-delta REGRESSED finding with reproducible machine-verifiable evidence against the previously approved invariant.\n",
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    source = source.replace(
        'VERDICT.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")',
        'blocking_ids = {item.get("finding_id") for item in verdict.get("blocking_findings", [])}\n'
        '    unexpected = blocking_ids - {"FINAL-F007", "FINAL-F005"}\n'
        '    if unexpected:\n'
        '        raise SystemExit(f"unexpected blocking findings: {sorted(unexpected)}")\n'
        '    for finding in verdict.get("blocking_findings", []):\n'
        '        if finding.get("finding_id") == "FINAL-F005":\n'
        '            if finding.get("status") != "REGRESSED" or not finding.get("concrete_evidence"):\n'
        '                raise SystemExit("FINAL-F005 may only reopen as REGRESSED with concrete evidence")\n'
        '    f007_blocked = "FINAL-F007" in blocking_ids\n'
        '    valid_f005_regression = any(item.get("finding_id") == "FINAL-F005" and item.get("status") == "REGRESSED" and item.get("concrete_evidence") for item in verdict.get("blocking_findings", []))\n'
        '    if verdict.get("verdict") == "APPROVE":\n'
        '        if f007_blocked:\n'
        '            raise SystemExit("APPROVE cannot retain FINAL-F007 blocker")\n'
        '        if verdict.get("step_status") != "PASS" or not verdict.get("authorized_for_next_step") or verdict.get("release_status") != "PASS" or not verdict.get("authorized_for_release"):\n'
        '            raise SystemExit("APPROVE has contradictory release authorization")\n'
        '    if verdict.get("verdict") == "REJECT" and not f007_blocked and not valid_f005_regression:\n'
        '        raise SystemExit("REJECT has no valid current-delta blocker")\n'
        '    VERDICT.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")',
    )
    namespace = {"__name__": "delta10_launcher"}
    exec(compile(source, str(SOURCE), "exec"), namespace)
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())
