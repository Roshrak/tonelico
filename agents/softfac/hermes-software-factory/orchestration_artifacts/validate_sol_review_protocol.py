import json
from typing import Any

BLOCKING_CLASSES = {
    "EXPLICIT_CONTRACT_VIOLATION",
    "FACTUAL_INACCURACY",
    "SAFETY_INVARIANT_VIOLATION",
    "REQUIRED_EVIDENCE_GAP",
    "EXECUTION_OR_RELEASE_CORRECTNESS",
}
CORRECTION_CLASSES = {
    "MICRO_FIX",
    "NORMAL_REWORK",
    "ARCHITECTURAL_REWORK",
    "SAFETY_BLOCKER",
    "EVIDENCE_REPAIR",
    "NONE",
}


def validate_review(verdict: dict[str, Any], expected_step: int = 1) -> tuple[bool, list[str]]:
    errors: list[str] = []
    required = ["review_type", "step", "verdict", "step_status", "authorized_for_next_step", "candidate_identity", "checklist", "blocking_findings", "non_blocking_findings"]
    for key in required:
        if key not in verdict:
            errors.append(f"missing required field: {key}")

    if verdict.get("step") != expected_step:
        errors.append(f"step must equal {expected_step}")
    if verdict.get("verdict") not in {"APPROVE", "REJECT"}:
        errors.append("verdict must be APPROVE or REJECT")
    if verdict.get("step_status") not in {"PASS", "FAIL"}:
        errors.append("step_status must be PASS or FAIL")

    identity = verdict.get("candidate_identity")
    if not isinstance(identity, dict):
        errors.append("candidate_identity must be an object")
    else:
        for key in ["base_commit", "head_commit", "tree_oid", "diff_sha256"]:
            value = identity.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"candidate_identity.{key} must be a non-empty string")

    authorized = verdict.get("authorized_for_next_step")
    if not isinstance(authorized, bool):
        errors.append("authorized_for_next_step must be boolean")

    blocking = verdict.get("blocking_findings", [])
    if not isinstance(blocking, list):
        errors.append("blocking_findings must be an array")
        blocking = []
    for index, finding in enumerate(blocking):
        for key in ["finding_id", "status", "severity", "blocking_class", "contract_source", "exact_requirement", "concrete_evidence", "observed_state", "expected_state", "why_it_blocks_current_step", "required_correction", "correction_class"]:
            if key not in finding:
                errors.append(f"blocking_findings[{index}] missing {key}")
        if finding.get("status") not in {"OPEN", "REGRESSED"}:
            errors.append(f"blocking_findings[{index}] invalid status")
        if finding.get("blocking_class") not in BLOCKING_CLASSES:
            errors.append(f"blocking_findings[{index}] invalid blocking_class")
        if finding.get("correction_class") not in CORRECTION_CLASSES - {"NONE"}:
            errors.append(f"blocking_findings[{index}] invalid correction_class")

    non_blocking = verdict.get("non_blocking_findings", [])
    if not isinstance(non_blocking, list):
        errors.append("non_blocking_findings must be an array")

    if not blocking and verdict.get("verdict") == "APPROVE":
        if verdict.get("step_status") != "PASS" or authorized is not True:
            errors.append("APPROVE without blockers requires PASS and authorized_for_next_step=true")
    if verdict.get("verdict") == "REJECT":
        if verdict.get("step_status") != "FAIL" or authorized is not False:
            errors.append("REJECT requires FAIL and authorized_for_next_step=false")
    if verdict.get("verdict") == "APPROVE" and authorized is False:
        errors.append("contradictory APPROVE + unauthorized state")
    if verdict.get("verdict") == "REJECT" and authorized is True:
        errors.append("contradictory REJECT + authorized state")
    return not errors, errors


def main() -> None:
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", type=int, default=1)
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    ok, errors = validate_review(payload, expected_step=args.step)
    print(json.dumps({"valid": ok, "errors": errors}, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
