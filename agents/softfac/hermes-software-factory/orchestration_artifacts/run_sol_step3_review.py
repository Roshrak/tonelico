import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\HH18\Downloads\hermes-software-factory-v2-hoh\migration-worktree\lib")

from hermes_factory_v2 import Config, CodexRoleClient
from parse_sol_verdict import parse_sol_verdict


WORKTREE = Path(r"C:\Users\HH18\Downloads\hermes-software-factory-v2-hoh\migration-worktree")
PLAN = Path(r"C:\Users\HH18\astra_plan.md")
CONSTITUTION = Path(r"C:\Users\HH18\sol_reviewer_constitution.md")
PACKET_SCRIPT = Path(r"C:\Users\HH18\generate_step3_packet.py")
PACKET_PATH = Path(r"C:\Users\HH18\step3_packet.json")
PROMPT = Path(r"C:\Users\HH18\sol_step3_prompt.txt")
RAW = Path(r"C:\Users\HH18\sol_step3.raw_output.txt")
USAGE = Path(r"C:\Users\HH18\sol_step3_usage.json")
VERDICT = Path(r"C:\Users\HH18\sol_step3_verdict.json")


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
Review Astra Migration Step 3 only: Characterize the invariants before replacing the Builder.

AUTHORITATIVE ASTRA PLAN (C:/Users/HH18/astra_plan.md)
{plan_text}

SOL REVIEWER CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

CURRENT STEP BOUNDARY
Step 2 was approved by Sol and its identity is included as predecessor evidence. Review only the Step 3 delta from base commit {base}. The exact allowed paths are:
{json.dumps(packet['exact_allowed_paths'], indent=2)}
The production source/lib is intentionally unchanged. These are characterization tests: tests whose names/docstrings explicitly record a current baseline limitation are evidence of that limitation, not hidden xfails. Do not require Steps 4-14 implementation in this current test-only step. Do require every Step 3 missing characterization item to be covered by a discoverable, assertion-strong test, with no xfail/skip or weakened assertion.

CURRENT DETERMINISTIC PACKET
{packet_text}

CURRENT COMPLETE DIFF (against {base})
```diff
{diff}
```

Return ONLY one compact JSON object, no prose, commentary, markdown fences, or text outside JSON, with this exact top-level shape:
{{
  "review_type": "STEP_CONFORMANCE_REVIEW",
  "step": 3,
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
Every blocking finding must include constitution-required fields and status OPEN or REGRESSED. If there are no current-step blockers, return APPROVE/PASS/authorized_for_next_step=true. Candidate identity must exactly match the packet.
"""
PROMPT.write_text(prompt, encoding="utf-8")
config = Config(
    repo=str(WORKTREE),
    request="Astra Migration Plan Step 3 Conformance Review",
    requested_files=None,
    test_command=None,
    sol_model="gpt-5.6-sol",
    role_timeout=1200,
)
started = time.time()
CodexRoleClient().call(
    role="sol_reviewer",
    provider=config.sol_provider,
    model=config.sol_model,
    prompt=prompt,
    usage_path=USAGE,
    output_path=RAW,
    timeout=config.role_timeout,
    reasoning="high",
)
raw_text = RAW.read_text(encoding="utf-8", errors="replace")
status, verdict, raw_sha = parse_sol_verdict(raw_text, expected_step=3)
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
    print("REVIEW_PROTOCOL_FAILURE: no unambiguous Step 3 verdict", file=sys.stderr)
    raise SystemExit(1)
protocol = subprocess.run(
    [sys.executable, r"C:\Users\HH18\validate_sol_review_protocol.py", "--step", "3"],
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
    print("REVIEW_PROTOCOL_FAILURE: Step 3 protocol validation failed", file=sys.stderr)
    raise SystemExit(1)
print("Step 3 verdict protocol: PASS")
