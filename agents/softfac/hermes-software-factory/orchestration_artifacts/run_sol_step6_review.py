"""Run the strict Sol High conformance gate for Astra Migration Step 6."""

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
PROMPT_PATH = Path(r"C:\Users\HH18\sol_step6_prompt.txt")
RAW_PATH = Path(r"C:\Users\HH18\sol_step6.raw_output.txt")
STDERR_PATH = Path(r"C:\Users\HH18\sol_step6.stderr.txt")
USAGE_PATH = Path(r"C:\Users\HH18\sol_step6_usage.json")
VERDICT_PATH = Path(r"C:\Users\HH18\sol_step6_verdict.json")


def main() -> int:
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
    base = packet["base_commit"]
    diff = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", f"{base}..HEAD"],
    ).decode("utf-8")
    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), the independent fail-closed gatekeeper for the Human-out-of-the-Loop Software Factory v2.

Review Astra Migration Step 6 only: Implement the bounded AGY subprocess runtime.
Step 5 has already received a protocol-valid APPROVE/PASS and is supplied as
predecessor evidence. Do not gate Step 6 on Step 7 event parsing, Step 8
dispatch, or any later migration step.

AUTHORITATIVE ASTRA PLAN (C:/Users/HH18/astra_plan.md)
{plan_text}

SOL REVIEWER CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

CURRENT STEP BOUNDARY
Review only the delta from base commit {base}. Allowed paths are exactly:
{json.dumps(packet['exact_allowed_paths'], indent=2)}
The implementation must add only a dedicated run_builder_process helper and
its real fixture tests. AgyBuilder.run remains Step 7 scope and production
cutover must remain unchanged.

Check concretely:
1. argv list, shell=False, exact resolved cwd, explicit UTF-8, closed
   non-interactive stdin, no prompt-bearing argv in errors, and rejection of
   NUL or oversized serialized Windows command lines before spawn;
2. concurrent stdout/stderr draining with bounded retained raw evidence,
   malformed UTF-8 fail-closed behavior, and partial evidence for timeout,
   cancellation, spawn failure, and output overflow;
3. separate outer watchdog/shutdown margin and awaiting all writer termination;
4. Windows Job Object containment assigned before resuming the suspended
   process, plus audited process-group lifecycle on other supported platforms;
5. real subprocess fixture coverage for Unicode paths, spaces, quotes, shell
   metacharacters, large stderr, malformed UTF-8, timeout, cancellation,
   delayed descendant writes, and output exhaustion;
6. no changes outside the three allowed paths, no protected checkout changes,
   no premature Step 7 behavior, and deterministic verification.

CURRENT DETERMINISTIC PACKET
{packet_text}

CURRENT COMPLETE DIFF (against {base})
DIFF START
{diff}
DIFF END

Return ONLY one compact JSON object. Its first character must be '{{' and its
last character must be '}}'. Do not emit the word codex, role/channel labels,
prose, markdown fences, or any text outside the JSON object. Use exactly this
top-level shape:
{{
  "review_type": "STEP_CONFORMANCE_REVIEW",
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
For every blocking finding include finding_id, status OPEN or REGRESSED,
severity, blocking_class, contract_source, exact_requirement,
concrete_evidence, observed_state, expected_state,
why_it_blocks_current_step, required_correction, and correction_class.
If no Step 6 blocker remains, return APPROVE/PASS/true. Candidate identity
must exactly match the packet.
"""
    PROMPT_PATH.write_text(prompt, encoding="utf-8")
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
        print("Sol invocation timed out after 1200s", file=sys.stderr)
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
                "completed": result.returncode == 0,
                "failed": result.returncode != 0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if result.returncode != 0:
        print("Sol invocation failed; inspect sol_step6.stderr.txt", file=sys.stderr)
        return 1

    raw = (result.stdout or "").strip()
    verdict = None
    status = "REVIEW_PROTOCOL_FAILURE"
    if raw.startswith("{") and raw.endswith("}"):
        try:
            candidate = json.loads(raw)
        except json.JSONDecodeError:
            candidate = None
        if isinstance(candidate, dict) and candidate.get("step") == 6 and candidate.get("verdict") in {"APPROVE", "REJECT"}:
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
        "review_mode": "STEP_CONFORMANCE_REVIEW",
        "elapsed_seconds": round(time.time() - started, 1),
        "verdict": verdict,
    }
    VERDICT_PATH.write_text(
        json.dumps(verdict if status == "SUCCESS" else metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if status != "SUCCESS":
        print("REVIEW_PROTOCOL_FAILURE: Step 6 stdout was not one JSON verdict", file=sys.stderr)
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
    print(f"Sol High completed in {time.time() - started:.1f}s")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(validation.stdout, end="")
    if validation.returncode != 0:
        print("REVIEW_PROTOCOL_FAILURE: Step 6 schema validation failed", file=sys.stderr)
        print(validation.stderr, file=sys.stderr, end="")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
