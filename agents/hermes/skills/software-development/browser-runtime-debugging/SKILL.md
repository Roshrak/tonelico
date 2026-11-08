---
name: browser-runtime-debugging
description: "Use when debugging or fixing browser DOM/extensions via CDP."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [cdp, browser, chromium, extension, dom, debugging, verification]
    related_skills: [desktop-reliability, inspecting-hermes-desktop-dom]
---

# Browser Runtime Debugging & Extension Remediation via CDP

Protocol for inspecting, diagnosing, and fixing browser DOM issues, visual artifacts, and intrusive extension injections live via Chrome DevTools Protocol (CDP).

## 1. Target Discovery
- Chromium and Electron instances run with `--remote-debugging-port=9222`.
- Probe active pages:
  ```bash
  curl -s http://127.0.0.1:9222/json
  ```
  Filter for targets with `"type": "page"` and extract their `webSocketDebuggerUrl` and `title`.

## 2. Live DOM Inspection via Built-in Node.js WebSocket
- Node.js 22+ includes native `WebSocket` (`globalThis.WebSocket`), eliminating external package dependencies.
- Evaluate expressions across tabs via CDP `Runtime.evaluate`:
  ```javascript
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  ws.onopen = () => {
    ws.send(JSON.stringify({
      id: 1,
      method: "Runtime.evaluate",
      params: {
        expression: `(() => {
          const els = Array.from(document.querySelectorAll("*")).filter(el =>
            el.textContent && el.textContent.includes("<target_text>")
          );
          return els.map(el => ({ tag: el.tagName, style: el.getAttribute("style"), html: el.outerHTML }));
        })()`,
        returnByValue: true
      }
    }));
  };
  ```

## 3. Tracing Injected Artifacts to Extensions
- Injected banners (e.g., fixed red warning bars, unwanted banners, overlays) are often added by extensions on non-HTTPS pages.
- Locate the extension source:
  ```bash
  grep -rn "<exact text>" ~/.config/chromium/Default/Extensions/
  ```
- Inspect `content.js` to see the injection logic (e.g., checking `window.location.protocol !== 'https:'` without whitelisting loopback or private addresses).

## 4. Two-Phase Remediation
1. **Persistent Fix (Source Patch):**
   - Edit the extension's `content.js` to neuter or restrict the function (e.g., exempting `localhost`, `127.0.0.1`, `::1`, or clearing the DOM injection logic completely).
2. **Immediate Live Fix (Zero-Restart Removal):**
   - Never force-kill the user's browser or reload tabs if avoidable.
   - Execute DOM removal live via CDP WebSocket across all active page tabs:
     ```javascript
     elements.forEach(el => el.remove());
     ```
   - This provides instant gratification and preserves active form inputs, playback, or work in progress.

## 5. Managing Extensions & Declarative Web Store Policies via `chrome://extensions` CDP
- **Declarative Policy-Managed Web Store Extensions (`ExtensionSettings`)**:
  - Prefer declarative `"ExtensionSettings"` (`"installation_mode": "normal_installed"`, `"toolbar_pin": "force_pinned"`, `"update_url": "https://clients2.google.com/service/update2/crx"`) in `/etc/chromium/policies/managed/default-browser.json` over unpacked `--load-extension` directories — policy-managed Web Store extensions install and update cleanly without triggering startup developer-mode warnings.
  - **Pitfall**: Never pass `--disable-background-networking` on Chromium's command line when using `ExtensionSettings` — it disables the background extension fetcher (`chrome.developerPrivate.autoUpdate()` / `repairExtension()`) so missing or newly declared policy extensions never download.
- **Enabling Unpacked `--load-extension` When Required**:
  - Chromium 138+ automatically disables unpacked `--load-extension` directories with `disable_reasons: [16777216]` (`DISABLE_UNSUPPORTED_DEVELOPER_EXTENSION`) unless Developer Mode is enabled in the profile (`"extensions": {"ui": {"developer_mode": true}}` in `Default/Preferences`) and allowed by policy (`"ExtensionDeveloperModeSettings": 0` in `/etc/chromium/policies/managed/default-browser.json`).
  - To enable Developer Mode and activate an unpacked extension live without restarting Chromium:
    1. Open a temporary `chrome://extensions` target via `PUT http://127.0.0.1:9222/json/new?chrome://extensions`.
    2. Connect to its `webSocketDebuggerUrl` and evaluate via `Runtime.evaluate` (`awaitPromise: true`):
       ```javascript
       await chrome.developerPrivate.updateProfileConfiguration({
         inDeveloperMode: true,
         isMv2DeprecationNoticeDismissed: true
       });
       await new Promise(r => chrome.management.setEnabled(extensionId, true, r));
       await chrome.developerPrivate.updateExtensionConfiguration({
         extensionId,
         pinnedToToolbar: true
       });
       ```
       - **Pitfall**: `chrome.developerPrivate.updateExtensionConfiguration` rejects `isActive` (`Unexpected property: 'isActive'`); always use `chrome.management.setEnabled(extensionId, true)` to enable an extension and `updateExtensionConfiguration` only for properties like `pinnedToToolbar`, `incognitoAccess`, or `fileAccess`.
    3. Close the temporary `chrome://extensions` tab via `http://127.0.0.1:9222/json/close/<tab_id>`.
- **Removing Installed Extensions Without Triggering `Error ⋮` or `ERR_FILE_NOT_FOUND`**:
  - To permanently purge retired or corrupted extension entries without leaving ghost entries in `chrome://extensions`, stop Chromium, delete their keys from `.extensions.settings.<id>` in both `~/.config/chromium/Default/Preferences` and `~/.config/chromium/Default/Secure Preferences` with `jq`, and remove their folders from `~/.config/chromium/Default/Extensions/`. Never delete an extension folder while Chromium is running without also disabling/removing its registry state, as Chromium's in-memory `ExtensionRegistry` rewrites `Preferences` on exit and displays the `Error ⋮` badge.

## 6. Automating Embedded Router / Admin Web UIs over CDP
- **Server-side active-page state:** Embedded `.asp`/CGI web servers (e.g., Econet/ZTE/ISP ONTs) track the last-requested `.asp` page in server-side session state. Fetching other `.asp` pages via background `fetch()` shifts the server's active page context and causes subsequent form submissions to redirect or fail. Always navigate the tab back to the target page (`location.href = '/cgi-bin/...'`) and wait for `onload` initialization before calling `doSubmit()`.
- **Custom dropdown (`custom-select`) synchronization:** When `<select>` elements are wrapped in `.custom-select` containers, call the page's native selector helper (e.g., `setSelect(id, val)` / `cs_chooseoption`) and invoke its visibility/change handler (e.g., `Show_DNS_mode()`, `RATypeClick()`, `typev6Click()`) rather than setting `.value` alone, ensuring both hidden form fields and visible UI controls serialize accurately.
- **Upstream IPv6 verification before enabling LAN SLAAC/DHCPv6:** ISP ONTs often display a delegated WAN `/64` prefix (`wan_ipv6_stt: up`) even when the upstream OLT drops outbound IPv6 packets (`ping6_ret: 1`). After enabling LAN SLAAC/DHCPv6, immediately verify end-to-end routing with `ping -6 -c 3 -W 2 2606:4700:4700::1111`; if packet loss is 100%, disable LAN SLAAC and DHCPv6 so clients do not suffer Happy Eyeballs connection timeouts.

## 6. Independent Verification
- Follow the Three-Stage Execution Invariant:
  - Take a screenshot with `grim` (exporting `WAYLAND_DISPLAY=wayland-1`).
  - Run local OCR (`mcp__paddleocr__ocr`) or `vision_analyze` on the captured image, and re-read live DOM state via CDP `Runtime.evaluate`.
  - Verify that the target state is confirmed both in the DOM and on screen.
