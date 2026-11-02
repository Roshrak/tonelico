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

## 5. Automating Embedded Router / Admin Web UIs over CDP
- **Server-side active-page state:** Embedded `.asp`/CGI web servers (e.g., Econet/ZTE/ISP ONTs) track the last-requested `.asp` page in server-side session state. Fetching other `.asp` pages via background `fetch()` shifts the server's active page context and causes subsequent form submissions to redirect or fail. Always navigate the tab back to the target page (`location.href = '/cgi-bin/...'`) and wait for `onload` initialization before calling `doSubmit()`.
- **Custom dropdown (`custom-select`) synchronization:** When `<select>` elements are wrapped in `.custom-select` containers, call the page's native selector helper (e.g., `setSelect(id, val)` / `cs_chooseoption`) and invoke its visibility/change handler (e.g., `Show_DNS_mode()`, `RATypeClick()`, `typev6Click()`) rather than setting `.value` alone, ensuring both hidden form fields and visible UI controls serialize accurately.
- **Upstream IPv6 verification before enabling LAN SLAAC/DHCPv6:** ISP ONTs often display a delegated WAN `/64` prefix (`wan_ipv6_stt: up`) even when the upstream OLT drops outbound IPv6 packets (`ping6_ret: 1`). After enabling LAN SLAAC/DHCPv6, immediately verify end-to-end routing with `ping -6 -c 3 -W 2 2606:4700:4700::1111`; if packet loss is 100%, disable LAN SLAAC and DHCPv6 so clients do not suffer Happy Eyeballs connection timeouts.

## 6. Independent Verification
- Follow the Three-Stage Execution Invariant:
  - Take a screenshot with `grim` (exporting `WAYLAND_DISPLAY=wayland-1`).
  - Run local OCR (`mcp__paddleocr__ocr`) or `vision_analyze` on the captured image, and re-read live DOM state via CDP `Runtime.evaluate`.
  - Verify that the target state is confirmed both in the DOM and on screen.
