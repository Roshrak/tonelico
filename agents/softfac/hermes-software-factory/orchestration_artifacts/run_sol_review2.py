import urllib.request, json, os

with open('C:/Users/HH18/Downloads/hoh_loop2.diff', 'r', encoding='utf-8', errors='replace') as f:
    diff_text = f.read()

sha256 = '304ff218f1f882773afba865004fd9fae4ceaa795b4801d998973d47781fa0eb'

review_prompt = f"""You are Sol Reviewer. Audit this implementation diff against the plan.
Plan: HoH Progressive Disclosure & Continual Improvement Architecture
1. Objective Classification (capability_growth vs repair)
2. Filesystem Memory Ledger (issue_ledger.json + trajectory.json)
3. Multi-loop Trajectory Tracking with atomic snapshot consistency
4. Prior-Run Context Loading with progressive disclosure & strict truncation
5. Unit and Integration tests in tests/test_factory_v2.py (29 tests passing)

CANDIDATE DIFF:
{diff_text}

CANDIDATE SHA256: {sha256}

REQUIREMENTS:
Return ONLY a valid JSON object matching:
{{
  "decision": "approve" | "reject",
  "sha256": "{sha256}",
  "summary": "...",
  "findings": []
}}
"""

payload = {
    "model": "gpt-5.6-sol",
    "messages": [{"role": "user", "content": review_prompt}],
    "reasoning_effort": "high",
    "response_format": {"type": "json_object"}
}

req = urllib.request.Request(
    "http://localhost:13844/v1/chat/completions",
    headers={"Authorization": "Bearer agt_codex_N0ogpcmP85D728nGpWbVU5YRbdLpCtrA", "Content-Type": "application/json"},
    data=json.dumps(payload).encode("utf-8")
)

res = urllib.request.urlopen(req, timeout=120)
print("Review status:", res.status)
review_json = json.loads(res.read().decode("utf-8"))
content = review_json["choices"][0]["message"]["content"]
print("Review output:\n", content)
