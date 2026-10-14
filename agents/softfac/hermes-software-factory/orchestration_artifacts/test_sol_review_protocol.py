import json
from pathlib import Path
from validate_sol_review_protocol import validate_review

CASES = {
    "stylistic_approve": {
        "review_type": "STEP_CONFORMANCE_REVIEW", "step": 1, "verdict": "APPROVE", "step_status": "PASS", "authorized_for_next_step": True,
        "checklist": [], "blocking_findings": [], "non_blocking_findings": [{"finding_id": "N1", "status": "NON_BLOCKING", "severity": "LOW", "issue": "style", "rationale": "not contractual"}], "candidate_identity": {"base_commit": "b", "head_commit": "h", "tree_oid": "t", "diff_sha256": "d"},
    },
    "explicit_reject": {
        "review_type": "STEP_CONFORMANCE_REVIEW", "step": 1, "verdict": "REJECT", "step_status": "FAIL", "authorized_for_next_step": False,
        "checklist": [], "blocking_findings": [{"finding_id": "B1", "status": "OPEN", "severity": "HIGH", "blocking_class": "FACTUAL_INACCURACY", "contract_source": "Astra Step 1", "exact_requirement": "exact fact", "concrete_evidence": "mismatch", "observed_state": "wrong", "expected_state": "right", "why_it_blocks_current_step": "false evidence", "required_correction": "fix", "correction_class": "MICRO_FIX"}], "non_blocking_findings": [], "candidate_identity": {"base_commit": "b", "head_commit": "h", "tree_oid": "t", "diff_sha256": "d"},
    },
    "future_optional": {
        "review_type": "STEP_CONFORMANCE_REVIEW", "step": 1, "verdict": "APPROVE", "step_status": "PASS", "authorized_for_next_step": True,
        "checklist": [], "blocking_findings": [], "non_blocking_findings": [{"finding_id": "F1", "status": "NON_BLOCKING", "severity": "LOW", "issue": "future", "rationale": "future step"}], "candidate_identity": {"base_commit": "b", "head_commit": "h", "tree_oid": "t", "diff_sha256": "d"},
    },
}

for name, case in CASES.items():
    ok, errors = validate_review(case)
    assert ok, (name, errors)

bad = dict(CASES["stylistic_approve"]); bad["authorized_for_next_step"] = False
assert not validate_review(bad)[0]
bad = dict(CASES["explicit_reject"]); bad["authorized_for_next_step"] = True
assert not validate_review(bad)[0]
bad = dict(CASES["stylistic_approve"]); bad["candidate_identity"] = {"base_commit": ""}
assert not validate_review(bad)[0]
print("Sol constitution protocol fixtures: PASS")
