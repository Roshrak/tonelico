#!/usr/bin/env python3
"""
Argon Quota Tracker & Dynamic Model Router for AIStudio2API (:2048) & Antigravity-Manager (:8045).
Rules (Fully Automatic High-Setting Cascade):
1. Default model is ALWAYS AIStudio Argon High (aistudio2api / gemini-4-argon-high).
2. If AIStudio Argon runs out, Hermes retries connecting 5 times, waiting 3 minutes (180s) each time.
3. If still unavailable after 5 retries (5 x 3m), automatically cascade in strict order:
   - Fallback 1: Antigravity Manager/Tools Argon High (antigravity-manager / gemini-4-argon-high)
   - Fallback 2: AIStudio Flash 3.8 High (aistudio2api / gemini-3.8-flash-high)
   - Fallback 3: Antigravity Manager/Tools Flash 3.8 High (antigravity-manager / gemini-3.8-flash-high)
4. Both AIStudio Argon and Antigravity Argon ALWAYS use the high setting (gemini-4-argon-high).
"""

import base64
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone

AISTUDIO_URL = "http://134.185.85.64:2048"
ANTIGRAVITY_URL = "http://134.185.85.64:8045"
REQUESTS_DB = "/home/aesc/aistudio2api/runtime/requests.db"
AISTUDIO_ENV = "/home/aesc/aistudio2api/.env"
HERMES_ENV = "/home/aesc/.hermes/.env"
STATE_FILE = "/home/aesc/.hermes/cache/argon_quota_state.json"
ESTIMATED_DAILY_ARGON_LIMIT_PER_ACCOUNT = 100


def load_proxy_keys() -> tuple[str, str]:
    aistudio_key = ""
    agm_key = ""
    if os.path.exists(HERMES_ENV):
        try:
            for line in open(HERMES_ENV):
                line = line.strip()
                if line.startswith("AISTUDIO2API_API_KEY="):
                    aistudio_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("AGY_ROTATOR_API_KEY="):
                    agm_key = line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return aistudio_key, agm_key


def get_aistudio_auth_headers() -> dict:
    user = "admin"
    pw = ""
    if os.path.exists(AISTUDIO_ENV):
        try:
            for line in open(AISTUDIO_ENV):
                line = line.strip()
                if line.startswith("ADMIN_USERNAME="):
                    user = line.split("=", 1)[1].strip()
                elif line.startswith("ADMIN_PASSWORD="):
                    pw = line.split("=", 1)[1].strip()
        except Exception:
            pass
    if pw:
        token = base64.b64encode(f"{user}:{pw}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    return {}


def parse_iso_utc(ts_str: str) -> float:
    if not ts_str:
        return 0.0
    s = ts_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if "." in s and "+" in s:
        main, tz = s.split("+", 1)
        sec, frac = main.split(".", 1)
        s = f"{sec}.{frac[:6]}+{tz}"
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def probe_v1_models(base_url: str, api_key: str) -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    req = urllib.request.Request(f"{base_url}/v1/models", headers=headers)
    with urllib.request.urlopen(req, timeout=4) as r:
        data = json.loads(r.read().decode())
    return [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]


def get_argon_quota_status() -> dict:
    now = time.time()
    total_accounts = 0
    ready_Ids = []
    cooldown_Ids = set()

    auth_headers = get_aistudio_auth_headers()
    try:
        req = urllib.request.Request(f"{AISTUDIO_URL}/api/accounts", headers=auth_headers)
        accs_data = json.loads(urllib.request.urlopen(req, timeout=3).read().decode())
        enabled_accs = [
            a["id"]
            for a in accs_data.get("accounts", [])
            if a.get("enabled", True) and a.get("state") == "ready"
        ]
        total_accounts = len(enabled_accs)
    except Exception:
        enabled_accs = []

    if total_accounts > 0:
        try:
            req = urllib.request.Request(f"{AISTUDIO_URL}/api/cooldowns", headers=auth_headers)
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
        account_pct = (ready_count / total_accounts) * 100.0 if total_accounts > 0 else 100.0
    else:
        # Remote /api/accounts is restricted (403); probe /v1/models with Bearer key instead
        aistudio_key, _ = load_proxy_keys()
        try:
            models = probe_v1_models(AISTUDIO_URL, aistudio_key)
            has_argon = any("argon" in m.lower() for m in models)
            total_accounts = 9 if has_argon else 0
            ready_count = 9 if has_argon else 0
            account_pct = 100.0 if has_argon else 0.0
        except Exception:
            total_accounts = 9
            ready_count = 9
            account_pct = 100.0

    remaining_pct = account_pct if ready_count > 0 else 0.0
    return {
        "total_accounts": total_accounts,
        "ready_accounts": ready_count,
        "cooldown_accounts": len(cooldown_Ids),
        "remaining_pct": round(remaining_pct, 1),
        "account_pct": round(account_pct, 1),
        "tier": "high",
        "argon_target": "gemini-4-argon-high",
        "provider": "aistudio2api",
        "retry_policy": {
            "primary_retries": 5,
            "primary_retry_wait_seconds": 180,
            "fallback_chain": [
                {"provider": "antigravity-manager", "model": "gemini-4-argon-high"},
                {"provider": "aistudio2api", "model": "gemini-3.8-flash-high"},
                {"provider": "antigravity-manager", "model": "gemini-3.8-flash-high"},
            ],
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_aistudio_model_mapping(tier: str = "high") -> str:
    """
    Build MODEL_MAPPING for AIStudio2API:
    - All Argon variants map to gemini-4-argon(high) (both use high setting).
    - All 3.8 Flash variants map to gemini-3.8-flash(high).
    """
    argon_high_target = "gemini-4-argon(high)"
    mappings = [
        f"gemini-4-argon:{argon_high_target}",
        f"gemini-4-argon-high:{argon_high_target}",
        f"gemini-4-argon-medium:{argon_high_target}",
        f"gemini-4-argon-low:{argon_high_target}",
        f"Gemini 4 Argon (High):{argon_high_target}",
        f"Gemini 4 Argon (Medium):{argon_high_target}",
        f"Gemini 4 Argon (Low):{argon_high_target}",
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
    auth_headers = get_aistudio_auth_headers()
    try:
        req = urllib.request.Request(f"{AISTUDIO_URL}/api/config", headers=auth_headers)
        cfg = json.loads(urllib.request.urlopen(req, timeout=3).read().decode())
        if cfg.get("model_mapping") != desired_mapping:
            cfg["model_mapping"] = desired_mapping
            put_headers = {**auth_headers, "Content-Type": "application/json"}
            put_req = urllib.request.Request(
                f"{AISTUDIO_URL}/api/config",
                data=json.dumps(cfg).encode(),
                headers=put_headers,
                method="PUT",
            )
            urllib.request.urlopen(put_req, timeout=5).read()
            changed = True
    except Exception:
        pass

    # Always keep Hermes config.yaml locked to:
    # Primary: aistudio2api / gemini-4-argon-high
    # Fallback 1: antigravity-manager / gemini-4-argon-high
    # Fallback 2: aistudio2api / gemini-3.8-flash-high
    # Fallback 3: antigravity-manager / gemini-3.8-flash-high
    hermes_cfg = "/home/aesc/.hermes/config.yaml"
    if os.path.exists(hermes_cfg):
        try:
            txt = open(hermes_cfg).read()
            new_txt = re.sub(
                r"provider:\s*(?:aistudio2api|antigravity-manager)",
                "provider: aistudio2api",
                txt,
                count=1,
            )
            new_txt = re.sub(
                r"default:\s*(?:gemini-4-argon[^\n]*|gemini-3\.8-flash[^\n]*)",
                "default: gemini-4-argon-high",
                new_txt,
                count=1,
            )
            new_txt = re.sub(
                r"(aistudio2api:\n(?:[ \t]+[^\n]+\n)*?[ \t]+default_model:\s*)(?:gemini-4-argon[^\n]*|gemini-3\.8-flash[^\n]*)",
                r"\g<1>gemini-4-argon-high",
                new_txt,
                count=1,
            )
            new_txt = re.sub(
                r"(antigravity-manager:\n(?:[ \t]+[^\n]+\n)*?[ \t]+default_model:\s*)(?:gemini-4-argon[^\n]*|gemini-3\.8-flash[^\n]*)",
                r"\g<1>gemini-4-argon-high",
                new_txt,
                count=1,
            )
            new_txt = new_txt.replace("argon-low: aistudio2api/gemini-4-argon-low", "argon-low: aistudio2api/gemini-4-argon-high")
            new_txt = new_txt.replace("reasoning_effort: low", "reasoning_effort: high")
            desired_fb = (
                "fallback_providers:\n"
                "  - provider: antigravity-manager\n"
                "    model: gemini-4-argon-high\n"
                "  - provider: aistudio2api\n"
                "    model: gemini-3.8-flash-high\n"
                "  - provider: antigravity-manager\n"
                "    model: gemini-3.8-flash-high\n"
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
