# Antigravity-Manager Upgrade & Headless Account Sync from AIStudio2API

## 1. Fast Upgrade via Prebuilt Upstream Docker Image

Avoid compiling the Rust backend from source inside `~/agm-docker` (~9 minutes). Upstream publishes multi-arch images to Docker Hub (`lbjlaq/antigravity-manager:v<X.Y.Z>`):

```bash
git -C ~/agm-docker/src fetch origin main --tags
git -C ~/agm-docker/src checkout FETCH_HEAD
docker pull lbjlaq/antigravity-manager:v<X.Y.Z>
docker tag lbjlaq/antigravity-manager:v<X.Y.Z> antigravity-manager:<X.Y.Z>-local
# Update image tag in ~/agm-docker/compose.yml to antigravity-manager:<X.Y.Z>-local
docker compose -f ~/agm-docker/compose.yml up -d
curl -s http://127.0.0.1:8045/health
```

Ensure `"enabled": true` is set under `"proxy"` in `~/.antigravity_tools/gui_config.json`.

## 2. Headless OAuth Account Linking from `aistudio2api` Sessions

Each account authenticated in `aistudio2api` has a saved session directory at `/home/aesc/aistudio2api/auth/<email>/` containing:
- `storage-state.json` (authenticated Google cookies)
- `camoufox-fingerprint.json` (browser fingerprint and `navigator.userAgent` in `config`)

To link any missing `aistudio2api` accounts into `Antigravity-Manager` (`127.0.0.1:8045`) without manual browser interaction:

```python
import json, os, time, urllib.request
from playwright.sync_api import sync_playwright

cfg = json.load(open("/home/aesc/.antigravity_tools/gui_config.json"))
pw = cfg["proxy"]["admin_password"]

def get_existing_emails():
    req = urllib.request.Request(
        "http://127.0.0.1:8045/api/accounts",
        headers={"Authorization": f"Bearer {pw}"},
    )
    resp = json.loads(urllib.request.urlopen(req).read().decode())
    return {a["email"]: a for a in resp.get("accounts", [])}

auth_dir = "/home/aesc/aistudio2api/auth"
aistudio_emails = sorted([
    d for d in os.listdir(auth_dir)
    if "@" in d and os.path.isfile(os.path.join(auth_dir, d, "storage-state.json"))
])
existing = get_existing_emails()

with sync_playwright() as p:
    for email in aistudio_emails:
        if email in existing and not existing[email].get("disabled"):
            continue
        req = urllib.request.Request(
            "http://127.0.0.1:8045/api/auth/url",
            headers={"Authorization": f"Bearer {pw}"},
        )
        auth_url = json.loads(urllib.request.urlopen(req).read().decode())["url"]

        fp_path = f"{auth_dir}/{email}/camoufox-fingerprint.json"
        if not os.path.exists(fp_path):
            import glob
            candidates = glob.glob(f"{auth_dir}/*/camoufox-fingerprint.json")
            fp_path = candidates[0] if candidates else fp_path
        fp = json.load(open(fp_path)) if os.path.exists(fp_path) else {"config": {}}
        ua = fp.get("config", {}).get(
            "navigator.userAgent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
        )

        st = json.load(open(f"{auth_dir}/{email}/storage-state.json"))
        for c in st.get("cookies", []):
            ss = str(c.get("sameSite", "")).capitalize()
            c["sameSite"] = ss if ss in ("Strict", "Lax", "None") else "Lax"

        env = dict(os.environ)
        env["CAMOU_CONFIG_1"] = json.dumps(fp.get("config", {}))
        browser = p.firefox.launch(
            executable_path="/home/aesc/aistudio2api/runtime/camoufox/camoufox-bin",
            headless=True,
            env=env,
        )
        context = browser.new_context(storage_state=st, no_viewport=True, user_agent=ua)
        page = context.new_page()
        done = [False]

        def handle_route(route):
            url = route.request.url
            target = url.replace("http://localhost:8045", "http://127.0.0.1:8045")
            r = urllib.request.Request(target, headers={"Host": "localhost:8045"})
            body = urllib.request.urlopen(r).read().decode("utf-8", errors="ignore")
            if "Authorization Successful" in body:
                done[0] = True
            route.fulfill(status=200, content_type="text/html", body=body)

        page.route("http://localhost:8045/**", handle_route)
        page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)

        for _ in range(8):
            time.sleep(3)
            if done[0]:
                break
            ident = page.locator(f'[data-identifier="{email}"], [data-email="{email}"]')
            if "accountchooser" in page.url and ident.count() > 0 and ident.first.is_visible():
                ident.first.click()
                continue
            for btn_text in ["Đăng nhập", "Sign in", "Tiếp tục", "Continue", "Cho phép", "Allow"]:
                btn = page.get_by_role("button", name=btn_text)
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click()
                    break

        context.close()
        browser.close()
```

Invoke the script using the scraper venv with `nix-ld` libraries exposed:
```bash
LD_LIBRARY_PATH="${NIX_LD_LIBRARY_PATH:-}" /home/aesc/.hermes/venv-scraper/bin/python link_accounts.py
```

After linking, trigger a quota refresh across all accounts (also run this first if a requested account already appears in `GET /api/accounts` with `"quota": null` or `"name": null` — newly linked accounts with a saved `token.refresh_token` in `~/.antigravity_tools/accounts/<id>.json` only need a refresh to populate `subscription_tier` and `quota.models`; if `details` reports `Refresh failed for client [antigravity_enterprise]` on an account with `"device_bound": true`, renew that account's 400-day cookies in `aistudio2api/auth/<email>/storage-state.json` first and then re-run the Playwright OAuth flow above to replace the device-bound token with a standard OAuth token):
```bash
curl -s -X POST http://127.0.0.1:8045/api/accounts/refresh \
  -H "Authorization: Bearer <admin_password>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## 3. Portable 400-Day Pool Bundle Export & Renewal (`AI_Pool_Bundle_*_400d.zip`)

To package all `AIStudio2API` and `Antigravity Tools` accounts into a portable `.zip` archive that works across Windows, Linux, Docker, and VPS without re-authenticating:

1. **Dual-Mode 400-Day Cookie Renewal (`scripts/renew_400d_tokens.py`)**:
   - **Chrome-Imported Accounts (`aistudio2api.oauth.refresh_token` starting with `1//0g...` and `gaia_id`)**: Send `POST https://accounts.google.com/oauth/multilogin?source=ChromiumAccountReconcilorDice&reuseCookies=0` with header `Authorization: MultiBearer <refresh_token>:<gaia_id>` and `data=b" "`. Strip the `)]}'` prefix from the response and convert `payload["cookies"]` to Playwright `storage-state.json` format with `expires = time.time() + min(maxAge, 400 * 86400)`.
   - **Camoufox-Authenticated Accounts (`source.browser == "camoufox"`, no `1//0g...` token)**: Never place an Antigravity Tools `1//06...` OAuth token into `aistudio2api.oauth.refresh_token` (which causes `OAuthMultilogin` to fail with `HTTP 403 Forbidden`). Instead, verify the session via `POST https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser&json=standard`, rotate `SIDCC` / `__Secure-1PSIDCC` / `__Secure-3PSIDCC` via `GET https://accounts.google.com/ServiceLogin?service=chromiumsync&sarp=1&continue=https%3A%2F%2Fwww.google.com%2F` (using a non-redirecting `HTTPRedirectHandler`), and set `expires = time.time() + 400 * 86400` on all persistent cookies in `storage-state.json`.

2. **Antigravity Tools Sync (`Antigravity_Tools/`)**:
   - Set `"priority": 1`, `"disabled": false`, and `"proxy_disabled": false` across all `PRO` accounts in `~/.antigravity_tools/accounts/*.json` and `~/.antigravity_tools/accounts.json`, then restart `antigravity-manager` (`docker restart antigravity-manager`).
   - Generate `Antigravity_Tools/gui_import_tokens.json` as `[{"email": "<email>", "refresh_token": "<token.refresh_token>"}]` for 1-click GUI/Web import alongside `Antigravity_Tools/accounts.json`, `Antigravity_Tools/gui_config.json`, and `Antigravity_Tools/accounts/*.json`.

3. **Bundle Layout (`1_CAI_DAT_VAO_MAY_NAY.bat` + `2_GIA_HAN_TOKEN_400_NGAY.bat`)**:
   - Include `account.json`, `storage-state.json`, `runtime-state.json`, `catalog.json`, `camoufox-fingerprint.json`, and `spidermonkey-cache.json` under `AIStudio2API/auth/<email>/`, plus `AIStudio2API/auth/.chrome-meta/Last Version` (`138.0.7204.300`) and `AIStudio2API/.env.recommended` (`WAA_BACKEND=spidermonkey`, `UPSTREAM_CHANNELS=playground`, `ROUTING_STRATEGY=fill-first`, `FIRST_EVENT_HEDGE=auto`).
