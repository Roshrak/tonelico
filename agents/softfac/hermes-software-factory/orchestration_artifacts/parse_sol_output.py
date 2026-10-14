import json
from pathlib import Path
import re

raw_path = Path("C:/Users/HH18/sol_migration_conformance.raw_output.txt")
raw_text = raw_path.read_text(encoding="utf-8", errors="replace")
print("Raw length:", len(raw_text))

s = raw_text.strip()
found = False

# Try markdown json fences
fence_blocks = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", s)
for block in reversed(fence_blocks):
    try:
        data = json.loads(block)
        Path("C:/Users/HH18/sol_migration_conformance_verdict.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
        print("Successfully parsed from markdown fence!")
        found = True
        break
    except Exception as e:
        continue

if not found:
    # Try finding the largest outermost valid JSON object
    first_brace = s.find("{")
    last_brace = s.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = s[first_brace:last_brace+1]
        try:
            data = json.loads(candidate)
            Path("C:/Users/HH18/sol_migration_conformance_verdict.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            print("Successfully parsed from outermost braces!")
            found = True
        except Exception as e:
            print("Outermost braces parse error:", e)

if not found:
    print("Could not find valid JSON block. Showing tail 1000 characters:")
    print(s[-1000:])
