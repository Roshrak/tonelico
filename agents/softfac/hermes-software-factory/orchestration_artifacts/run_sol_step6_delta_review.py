"""Run the post-repair DELTA_ONLY_RECHECK for Step 6 finding STEP6-F001."""

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
PACKET_SCRIPT = Path(r"C:\Users\HH18\generate_step6_packet.py")
PACKET_PATH = Path(r"C:\Users\HH18\step6_packet.json")
PRIOR_REVIEW = Path(r"C:\Users\HH18\sol_step6_verdict.json")
PRIOR_HEAD = "1bb56c159dd4a19a41e6645e01e32538ce48d293"
RAW_PATH = Path(r"C:\Users\HH18\sol_step6_delta.raw_output.txt")
STDERR_PATH = Path(r"C:\Users\HH18\sol_step6_delta.stderr.txt")
USAGE_PATH = Path(r"C:\Users\HH18\sol_step6_delta_usage.json")
VERDICT_PATH = Path(r"C:\Users\HH18\sol_step6_delta_verdict.json")


def main() -> int:
    prior = json.loads(PRIOR_REVIEW.read_text(encoding="utf-8"))
    if prior.get("step") != 6 or prior.get("verdict") != "REJECT":
        raise SystemExit("prior Step 6 review is not the required REJECT")
    findings = prior.get("blocking_findings", [])
    target_findings = [item for item in findings if item.get("finding_id") == "STEP6-F001"]
    if len(target_findings) != 1 or target_findings[0].get("status") != "OPEN":
        raise SystemExit("STEP6-F001 is not the single open prior blocker")

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
        raise SystemExit("repair did not advance the candidate HEAD")
    repair_delta_bytes = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", f"{PRIOR_HEAD}..{current_head}"]
    )
    repair_delta = repair_delta_bytes.decode("utf-8")
    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
    prior_identity = prior["candidate_identity"]
    current_identity = {
        key: packet[key] for key in ("base_commit", "head_commit", "tree_oid", "diff_sha256")
    }
    prior_pass_checklist = [
        item for item in prior.get("checklist", []) if item.get("status") == "PASS"
    ]
    repair_mapping = {
        "finding_id": "STEP6-F001",
        "changed_files": [
            "tests/test_factory_builder_process.py",
            "tests/fixtures/builder_process_fixture.py",
        ],
        "correction_performed": (
            "Added an armed descendant readiness marker; cancellation now runs the real "
            "supervisor in a thread and sets cancellation only after the marker; both "
            "containment tests observe beyond the 0.8-second child write deadline; "
            "added an explicit uncontained subprocess control that must create the target."
        ),
        "verification_command": packet["test_command"],
        "verification_result": packet["test_counts"],
        "evidence_sha256": packet["test_output_sha256"],
    }
    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), the independent fail-closed gatekeeper for the Human-out-of-the-Loop Software Factory v2.

review_type = DELTA_ONLY_RECHECK
step = 6
target_finding = STEP6-F001

The initial Step 6 review is complete and its only blocking finding is supplied
below. This is a post-repair delta recheck, not a new full conformance review.
Review only:
- whether STEP6-F001 is RESOLVED;
- the exact repair delta from the prior reviewed candidate to the new candidate;
- the affected deterministic tests/evidence;
- candidate/path identity;
- regressions in the previously PASS Step 6 requirements only where this repair
  touched them.

Do not reopen unrelated PASS requirements. A new blocker is allowed only if the
repair introduced it or concrete hidden evidence proves an actual defect; state
why it was not part of the prior review and use PRECEDENT_CORRECTION if an
interpretation changed. Preserve the exact finding ID and classify it
RESOLVED, OPEN, REGRESSED, or SUPERSEDED.

AUTHORITATIVE ASTRA PLAN
{plan_text}

SOL REVIEWER CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

PRIOR REVIEW ARTIFACT
{json.dumps(prior, indent=2, ensure_ascii=False)}

PRIOR REVIEWED CANDIDATE IDENTITY
{json.dumps(prior_identity, indent=2)}

NEW CANDIDATE PACKET
{packet_text}

NEW CANDIDATE IDENTITY
{json.dumps(current_identity, indent=2)}

EXACT REPAIR DELTA ({PRIOR_HEAD}..{current_head})
DIFF START
{repair_delta}
DIFF END

REPAIR MAPPING
{json.dumps(repair_mapping, indent=2, ensure_ascii=False)}

PREVIOUS PASS CHECKLIST TO PRESERVE
{json.dumps(prior_pass_checklist, indent=2, ensure_ascii=False)}

Return ONLY one compact JSON object whose first character is '{{' and last
character is '}}'. Do not emit role/channel labels, the word codex, prose,
markdown fences, or any text outside JSON. Use exactly this top-level shape:
{{
  "review_type": "DELTA_ONLY_RECHECK",
  "step": 6,
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
If STEP6-F001 is resolved, all affected tests pass, identity matches, and no
previous PASS requirement regressed, return APPROVE/PASS/true with
STEP6-F001 in resolved_findings and no blocking findings.
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
        print("Sol delta invocation timed out after 1200s", file=sys.stderr)
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
                "completed": result.returncode == 0,
                "failed": result.returncode != 0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if result.returncode != 0:
        print("Sol delta invocation failed; inspect sol_step6_delta.stderr.txt", file=sys.stderr)
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
            and candidate.get("step") == 6
            and candidate.get("verdict") in {"APPROVE", "REJECT"}
        ):
            verdict = candidate
            status = "SUCCESS"
    raw_sha = hashlib.sha256((result.stdout or "").encode("utf-8")).hexdigest()
    metadata = {
        "parsing_status": status,
        "raw_output_sha256": raw_sha,
        "raw_output_path": str(RAW_PATH).replace("\\", "/"),
        "stderr_output_path": str(STDERR_PATH).replace("\\", "/"),
        "constitution_version": "1.0.0",
        "constitution_sha256": constitution_sha,
        "review_mode": "DELTA_ONLY_RECHECK",
        "step": 6,
        "target_finding": "STEP6-F001",
        "elapsed_seconds": round(time.time() - started, 1),
        "verdict": verdict,
    }
    VERDICT_PATH.write_text(
        json.dumps(verdict if status == "SUCCESS" else metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if status != "SUCCESS":
        print("REVIEW_PROTOCOL_FAILURE: delta stdout was not one JSON verdict", file=sys.stderr)
        return 1
    validation = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", r"C:\Users\HH18\validate_sol_review_protocol.py", "--step", "6"],
        input=json.dumps(verdict),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    print(f"Sol Delta High completed in {time.time() - started:.1f}s")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(validation.stdout, end="")
    if validation.returncode != 0:
        print("REVIEW_PROTOCOL_FAILURE: delta schema validation failed", file=sys.stderr)
        print(validation.stderr, file=sys.stderr, end="")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
