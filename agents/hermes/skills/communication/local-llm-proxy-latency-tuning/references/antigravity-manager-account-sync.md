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

After linking, trigger a quota refresh across all accounts:
```bash
curl -s -X POST http://127.0.0.1:8045/api/accounts/refresh \
  -H "Authorization: Bearer <admin_password>" \
  -H "Content-Type: application/json" \
  -d '{}'
```
