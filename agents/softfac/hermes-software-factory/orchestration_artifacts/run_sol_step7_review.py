"""Run the one initial Sol High conformance review for Astra Step 7."""

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
RAW_PATH = Path(r"C:\Users\HH18\sol_step7.raw_output.txt")
STDERR_PATH = Path(r"C:\Users\HH18\sol_step7.stderr.txt")
USAGE_PATH = Path(r"C:\Users\HH18\sol_step7_usage.json")
VERDICT_PATH = Path(r"C:\Users\HH18\sol_step7_verdict.json")


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

You are conducting the ONE initial review for Astra Migration Step 7.
review_type = STEP_CONFORMANCE_REVIEW
step = 7

The predecessor Step 6 already has a protocol-valid APPROVE/PASS and is frozen
at the identity supplied in the packet. Review ONLY the Step 7 delta, explicit
Astra Step 7 requirements, and regression of predecessor invariants that Step 7
actually touches. Do not re-audit Steps 1-6 absent concrete regression evidence.
If this review rejects, create stable finding IDs STEP7-F001, STEP7-F002, etc.;
all subsequent reviews for this step will be DELTA_ONLY_RECHECK.

AUTHORITATIVE ASTRA PLAN
{plan_text}

SOL REVIEWER CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

STEP 7 REQUIREMENTS
1. Preserve the exact injected Builder.run signature.
2. Add direct AgyBuilder.run using only the approved AGY stream-json argv and
   the Step 6 bounded supervisor; no bridge/API-key/continue/conversation/project
   fallback or Git authority.
3. Validate labels, canonical disposable candidate cwd, allowed file boundary,
   pinned executable/config identity, and unique attempt artifacts outside the
   candidate before dispatch.
4. Parse untrusted bounded UTF-8 NDJSON strictly: one init, init metadata,
   step updates, one final result, consistent fresh conversation, model/cwd,
   permission/completion metadata, terminal SUCCESS, no duplicates/malformed/
   truncated/unsupported/contradictory evidence.
5. Map spawn/timeout/cancel/protocol/runtime/model/identity/output/isolation
   failures to stable BuilderFailure codes without leaking prompt diagnostics.
6. Test all listed negative statuses, zero-exit error/timeout, wrong model/cwd,
   stale conversation, missing/duplicate final, partial edit failure, and
   response prose containing error/token limit; keep production default and
   existing behavior aligned with the step boundary.

CURRENT DETERMINISTIC PACKET
{packet_text}

CURRENT COMPLETE STEP 7 DIFF (against {base})
DIFF START
{diff}
DIFF END

Return ONLY one compact JSON object, beginning with '{{' and ending with '}}'.
Do not emit role/channel labels, the word codex, prose, markdown fences, or any
text outside JSON. Use exactly this top-level shape:
{{
  "review_type": "STEP_CONFORMANCE_REVIEW",
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
Blocking findings must include all constitution-required fields with status OPEN
or REGRESSED. Candidate identity must exactly match the packet. If no current
Step 7 blocker remains, return APPROVE/PASS/true.
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
        print("Sol Step 7 invocation timed out after 1200s", file=sys.stderr)
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
                "review_type": "STEP_CONFORMANCE_REVIEW",
                "completed": result.returncode == 0,
                "failed": result.returncode != 0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if result.returncode != 0:
        print("Sol Step 7 invocation failed; inspect sol_step7.stderr.txt", file=sys.stderr)
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
            and candidate.get("review_type") == "STEP_CONFORMANCE_REVIEW"
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
        "review_mode": "STEP_CONFORMANCE_REVIEW",
        "step": 7,
        "elapsed_seconds": round(time.time() - started, 1),
        "verdict": verdict,
    }
    VERDICT_PATH.write_text(
        json.dumps(verdict if status == "SUCCESS" else metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if status != "SUCCESS":
        print("REVIEW_PROTOCOL_FAILURE: Step 7 stdout was not one JSON verdict", file=sys.stderr)
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
    print(f"Sol High completed in {time.time() - started:.1f}s")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(validation.stdout, end="")
    if validation.returncode != 0:
        print("REVIEW_PROTOCOL_FAILURE: Step 7 schema validation failed", file=sys.stderr)
        print(validation.stderr, file=sys.stderr, end="")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
