"""Run the Step 7 DELTA_ONLY_RECHECK after the F003-F006 repair pass."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


WORKTREE = Path(r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2")
PLAN = Path(r"C:\Users\HH18\astra_plan.md")
CONSTITUTION = Path(r"C:\Users\HH18\sol_reviewer_constitution.md")
PACKET_SCRIPT = Path(r"C:\Users\HH18\generate_step7_packet.py")
PACKET_PATH = Path(r"C:\Users\HH18\step7_packet.json")
PRIOR_REVIEW = Path(r"C:\Users\HH18\sol_step7_verdict.json")
PRIOR_HEAD = "16acfc460945b0b7f37560d668e4bb765474bbc3"
RAW_PATH = Path(r"C:\Users\HH18\sol_step7_delta.raw_output.txt")
STDERR_PATH = Path(r"C:\Users\HH18\sol_step7_delta.stderr.txt")
USAGE_PATH = Path(r"C:\Users\HH18\sol_step7_delta_usage.json")
VERDICT_PATH = Path(r"C:\Users\HH18\sol_step7_delta_verdict.json")


def main() -> int:
    prior = json.loads(PRIOR_REVIEW.read_text(encoding="utf-8"))
    if prior.get("step") != 7 or prior.get("review_type") != "STEP_CONFORMANCE_REVIEW":
        raise SystemExit("prior Step 7 initial review is unavailable")
    previous_findings = prior.get("blocking_findings", [])
    expected_ids = {
        "STEP7-F001",
        "STEP7-F002",
        "STEP7-F003",
        "STEP7-F004",
        "STEP7-F005",
        "STEP7-F006",
    }
    if {item.get("finding_id") for item in previous_findings} != expected_ids:
        raise SystemExit("prior Step 7 finding set does not match the stable review record")
    if any(item.get("status") != "OPEN" for item in previous_findings):
        raise SystemExit("prior Step 7 findings are not all OPEN")

    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    packet_proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", str(PACKET_SCRIPT)],
        cwd=WORKTREE,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if packet_proc.returncode != 0:
        print(packet_proc.stdout, end="")
        print(packet_proc.stderr, file=sys.stderr, end="")
        return packet_proc.returncode
    packet_text = packet_proc.stdout.strip()
    packet = json.loads(packet_text)
    PACKET_PATH.write_text(packet_text + "\n", encoding="utf-8")
    current_head = packet["head_commit"]
    if current_head == PRIOR_HEAD:
        raise SystemExit("repair did not advance the Step 7 candidate")
    repair_delta_bytes = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", f"{PRIOR_HEAD}..{current_head}"]
    )
    repair_delta = repair_delta_bytes.decode("utf-8")
    repair_delta_sha = hashlib.sha256(repair_delta_bytes).hexdigest()
    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
    current_identity = {
        key: packet[key] for key in ("base_commit", "head_commit", "tree_oid", "diff_sha256")
    }
    repair_mapping = [
        {
            "finding_id": "STEP7-F003",
            "changed_files": ["lib/hermes_factory_v2.py", "tests/test_factory_agy_builder.py"],
            "correction": "Require at least one step_update, reserve every observed init conversation hash before terminal acceptance, persist the reservation, and consult prior attempt evidence across Builder instances.",
            "verification": "test_parser_requires_a_step_update_before_terminal_success; test_failed_conversation_is_reserved_across_attempts_and_instances",
        },
        {
            "finding_id": "STEP7-F004",
            "changed_files": ["lib/hermes_factory_v2.py", "tests/test_factory_agy_builder.py"],
            "correction": "Map process-boundary failures to agy_isolation_failed, wrap attempt creation/finalization in BuilderFailure, and expose evidence_path only after persistence.",
            "verification": "test_all_supervisor_failure_classes_map_without_raw_diagnostics; test_attempt_creation_and_finalization_failures_are_structured; test_identity_change_after_process_is_structured",
        },
        {
            "finding_id": "STEP7-F005",
            "changed_files": ["lib/hermes_factory_v2.py", "tests/test_factory_agy_builder.py"],
            "correction": "Use AGY wording in the engine instruction and record the verified unique attempt.json path for every direct AGY builder route.",
            "verification": "test_engine_builder_instruction_and_artifact_reference_are_backend_correct",
        },
        {
            "finding_id": "STEP7-F006",
            "changed_files": ["lib/hermes_factory_v2.py", "tests/test_factory_agy_builder.py"],
            "correction": "Add executable AgyBuilder coverage for the initial stdout/stderr evidence-write failure while retaining the complete stable-code, partial-edit, durable-reuse, artifact, identity-drift, supervisor interaction, production-route, and packet-mapping coverage.",
            "verification": packet["test_counts"],
        },
    ]
    prior_pass_checklist = [
        item for item in prior.get("checklist", []) if item.get("status") == "PASS"
    ]
    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), the independent fail-closed gatekeeper for the Human-out-of-the-Loop Software Factory v2.

review_type = DELTA_ONLY_RECHECK
step = 7
target_findings = STEP7-F001, STEP7-F002, STEP7-F003, STEP7-F004, STEP7-F005, STEP7-F006

The initial Step 7 review is complete. This recheck is limited to the exact
repair delta and affected evidence; do not perform a new full migration or
architecture audit. Classify every prior finding with its exact stable ID.

The repair pass intentionally addressed only F003-F006. F001 and F002 are
SAFETY_BLOCKER findings and remain OPEN; do not mark them resolved or invent a
weaker isolation/provenance substitute. Previously PASS requirements remain
frozen unless this repair produced concrete regression evidence. A new blocker
is permitted only if the repair introduced it or concrete hidden evidence proves
an actual defect; explain why it was absent from the initial review and use
PRECEDENT_CORRECTION if interpretation changed.

AUTHORITATIVE ASTRA PLAN
{plan_text}

SOL REVIEWER CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

PRIOR INITIAL REVIEW (authoritative finding IDs and PASS checklist)
{json.dumps(prior, indent=2, ensure_ascii=False)}

PRIOR REVIEWED CANDIDATE IDENTITY
{json.dumps(prior['candidate_identity'], indent=2)}

NEW CANDIDATE PACKET
{packet_text}

NEW CANDIDATE IDENTITY
{json.dumps(current_identity, indent=2)}

EXACT REPAIR DELTA ({PRIOR_HEAD}..{current_head})
repair_delta_sha256 = {repair_delta_sha}
DIFF START
{repair_delta}
DIFF END

REPAIR MAPPING
{json.dumps(repair_mapping, indent=2, ensure_ascii=False)}

PREVIOUS PASS CHECKLIST TO PRESERVE
{json.dumps(prior_pass_checklist, indent=2, ensure_ascii=False)}

Return ONLY one compact JSON object beginning with '{{' and ending with '}}'.
Do not emit role/channel labels, the word codex, prose, markdown fences, or any
text outside JSON. Use exactly this top-level shape:
{{
  "review_type": "DELTA_ONLY_RECHECK",
  "step": 7,
  "verdict": "APPROVE or REJECT",
  "step_status": "PASS or FAIL",
  "authorized_for_next_step": true,
  "candidate_identity": {{"base_commit": "...", "head_commit": "...", "tree_oid": "...", "diff_sha256": "..."}},
  "checklist": [],
  "blocking_findings": [],
  "resolved_findings": [],
  "non_blocking_findings": [],
  "precedent_corrections": [],
  "next_actions": []
}}
An APPROVE is allowed only if all legitimate blockers are resolved; therefore
F001/F002 must remain OPEN unless the current delta genuinely resolves their
explicit safety requirements (it does not). Preserve prior PASS decisions and
return REJECT with F001/F002 open if they still block Step 7.
"""
    codex_bin = shutil.which("codex") or "codex"
    argv = [
        codex_bin,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "-m",
        "gpt-5.6-sol",
        "-c",
        'model_reasoning_effort="high"',
        "-",
    ]
    started = time.time()
    try:
        result = subprocess.run(
            argv,
            cwd=USAGE_PATH.parent,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1200,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("Sol Step 7 delta invocation timed out after 1200s", file=sys.stderr)
        return 1
    RAW_PATH.write_text(result.stdout or "", encoding="utf-8")
    STDERR_PATH.write_text(result.stderr or "", encoding="utf-8")
    USAGE_PATH.write_text(
        json.dumps(
            {
                "role": "sol_reviewer",
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
                "reasoning": "high",
                "review_type": "DELTA_ONLY_RECHECK",
                "step": 7,
                "completed": result.returncode == 0,
                "failed": result.returncode != 0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if result.returncode != 0:
        print("Sol Step 7 delta invocation failed; inspect sol_step7_delta.stderr.txt", file=sys.stderr)
        return 1
    raw = (result.stdout or "").strip()
    verdict = None
    status = "REVIEW_PROTOCOL_FAILURE"
    if raw.startswith("{") and raw.endswith("}"):
        try:
            candidate = json.loads(raw)
        except json.JSONDecodeError:
            candidate = None
        if (
            isinstance(candidate, dict)
            and candidate.get("review_type") == "DELTA_ONLY_RECHECK"
            and candidate.get("step") == 7
            and candidate.get("verdict") in {"APPROVE", "REJECT"}
        ):
            verdict = candidate
            status = "SUCCESS"
    metadata = {
        "parsing_status": status,
        "raw_output_sha256": hashlib.sha256((result.stdout or "").encode("utf-8")).hexdigest(),
        "raw_output_path": str(RAW_PATH).replace("\\", "/"),
        "stderr_output_path": str(STDERR_PATH).replace("\\", "/"),
        "constitution_version": "1.0.0",
        "constitution_sha256": constitution_sha,
        "review_mode": "DELTA_ONLY_RECHECK",
        "step": 7,
        "target_findings": sorted(expected_ids),
        "elapsed_seconds": round(time.time() - started, 1),
        "verdict": verdict,
    }
    VERDICT_PATH.write_text(
        json.dumps(verdict if status == "SUCCESS" else metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if status != "SUCCESS":
        print("REVIEW_PROTOCOL_FAILURE: Step 7 delta stdout was not one JSON verdict", file=sys.stderr)
        return 1
    validation = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", r"C:\Users\HH18\validate_sol_review_protocol.py", "--step", "7"],
        input=json.dumps(verdict),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    print(f"Sol Step 7 Delta completed in {time.time() - started:.1f}s")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(validation.stdout, end="")
    if validation.returncode != 0:
        print("REVIEW_PROTOCOL_FAILURE: Step 7 delta schema validation failed", file=sys.stderr)
        print(validation.stderr, file=sys.stderr, end="")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
