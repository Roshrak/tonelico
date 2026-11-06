#!/usr/bin/env python3
"""
Argon Quota Tracker & Dynamic Model Router for AIStudio2API (:2048) & Antigravity-Manager (:8045).
Rules (No Compromise):
1. Default model is ALWAYS Argon High (gemini-4-argon-high).
2. Track Argon quota across all enabled accounts in AIStudio2API (:2048):
   - > 20% remaining: Argon maps to gemini-4-argon(high)
   - <= 20% remaining (> 0%): Argon automatically switches to gemini-4-argon(low)
   - 0% remaining (limit reached): Fallback to Antigravity-Manager (:8045) with claude-opus-4-6-thinking or gemini-3.8-flash-high
3. Every 3.8 Flash request (gemini-3.8-flash, -low, -medium, -tiered, -high) ALWAYS maps to high (gemini-3.8-flash-high).
"""

import json
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone

AISTUDIO_URL = "http://127.0.0.1:2048"
ANTIGRAVITY_URL = "http://127.0.0.1:8045"
REQUESTS_DB = "/home/aesc/aistudio2api/runtime/requests.db"
AISTUDIO_ENV = "/home/aesc/aistudio2api/.env"
STATE_FILE = "/home/aesc/.hermes/cache/argon_quota_state.json"
ESTIMATED_DAILY_ARGON_LIMIT_PER_ACCOUNT = 100


def parse_iso_utc(ts_str: str) -> float:
    if not ts_str:
        return 0.0
    s = ts_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Truncate nanoseconds to microseconds for fromisoformat
    if "." in s and "+" in s:
        main, tz = s.split("+", 1)
        sec, frac = main.split(".", 1)
        s = f"{sec}.{frac[:6]}+{tz}"
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def get_argon_quota_status() -> dict:
    now = time.time()
    total_accounts = 0
    ready_Ids = []
    cooldown_Ids = set()

    try:
        req = urllib.request.Request(f"{AISTUDIO_URL}/api/accounts")
        accs_data = json.loads(urllib.request.urlopen(req, timeout=3).read().decode())
        enabled_accs = [a["id"] for a in accs_data.get("accounts", []) if a.get("enabled", True)]
        total_accounts = len(enabled_accs)
    except Exception:
        enabled_accs = []

    try:
        req = urllib.request.Request(f"{AISTUDIO_URL}/api/cooldowns")
        cd_data = json.loads(urllib.request.urlopen(req, timeout=3).read().decode())
        for c in cd_data.get("cooldowns", []):
            model_id = c.get("model_id", "") or c.get("scope", "")
            until_ts = parse_iso_utc(c.get("until", ""))
            if ("argon" in model_id or model_id == "*") and until_ts > now:
                cooldown_Ids.add(c.get("account_id"))
    except Exception:
        pass

    ready_Ids = [a for a in enabled_accs if a not in cooldown_Ids]
    ready_count = len(ready_Ids)

    if total_accounts == 0:
        return {
            "total_accounts": 0,
            "ready_accounts": 0,
            "cooldown_accounts": 0,
            "remaining_pct": 0.0,
            "tier": "fallback",
            "argon_target": "gemini-3.8-flash-high",
            "provider": "antigravity-manager",
        }

    account_pct = (ready_count / total_accounts) * 100.0

    # Also check 24h Argon request usage on ready accounts from requests.db
    used_on_ready = 0
    if os.path.exists(REQUESTS_DB) and ready_Ids:
        try:
            conn = sqlite3.connect(f"file:{REQUESTS_DB}?mode=ro", uri=True)
            cutoff_ms = int((now - 86400) * 1000)
            placeholders = ",".join("?" for _ in ready_Ids)
            row = conn.execute(
                f"SELECT COUNT(*) FROM requests WHERE model LIKE '%argon%' AND status = 200 AND time >= ? AND account IN ({placeholders})",
                [cutoff_ms, *ready_Ids],
            ).fetchone()
            used_on_ready = row[0] if row else 0
            conn.close()
        except Exception:
            used_on_ready = 0

    total_pool_capacity = total_accounts * ESTIMATED_DAILY_ARGON_LIMIT_PER_ACCOUNT
    ready_remaining_capacity = max(0, ready_count * ESTIMATED_DAILY_ARGON_LIMIT_PER_ACCOUNT - used_on_ready)
    req_pct = (ready_remaining_capacity / total_pool_capacity) * 100.0 if total_pool_capacity > 0 else account_pct

    # Effective remaining percentage: if ready_count > 0, never report 0% solely from heuristic request count
    if ready_count == 0:
        remaining_pct = 0.0
    else:
        remaining_pct = max(1.0, min(account_pct, req_pct))

    if remaining_pct <= 0.0:
        tier = "fallback"
        argon_target = "gemini-3.8-flash-high"
        provider = "antigravity-manager"
    elif remaining_pct <= 20.0:
        tier = "low"
        argon_target = "gemini-4-argon-low"
        provider = "aistudio2api"
    else:
        tier = "high"
        argon_target = "gemini-4-argon-high"
        provider = "aistudio2api"

    return {
        "total_accounts": total_accounts,
        "ready_accounts": ready_count,
        "cooldown_accounts": len(cooldown_Ids),
        "remaining_pct": round(remaining_pct, 1),
        "account_pct": round(account_pct, 1),
        "tier": tier,
        "argon_target": argon_target,
        "provider": provider,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_aistudio_model_mapping(argon_effort: str = "high") -> str:
    """
    Build MODEL_MAPPING for AIStudio2API:
    - Argon ALWAYS maps to high (gemini-4-argon(high)).
    - Every 3.8 flash variant ALWAYS maps to gemini-3.8-flash(high).
    """
    mappings = [
        "gemini-4-argon:gemini-4-argon(high)",
        "gemini-4-argon-high:gemini-4-argon(high)",
        "gemini-4-argon-medium:gemini-4-argon(high)",
        "gemini-4-argon-low:gemini-4-argon(low)",
        "Gemini 4 Argon (High):gemini-4-argon(high)",
        "Gemini 4 Argon (Medium):gemini-4-argon(high)",
        "Gemini 4 Argon (Low):gemini-4-argon(low)",
        "gemini-3.8-flash:gemini-3.8-flash(high)",
        "gemini-3.8-flash-high:gemini-3.8-flash(high)",
        "gemini-3.8-flash-medium:gemini-3.8-flash(high)",
        "gemini-3.8-flash-low:gemini-3.8-flash(high)",
        "gemini-3.8-flash-tiered:gemini-3.8-flash(high)",
        "Gemini 3.8 Flash (High):gemini-3.8-flash(high)",
        "Gemini 3.8 Flash (Medium):gemini-3.8-flash(high)",
        "Gemini 3.8 Flash (Low):gemini-3.8-flash(high)",
        "gemini-3.7-flash:gemini-3.8-flash(high)",
        "gemini-3.7-flash-high:gemini-3.8-flash(high)",
        "gemini-3.7-flash-medium:gemini-3.8-flash(high)",
        "gemini-3.7-flash-low:gemini-3.8-flash(high)",
        "gemini-3.1-pro:gemini-3.1-pro-preview(high)",
        "gemini-3.1-pro-high:gemini-3.1-pro-preview(high)",
        "gemini-3.1-pro-low:gemini-3.1-pro-preview(low)",
    ]
    return ",".join(mappings)


def sync_aistudio_mapping(status: dict) -> bool:
    desired_mapping = build_aistudio_model_mapping("high")
    changed = False
    try:
        req = urllib.request.Request(f"{AISTUDIO_URL}/api/config")
        cfg = json.loads(urllib.request.urlopen(req, timeout=3).read().decode())
        if cfg.get("model_mapping") != desired_mapping:
            put_req = urllib.request.Request(
                f"{AISTUDIO_URL}/api/config",
                data=json.dumps({"model_mapping": desired_mapping}).encode(),
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            urllib.request.urlopen(put_req, timeout=5).read()
            changed = True
    except Exception:
        pass

    # Ensure Hermes config.yaml has primary: gemini-4-argon-high (aistudio2api)
    # and fallback chain:
    # 1. gemini-4-argon-high (antigravity-manager)
    # 2. gemini-3.8-flash-high (aistudio2api)
    # 3. gemini-3.8-flash-high (antigravity-manager)
    # 4. claude-opus-4-6-thinking (antigravity-manager)
    hermes_cfg = "/home/aesc/.hermes/config.yaml"
    if os.path.exists(hermes_cfg):
        try:
            txt = open(hermes_cfg).read()
            import re
            new_txt = re.sub(r"provider:\s*(?:aistudio2api|antigravity-manager)", "provider: aistudio2api", txt, count=1)
            new_txt = re.sub(r"default:\s*gemini-4-argon[^\n]*", "default: gemini-4-argon-high", new_txt)
            new_txt = new_txt.replace("reasoning_effort: low", "reasoning_effort: high")
            desired_fb = (
                "fallback_providers:\n"
                "  - provider: antigravity-manager\n"
                "    model: gemini-4-argon-high\n"
                "  - provider: aistudio2api\n"
                "    model: gemini-3.8-flash-high\n"
                "  - provider: antigravity-manager\n"
                "    model: gemini-3.8-flash-high\n"
                "  - provider: antigravity-manager\n"
                "    model: claude-opus-4-6-thinking\n"
            )
            new_txt = re.sub(
                r"fallback_providers:\n(?:[ \t]*-[^\n]*\n(?:[ \t]+[^\n]*\n)*)+",
                desired_fb,
                new_txt,
                count=1,
            )
            if new_txt != txt:
                open(hermes_cfg, "w").write(new_txt)
                changed = True
        except Exception:
            pass

    # Persist in .env as well so restarts keep the mapping
    if os.path.exists(AISTUDIO_ENV):
        try:
            lines = open(AISTUDIO_ENV).read().splitlines()
            new_lines = []
            updated_line = False
            for line in lines:
                if line.startswith("MODEL_MAPPING="):
                    if line != f"MODEL_MAPPING={desired_mapping}":
                        new_lines.append(f"MODEL_MAPPING={desired_mapping}")
                        updated_line = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            if updated_line:
                open(AISTUDIO_ENV, "w").write("\n".join(new_lines) + "\n")
        except Exception:
            pass

    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        json.dump({**status, "mapping_updated": changed}, open(STATE_FILE, "w"), indent=2)
    except Exception:
        pass
    return changed


def main():
    status = get_argon_quota_status()
    sync_aistudio_mapping(status)
    if "--json" in sys.argv:
        print(json.dumps(status))
    elif "--model" in sys.argv:
        print(status["argon_target"])
    else:
        print(
            f"Argon Quota: {status['ready_accounts']}/{status['total_accounts']} ready "
            f"({status['remaining_pct']}% left) -> tier={status['tier']} target={status['argon_target']} ({status['provider']})"
        )


if __name__ == "__main__":
    main()
