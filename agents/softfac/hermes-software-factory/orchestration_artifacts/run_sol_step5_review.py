import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2\lib")

from hermes_factory_v2 import Config
from parse_sol_verdict import parse_sol_verdict


WORKTREE = Path(r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2")
PLAN = Path(r"C:\Users\HH18\astra_plan.md")
CONSTITUTION = Path(r"C:\Users\HH18\sol_reviewer_constitution.md")
PACKET_SCRIPT = Path(r"C:\Users\HH18\generate_step5_packet.py")
PACKET_PATH = Path(r"C:\Users\HH18\step5_packet.json")
PROMPT = Path(r"C:\Users\HH18\sol_step5_prompt.txt")
RAW = Path(r"C:\Users\HH18\sol_step5.raw_output.txt")
RAW_STDERR = Path(r"C:\Users\HH18\sol_step5.stderr.txt")
USAGE = Path(r"C:\Users\HH18\sol_step5_usage.json")
VERDICT = Path(r"C:\Users\HH18\sol_step5_verdict.json")


env = os.environ.copy()
env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
packet_proc = subprocess.run(
    [sys.executable, "-B", str(PACKET_SCRIPT)],
    cwd=WORKTREE,
    env=env,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    check=False,
)
if packet_proc.returncode:
    print(packet_proc.stdout)
    print(packet_proc.stderr, file=sys.stderr)
    raise SystemExit(packet_proc.returncode)
packet_text = packet_proc.stdout.strip()
packet = json.loads(packet_text)
PACKET_PATH.write_text(packet_text + "\n", encoding="utf-8")
base = packet["base_commit"]
diff = subprocess.check_output(
    ["git", "-C", str(WORKTREE), "diff", f"{base}..HEAD"],
    text=True,
    encoding="utf-8",
)
plan_text = PLAN.read_text(encoding="utf-8")
constitution_text = CONSTITUTION.read_text(encoding="utf-8")
constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()

prompt = f"""You are Sol Reviewer (gpt-5.6-sol), the independent gatekeeper for the Human-Out-of-the-Loop Software Factory v2.
Review Astra Migration Step 5 only: Implement executable resolution and capability preflight.

AUTHORITATIVE ASTRA PLAN (C:/Users/HH18/astra_plan.md)
{plan_text}

SOL REVIEWER CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

CURRENT STEP BOUNDARY
Step 4 was approved and its exact identity is supplied as predecessor evidence. Review only the Step 5 delta from base commit {base}. Allowed paths are exactly:
{json.dumps(packet['exact_allowed_paths'], indent=2)}
Step 5 is executable resolution and capability preflight. Do not require Step 6 process supervision, Step 7 editing/result parser, Step 8 dispatcher, or Steps 9-14 runtime/deployment/retirement changes. The old Aider class may remain temporarily for Step 13, but AgyBuilder itself must be direct-CLI-only and must not use the legacy HTTP bridge or API-key fallback.

Check, with concrete evidence:
1. explicit --agy-bin, PATH agy, and Windows LOCALAPPDATA fallback resolution order;
2. invalid explicit paths never fall back; absolute native executable pinning rejects directories and shell shims;
3. strict bare semantic version and supported 1.2.0 identity plus binary SHA-256;
4. required help capabilities and strict model catalog parsing with exact gemini-3.8-flash-high entry;
5. bounded no-edit disposable-cwd probe with direct AGY argv, fresh stream evidence, exact model/cwd, one init/result, consistent conversation, successful completion, and sanitized persisted preflight_builder.json;
6. fail-closed negative tests and no source/main/audit mutation.
The packet's preflight evidence may reuse the approved Step 2 Windows Sandbox
and authenticated-runtime fixtures when a fresh guest output was already
host-attested; do not demand an unsafe unrestricted host probe.

CURRENT DETERMINISTIC PACKET
{packet_text}

CURRENT COMPLETE DIFF (against {base})
DIFF START
{diff}
DIFF END

Return ONLY one compact JSON object whose first character is '{' and last character is '}'. Do not emit the word 'codex', a role/channel label, prose, commentary, markdown fences, or any text outside JSON. Use this exact top-level shape:
{{
  "review_type": "STEP_CONFORMANCE_REVIEW",
  "step": 5,
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
Blocking findings require every constitution-required field and status OPEN or REGRESSED. If no current-step blockers remain, return APPROVE/PASS/authorized_for_next_step=true. Candidate identity must exactly match the packet.
"""
PROMPT.write_text(prompt, encoding="utf-8")
config = Config(
    repo=str(WORKTREE),
    request="Astra Migration Plan Step 5 Conformance Review",
    requested_files=None,
    test_command=None,
    sol_model="gpt-5.6-sol",
    role_timeout=1200,
)
started = time.time()
codex_bin = shutil.which("codex") or "codex"
argv = [
    codex_bin,
    "exec",
    "--ephemeral",
    "--skip-git-repo-check",
    "-m",
    config.sol_model,
    "-c",
    'model_reasoning_effort="high"',
    "-",
]
try:
    result = subprocess.run(
        argv,
        cwd=USAGE.parent,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=config.role_timeout,
        check=False,
    )
except subprocess.TimeoutExpired as exc:
    raise SystemExit(f"Sol invocation timed out after {config.role_timeout}s") from exc

# Keep the model's machine-readable stdout separate from the CLI transcript.
# The latter may contain tool output, old-artifact text, and terminal labels.
RAW.write_text(result.stdout or "", encoding="utf-8")
RAW_STDERR.write_text(result.stderr or "", encoding="utf-8")
USAGE.write_text(
    json.dumps(
        {
            "role": "sol_reviewer",
            "provider": config.sol_provider,
            "model": config.sol_model,
            "reasoning": "high",
            "completed": result.returncode == 0,
            "failed": result.returncode != 0,
        },
        indent=2,
    ),
    encoding="utf-8",
)
if result.returncode != 0:
    raise SystemExit("Sol invocation failed; inspect the separate stderr artifact")

raw_text = RAW.read_text(encoding="utf-8", errors="replace")
stripped = raw_text.strip()
status = "REVIEW_PROTOCOL_FAILURE"
verdict = None
raw_sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
if stripped.startswith("{") and stripped.endswith("}"):
    try:
        exact_object = json.loads(stripped)
    except json.JSONDecodeError:
        exact_object = None
    parsed_status, parsed_verdict, _ = parse_sol_verdict(stripped, expected_step=5)
    if parsed_status == "SUCCESS" and parsed_verdict == exact_object:
        status = "SUCCESS"
        verdict = exact_object
metadata = {
    "parsing_status": status,
    "raw_output_sha256": raw_sha,
    "raw_output_path": str(RAW).replace("\\", "/"),
    "constitution_version": "1.0.0",
    "constitution_sha256": constitution_sha,
    "review_mode": "STEP_CONFORMANCE_REVIEW",
    "elapsed_seconds": round(time.time() - started, 1),
    "verdict": verdict,
}
VERDICT.write_text(json.dumps(metadata if status != "SUCCESS" else verdict, indent=2), encoding="utf-8")
if status != "SUCCESS":
    print("REVIEW_PROTOCOL_FAILURE: no unambiguous Step 5 verdict", file=sys.stderr)
    raise SystemExit(1)
protocol = subprocess.run(
    [sys.executable, r"C:\Users\HH18\validate_sol_review_protocol.py", "--step", "5"],
    input=json.dumps(verdict),
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    check=False,
)
print(f"Sol High completed in {time.time() - started:.1f}s")
print(json.dumps(verdict, indent=2))
if protocol.returncode:
    print(protocol.stdout)
    print(protocol.stderr, file=sys.stderr)
    print("REVIEW_PROTOCOL_FAILURE: Step 5 protocol validation failed", file=sys.stderr)
    raise SystemExit(1)
print("Step 5 verdict protocol: PASS")
