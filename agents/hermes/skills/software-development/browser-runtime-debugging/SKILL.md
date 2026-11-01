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

## 5. Independent Verification
- Follow the Three-Stage Execution Invariant:
  - Take a screenshot with `grim` (exporting `WAYLAND_DISPLAY=wayland-1`).
  - Run local OCR (`mcp__paddleocr__ocr`) on the captured image.
  - Verify that the artifact text is 100% absent from the OCR output.
