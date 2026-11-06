#!/usr/bin/env python3
"""
Importer for AI_Pool_Bundle_16Acc_400d.zip into Antigravity Tools & AIStudio2API.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ZIP_PATH = pathlib.Path("/home/aesc/Downloads/AI_Pool_Bundle_16Acc_400d.zip")
AG_TARGET = pathlib.Path.home() / ".antigravity_tools"
AISTUDIO_AUTH_TARGET = pathlib.Path("/home/aesc/aistudio2api/auth")

MULTILOGIN_URL = (
    "https://accounts.google.com/oauth/multilogin"
    "?source=ChromiumAccountReconcilorDice&reuseCookies=0"
)
MAX_COOKIE_AGE = 400 * 24 * 3600


def to_storage_cookies(ml_cookies):
    now = time.time()
    out = []
    for c in ml_cookies:
        domain = c.get("domain") or ""
        host = c.get("host") or ""
        if not domain and host and not host.startswith("."):
            domain = host
        expires = -1.0
        if c.get("maxAge") is not None:
            lifetime = min(float(c["maxAge"]), float(MAX_COOKIE_AGE))
            expires = now + lifetime
        path = c.get("path") or "/"
        ss = (c.get("sameSite") or "").lower()
        same_site = ss.capitalize() if ss in ("none", "lax", "strict") else ""
        out.append(
            {
                "name": c["name"],
                "value": c["value"],
                "domain": domain,
                "path": path,
                "expires": expires,
                "httpOnly": bool(c.get("isHttpOnly", False)),
                "secure": bool(c.get("isSecure", False)),
                "sameSite": same_site,
            }
        )
    return out


def install_antigravity():
    print("=== 1. Installing Antigravity Tools accounts ===")
    ag_acc_target = AG_TARGET / "accounts"
    ag_acc_target.mkdir(parents=True, exist_ok=True)

    backup_dir = AG_TARGET / f"accounts_backup_{int(time.time())}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst_index_file = AG_TARGET / "accounts.json"
    if dst_index_file.exists():
        shutil.copy2(dst_index_file, backup_dir / "accounts.json")
        try:
            dst_index = json.loads(dst_index_file.read_text(encoding="utf-8"))
        except Exception:
            dst_index = {"accounts": [], "current_account_id": None}
    else:
        dst_index = {"accounts": [], "current_account_id": None}

    existing_by_email = {
        a.get("email"): a for a in dst_index.get("accounts", []) if a.get("email")
    }

    with zipfile.ZipFile(ZIP_PATH, "r") as z:
        src_index = json.loads(z.read("Antigravity_Tools/accounts.json").decode("utf-8"))

        for name in z.namelist():
            if name.startswith("Antigravity_Tools/accounts/") and name.endswith(".json"):
                data_bytes = z.read(name)
                acc_obj = json.loads(data_bytes.decode("utf-8"))
                # Enable proxy_disabled if needed so accounts can be actively used
                acc_obj["proxy_disabled"] = False
                acc_obj["disabled"] = False
                filename = pathlib.Path(name).name
                (ag_acc_target / filename).write_text(
                    json.dumps(acc_obj, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )

        for acc_entry in src_index.get("accounts", []):
            email = acc_entry.get("email")
            if email:
                acc_entry["proxy_disabled"] = False
                acc_entry["disabled"] = False
                existing_by_email[email] = acc_entry

    dst_index["accounts"] = list(existing_by_email.values())
    if not dst_index.get("current_account_id") and dst_index["accounts"]:
        dst_index["current_account_id"] = dst_index["accounts"][0]["id"]

    dst_index_file.write_text(
        json.dumps(dst_index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"[OK] Antigravity Tools: Merged total {len(dst_index['accounts'])} accounts in {ag_acc_target}"
    )


def install_and_renew_aistudio():
    print("=== 2. Installing and renewing AIStudio2API accounts ===")
    AISTUDIO_AUTH_TARGET.mkdir(parents=True, exist_ok=True)

    backup_dir = AISTUDIO_AUTH_TARGET.parent / f"auth_backup_{int(time.time())}"
    if AISTUDIO_AUTH_TARGET.exists():
        shutil.copytree(AISTUDIO_AUTH_TARGET, backup_dir, dirs_exist_ok=True)
        print(f"[BACKUP] AIStudio auth backed up to {backup_dir}")

    chrome_meta = AISTUDIO_AUTH_TARGET / ".chrome-meta"
    chrome_meta.mkdir(parents=True, exist_ok=True)
    (chrome_meta / "Last Version").write_text("138.0.7204.300\n", encoding="utf-8")

    installed_emails = []
    with zipfile.ZipFile(ZIP_PATH, "r") as z:
        for name in z.namelist():
            if name.startswith("AIStudio2API/auth/") and "/" in name[len("AIStudio2API/auth/"):].strip("/"):
                rel = name[len("AIStudio2API/auth/"):].strip("/")
                parts = rel.split("/")
                if len(parts) == 2 and "@" in parts[0]:
                    email, fname = parts
                    dst_acc = AISTUDIO_AUTH_TARGET / email
                    dst_acc.mkdir(parents=True, exist_ok=True)
                    content = z.read(name)
                    (dst_acc / fname).write_bytes(content)
                    if email not in installed_emails:
                        installed_emails.append(email)

    print(f"[OK] Extracted {len(installed_emails)} accounts into {AISTUDIO_AUTH_TARGET}")

    # Now renew 400-day cookies for ALL accounts in AISTUDIO_AUTH_TARGET
    ok = 0
    total = 0
    for acc_dir in sorted(AISTUDIO_AUTH_TARGET.iterdir()):
        if not acc_dir.is_dir() or "@" not in acc_dir.name:
            continue
        st_file = acc_dir / "storage-state.json"
        if not st_file.exists():
            continue
        total += 1
        st = json.loads(st_file.read_text(encoding="utf-8"))
        oauth = st.get("aistudio2api", {}).get("oauth", {})
        gaia = oauth.get("gaia_id", "")
        token = oauth.get("refresh_token", "")
        if not gaia or not token:
            print(f"[SKIP] {acc_dir.name}: no oauth.refresh_token")
            continue
        req = urllib.request.Request(
            MULTILOGIN_URL,
            data=b" ",
            headers={
                "Authorization": f"MultiBearer {token}:{gaia}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Dest": "empty",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Priority": "u=4, i",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                body = resp.read().decode("utf-8").strip()
            if body.startswith(")]}'"):
                body = body[4:].strip()
            payload = json.loads(body)
            cookies = payload.get("cookies", [])
            if payload.get("status") == "OK" and cookies:
                st["cookies"] = to_storage_cookies(cookies)
                st.setdefault("aistudio2api", {}).setdefault("source", {})["root"] = str(
                    chrome_meta.resolve()
                )
                st_file.write_text(
                    json.dumps(st, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                ok += 1
                print(f"[OK 400d] {acc_dir.name} (cookies={len(cookies)})")
            else:
                print(f"[FAIL] {acc_dir.name}: status={payload.get('status')}")
        except Exception as e:
            print(f"[ERR]  {acc_dir.name}: {e}")

    print(f"=== Completed: {ok}/{total} AIStudio2API accounts renewed for 400 days ===")


def restart_services():
    print("=== 3. Restarting services ===")
    try:
        subprocess.run(["systemctl", "--user", "restart", "aistudio2api.service"], check=True)
        print("[OK] aistudio2api.service restarted")
    except Exception as e:
        print("[ERR] restarting aistudio2api:", e)

    try:
        subprocess.run(["docker", "restart", "antigravity-manager"], check=True)
        print("[OK] antigravity-manager container restarted")
    except Exception as e:
        print("[ERR] restarting antigravity-manager:", e)


if __name__ == "__main__":
    install_antigravity()
    install_and_renew_aistudio()
    restart_services()
