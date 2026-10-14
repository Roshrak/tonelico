import json
from pathlib import Path
import re

raw_path = Path("C:/Users/HH18/sol_migration_conformance.raw_output.txt")
raw_text = raw_path.read_text(encoding="utf-8", errors="replace")

s = raw_text.strip()
print("Raw length:", len(raw_text))

# Search for JSON blocks containing 'plan_conformance'
matches = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\"plan_conformance\"[\s\S]*?\})\s*```", s)
if not matches:
    # Maybe raw json without fence
    matches = re.findall(r"(\{[\s\S]*?\"plan_conformance\"[\s\S]*?\})", s)

print(f"Found {len(matches)} candidate matches containing 'plan_conformance'")

found = False
for idx, m in enumerate(matches):
    try:
        data = json.loads(m)
        Path("C:/Users/HH18/sol_migration_conformance_verdict.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
        print(f"Match {idx} parsed successfully!")
        found = True
        break
    except Exception as e:
        print(f"Match {idx} JSON parse error:", e)

if not found:
    print("Finding occurrences of plan_conformance in raw_text...")
    for m in re.finditer(r"\"plan_conformance\"", s):
        start = max(0, m.start() - 200)
        end = min(len(s), m.end() + 500)
        print("Context around match:", s[start:end])
        print("="*40)
