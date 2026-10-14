import urllib.request, json

diff_path = "C:/Users/HH18/Downloads/hoh_loop2_main.diff"
with open(diff_path, "r", encoding="utf-8") as f:
    diff_text = f.read()

sol_prompt = f"""You are Sol Reviewer, the final fail-closed authority.
Evaluate the candidate git diff for Hermes Software Factory v2 (HoH Iteration 2: MemoryLedger, Issue Ledger, Trajectory Tracking, Objective Classification, Prior Run Progressive Disclosure):
Requirements:
1. Pure Python memory ledger (MemoryLedger) saving versioned snapshots to run_dir/ledger.
2. Trajectory events tracking all phases (planning, building, testing, luna, sol review).
3. Issue lifecycle tracking with fingerprint-based deduplication and regression detection.
4. Objective classification (classify_objective) partitioning tasks into 'capability_growth' vs 'repair' with deterministic policy.
5. Prior-run progressive disclosure context passed to Planner with strict character budgeting.
6. Fail-closed snapshot consistency checks preventing state corruption.
7. Unit tests covering all new features (29 integration tests pass).

Candidate diff:
```diff
{diff_text}
```

Return ONLY a JSON object with:
{{
  "decision": "approve" | "reject",
  "sha256": "45a02f2feab4bceb3c1c70f664dbe13274df6965ee51a1df2e6df725613ffcf5",
  "summary": "<summary>",
  "findings": []
}}
"""

req = urllib.request.Request(
    'http://localhost:13844/v1/chat/completions',
    headers={'Authorization': 'Bearer agt_codex_N0ogpcmP85D728nGpWbVU5YRbdLpCtrA', 'Content-Type': 'application/json'},
    data=json.dumps({
        'model': 'gpt-5.6-sol',
        'messages': [{'role': 'user', 'content': sol_prompt}],
        'reasoning_effort': 'high'
    }).encode('utf-8')
)

res = urllib.request.urlopen(req, timeout=300)
print('Response Status:', res.status)
raw = json.loads(res.read().decode('utf-8'))
content = raw['choices'][0]['message']['content']
print('Sol Review Decision:\n', content)
