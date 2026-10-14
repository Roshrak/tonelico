import hashlib
import json
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
PACKET_SCRIPT = Path(r"C:\Users\HH18\generate_step2_packet.py")
PROMPT = Path(r"C:\Users\HH18\sol_step2_prompt.txt")
RAW = Path(r"C:\Users\HH18\sol_step2.raw_output.txt")
USAGE = Path(r"C:\Users\HH18\sol_step2_usage.json")
VERDICT = Path(r"C:\Users\HH18\sol_step2_verdict.json")


def git(*args):
    return subprocess.check_output(
        ["git", "-C", str(WORKTREE), *args],
        text=True,
        encoding="utf-8",
    ).strip()


packet_proc = subprocess.run(
    [sys.executable, "-B", str(PACKET_SCRIPT)],
    cwd=WORKTREE,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    env={**__import__("os").environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    check=False,
)
if packet_proc.returncode:
    print(packet_proc.stdout)
    print(packet_proc.stderr, file=sys.stderr)
    raise SystemExit(packet_proc.returncode)
packet_text = packet_proc.stdout.strip()
packet = json.loads(packet_text)
Path(r"C:\Users\HH18\step2_packet.json").write_text(packet_text + "\n", encoding="utf-8")

base = packet["base_commit"]
diff = subprocess.check_output(
    ["git", "-C", str(WORKTREE), "diff", f"{base}..HEAD"],
    text=True,
    encoding="utf-8",
)
constitution_text = CONSTITUTION.read_text(encoding="utf-8")
constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
plan_text = PLAN.read_text(encoding="utf-8")

prompt = f"""You are Sol Reviewer (gpt-5.6-sol), the independent gatekeeper for the Human-Out-of-the-Loop Software Factory v2.
Review Astra Migration Step 2 only: Specify the AGY runtime and isolation contract.

AUTHORITATIVE ASTRA PLAN (C:/Users/HH18/astra_plan.md)
{plan_text}

SOL REVIEWER CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

CURRENT STEP BOUNDARY
The Step 1 candidate was independently approved as APPROVE/PASS and is supplied only as predecessor evidence. Review only the Step 2 delta from base commit {base}. The allowed paths are exactly:
{json.dumps(packet['exact_allowed_paths'], indent=2)}
No production backend switch, source-code change, OS isolation provisioning, credential change, or Step 3-14 work is in scope.

The Step 2 documents intentionally distinguish observed local CLI facts from unverified Windows containment. Decide whether this preparation increment satisfies the current Step 2 contract. Do not treat prompt compliance, cwd, --sandbox help text, or --dangerously-skip-permissions as isolation proof. If actual Windows/descendant/native-tool proof is a current-step prerequisite under the Astra plan, report a blocking REQUIRED_EVIDENCE_GAP rather than upgrading an unverified claim. Do not block on future-step work that the plan does not require for this increment.

CURRENT DETERMINISTIC PACKET
{packet_text}

CURRENT COMPLETE DIFF (against {base})
```diff
{diff}
```

Return ONLY one compact JSON object, with no prose, commentary, markdown fences, or text outside JSON. Use this exact top-level shape:
{{
  "review_type": "STEP_CONFORMANCE_REVIEW",
  "step": 2,
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
Every blocking finding must include all constitution-required fields and status OPEN or REGRESSED. If there are no blocking findings, return APPROVE/PASS/authorized_for_next_step=true. Candidate identity must exactly match the packet.
"""
PROMPT.write_text(prompt, encoding="utf-8")

config = Config(
    repo=str(WORKTREE),
    request="Astra Migration Plan Step 2 Conformance Review",
    requested_files=None,
    test_command=None,
    sol_model="gpt-5.6-sol",
    role_timeout=1200,
)
client = CodexRoleClient()
started = time.time()
verdict_data = client.call(
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
status, verdict, raw_sha = parse_sol_verdict(raw_text, expected_step=2)
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
    print("REVIEW_PROTOCOL_FAILURE: no unambiguous Step 2 verdict", file=sys.stderr)
    raise SystemExit(1)

protocol = subprocess.run(
    [sys.executable, r"C:\Users\HH18\validate_sol_review_protocol.py", "--step", "2"],
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
    print("REVIEW_PROTOCOL_FAILURE: Step 2 protocol validation failed", file=sys.stderr)
    raise SystemExit(1)
print("Step 2 verdict protocol: PASS")
