"""Run the next Step 7 DELTA_ONLY_RECHECK from the latest delta artifact."""

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
PRIOR_REVIEW = Path(r"C:\Users\HH18\sol_step7_delta_verdict.json")
RAW_PATH = Path(r"C:\Users\HH18\sol_step7_delta2.raw_output.txt")
STDERR_PATH = Path(r"C:\Users\HH18\sol_step7_delta2.stderr.txt")
USAGE_PATH = Path(r"C:\Users\HH18\sol_step7_delta2_usage.json")
VERDICT_PATH = Path(r"C:\Users\HH18\sol_step7_delta2_verdict.json")


def main() -> int:
    prior = json.loads(PRIOR_REVIEW.read_text(encoding="utf-8"))
    if prior.get("step") != 7 or prior.get("review_type") != "DELTA_ONLY_RECHECK":
        raise SystemExit("latest Step 7 delta review is unavailable")
    prior_findings = prior.get("blocking_findings", [])
    prior_ids = {item.get("finding_id") for item in prior_findings}
    if not prior_ids or any(item.get("status") not in {"OPEN", "REGRESSED"} for item in prior_findings):
        raise SystemExit("latest Step 7 delta has no valid blocking finding set")
    prior_head = prior["candidate_identity"]["head_commit"]

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
    if current_head == prior_head:
        raise SystemExit("Step 7 delta2 has no new candidate")
    delta_bytes = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", f"{prior_head}..{current_head}"]
    )
    delta_text = delta_bytes.decode("utf-8")
    current_identity = {
        key: packet[key] for key in ("base_commit", "head_commit", "tree_oid", "diff_sha256")
    }
    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
    prior_pass = [item for item in prior.get("checklist", []) if item.get("status") == "PASS"]
    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), the independent fail-closed gatekeeper for the Human-out-of-the-Loop Software Factory v2.

review_type = DELTA_ONLY_RECHECK
step = 7

This is the third and final allowed Step 7 delta recheck. The immediately
previous delta review is authoritative. Review only its OPEN/REGRESSED findings,
the exact repair delta, affected deterministic evidence, candidate identity, and
regressions in touched PASS requirements. Do not perform a new full migration
audit or reopen unrelated PASS decisions.

The current repair addresses the remaining bounded normal/evidence findings
from the previous review (especially STEP7-F004 and STEP7-F006). Preserve any
unresolved SAFETY_BLOCKER findings exactly and do not invent a weaker isolation
or provenance substitute. Every prior finding must be classified with its exact
stable ID. A new blocker needs concrete repair-caused evidence or a formal
PRECEDENT_CORRECTION.

AUTHORITATIVE ASTRA PLAN
{plan_text}

SOL REVIEWER CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

IMMEDIATELY PREVIOUS DELTA REVIEW
{json.dumps(prior, indent=2, ensure_ascii=False)}

PREVIOUS REVIEWED IDENTITY
{json.dumps(prior['candidate_identity'], indent=2)}

CURRENT PACKET
{packet_text}

CURRENT IDENTITY
{json.dumps(current_identity, indent=2)}

EXACT REPAIR DELTA ({prior_head}..{current_head})
repair_delta_sha256 = {hashlib.sha256(delta_bytes).hexdigest()}
DIFF START
{delta_text}
DIFF END

PREVIOUS PASS CHECKLIST TO PRESERVE
{json.dumps(prior_pass, indent=2, ensure_ascii=False)}

CURRENT AFFECTED EVIDENCE
{json.dumps({'test_command': packet['test_command'], 'test_counts': packet['test_counts'], 'test_output_sha256': packet['test_output_sha256'], 'invariant_to_test_mapping': packet.get('invariant_to_test_mapping'), 'known_limitations_and_release_blockers': packet.get('known_limitations_and_release_blockers')}, indent=2, ensure_ascii=False)}

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
If legitimate blockers remain, return REJECT/FAIL/false; if every legitimate
blocker is resolved with no regression, return APPROVE/PASS/true. Preserve the
previous SAFETY_BLOCKER findings and all stable IDs.
"""
    codex_bin = shutil.which("codex") or "codex"
    argv = [codex_bin, "exec", "--ephemeral", "--skip-git-repo-check", "-m", "gpt-5.6-sol", "-c", 'model_reasoning_effort="high"', "-"]
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
        print("Sol Step 7 delta2 invocation timed out after 1200s", file=sys.stderr)
        return 1
    RAW_PATH.write_text(result.stdout or "", encoding="utf-8")
    STDERR_PATH.write_text(result.stderr or "", encoding="utf-8")
    USAGE_PATH.write_text(json.dumps({"role": "sol_reviewer", "provider": "openai-codex", "model": "gpt-5.6-sol", "reasoning": "high", "review_type": "DELTA_ONLY_RECHECK", "step": 7, "completed": result.returncode == 0, "failed": result.returncode != 0}, indent=2), encoding="utf-8")
    if result.returncode != 0:
        print("Sol Step 7 delta2 invocation failed; inspect stderr artifact", file=sys.stderr)
        return 1
    raw = (result.stdout or "").strip()
    verdict = None
    status = "REVIEW_PROTOCOL_FAILURE"
    if raw.startswith("{") and raw.endswith("}"):
        try:
            candidate = json.loads(raw)
        except json.JSONDecodeError:
            candidate = None
        if isinstance(candidate, dict) and candidate.get("review_type") == "DELTA_ONLY_RECHECK" and candidate.get("step") == 7 and candidate.get("verdict") in {"APPROVE", "REJECT"}:
            verdict = candidate
            status = "SUCCESS"
    metadata = {"parsing_status": status, "raw_output_sha256": hashlib.sha256((result.stdout or "").encode("utf-8")).hexdigest(), "raw_output_path": str(RAW_PATH).replace("\\", "/"), "stderr_output_path": str(STDERR_PATH).replace("\\", "/"), "constitution_version": "1.0.0", "constitution_sha256": constitution_sha, "review_mode": "DELTA_ONLY_RECHECK", "step": 7, "prior_head": prior_head, "elapsed_seconds": round(time.time() - started, 1), "verdict": verdict}
    VERDICT_PATH.write_text(json.dumps(verdict if status == "SUCCESS" else metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    if status != "SUCCESS":
        print("REVIEW_PROTOCOL_FAILURE: Step 7 delta2 stdout was not one JSON verdict", file=sys.stderr)
        return 1
    validation = subprocess.run([sys.executable, "-X", "utf8", "-B", r"C:\Users\HH18\validate_sol_review_protocol.py", "--step", "7"], input=json.dumps(verdict), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    print(f"Sol Step 7 Delta2 completed in {time.time() - started:.1f}s")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(validation.stdout, end="")
    if validation.returncode != 0:
        print("REVIEW_PROTOCOL_FAILURE: Step 7 delta2 schema validation failed", file=sys.stderr)
        print(validation.stderr, file=sys.stderr, end="")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
