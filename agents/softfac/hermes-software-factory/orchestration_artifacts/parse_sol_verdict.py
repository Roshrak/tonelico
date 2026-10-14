import json
import hashlib
from pathlib import Path
from typing import Tuple, Dict, Any, Optional

def parse_sol_verdict(raw_text: str, expected_step: int = 1) -> Tuple[str, Optional[Dict[str, Any]], str]:
    """
    Robustly extracts the authoritative final JSON verdict from Sol raw output.
    Returns: (status, verdict_dict, sha256_hash)
    Status is one of: 'SUCCESS', 'REVIEW_PROTOCOL_FAILURE'
    """
    raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    decoder = json.JSONDecoder()
    
    # 1. Candidate extraction via JSONDecoder.raw_decode from every plausible '{' position
    valid_objects = []
    pos = 0
    length = len(raw_text)
    
    while pos < length:
        idx = raw_text.find('{', pos)
        if idx == -1:
            break
        try:
            obj, end = decoder.raw_decode(raw_text, idx)
            if isinstance(obj, dict):
                # Check if this object matches the Sol verdict schema
                is_schema_match = (
                    obj.get("step") == expected_step and
                    obj.get("verdict") in {"APPROVE", "REJECT"} and
                    ("step_1_status" in obj or "step_status" in obj or "status" in obj) and
                    ("authorized_for_step_2" in obj or "can_proceed_to_step_2" in obj)
                )
                if is_schema_match:
                    valid_objects.append((idx, end, obj))
            pos = end
        except Exception:
            pos = idx + 1

    if not valid_objects:
        # Fallback: check if any object has at least verdict and step
        pos = 0
        while pos < length:
            idx = raw_text.find('{', pos)
            if idx == -1:
                break
            try:
                obj, end = decoder.raw_decode(raw_text, idx)
                if isinstance(obj, dict):
                    if obj.get("verdict") in {"APPROVE", "REJECT"} and (obj.get("step") == expected_step or f"step_{expected_step}_status" in obj):
                        valid_objects.append((idx, end, obj))
                pos = end
            except Exception:
                pos = idx + 1

    if not valid_objects:
        return "REVIEW_PROTOCOL_FAILURE", None, raw_hash

    # Check for consistency across extracted verdict candidates
    first_verdict = valid_objects[0][2].get("verdict")
    for _, _, candidate in valid_objects:
        if candidate.get("verdict") != first_verdict:
            return "REVIEW_PROTOCOL_FAILURE", None, raw_hash

    # Select the final authoritative candidate (latest complete verdict block emitted by Sol)
    final_candidate = valid_objects[-1][2]
    return "SUCCESS", final_candidate, raw_hash

if __name__ == "__main__":
    raw_path = Path(r"C:\Users\HH18\sol_step1.raw_output.txt")
    if raw_path.exists():
        text = raw_path.read_text(encoding="utf-8", errors="replace")
        status, verdict, h = parse_sol_verdict(text)
        print("Self-test parse status:", status)
        print("Verdict:", verdict.get("verdict") if verdict else None)
        print("Authorized for step 2:", verdict.get("authorized_for_step_2") if verdict else None)
        print("Raw SHA256:", h)
