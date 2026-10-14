#!/home/aesc/.local/share/nix-roots/hermes-agent-env/bin/python3
"""
YouTube Music controller for NixOS desktop assistant.
Enforces:
1. Always use YouTube Music (music.youtube.com).
2. When switching songs, NEVER open a new tab - reuse the existing tab via Chrome DevTools Protocol or playerctl.
"""

import sys
import os
import time
import json
import urllib.parse
import urllib.request
import subprocess
import asyncio
import websockets
import shutil

CDP_BASE = "http://127.0.0.1:9222"
YTM_URL = "https://music.youtube.com"

def get_open_tabs():
    try:
        req = urllib.request.Request(f"{CDP_BASE}/json", headers={"User-Agent": "ytmusic-ctrl"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return []

def activate_tab(tab_id):
    try:
        req = urllib.request.Request(f"{CDP_BASE}/json/activate/{tab_id}", method="POST")
        with urllib.request.urlopen(req, timeout=2):
            pass
    except Exception:
        try:
            req = urllib.request.Request(f"{CDP_BASE}/json/activate/{tab_id}")
            with urllib.request.urlopen(req, timeout=2):
                pass
        except Exception:
            pass

async def cdp_navigate(ws_url, target_url, auto_play=False):
    try:
        async with websockets.connect(ws_url) as ws:
            msg = {
                "id": 1,
                "method": "Page.navigate",
                "params": {"url": target_url}
            }
            await ws.send(json.dumps(msg))
            try:
                await asyncio.wait_for(ws.recv(), timeout=5)
            except Exception:
                pass

            if auto_play:
                js_click = """
                (function() {
                    let playBtn = document.querySelector("ytmusic-card-shelf-renderer ytmusic-play-button-renderer") ||
                                  document.querySelector("ytmusic-responsive-list-item-renderer ytmusic-play-button-renderer") ||
                                  document.querySelector("ytmusic-responsive-list-item-renderer .title a");
                    if (playBtn) {
                        playBtn.click();
                        return true;
                    }
                    return false;
                })()
                """
                for _ in range(8):
                    await asyncio.sleep(0.5)
                    try:
                        await ws.send(json.dumps({
                            "id": 2,
                            "method": "Runtime.evaluate",
                            "params": {"expression": js_click, "returnByValue": True}
                        }))
                        res = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                        if res.get("result", {}).get("result", {}).get("value") is True:
                            break
                    except Exception:
                        pass
    except Exception as e:
        print(f"CDP navigation error: {e}")

async def cdp_evaluate(ws_url, script):
    async with websockets.connect(ws_url) as ws:
        msg = {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": script, "userGesture": True}
        }
        await ws.send(json.dumps(msg))
        resp = await ws.recv()
        return json.loads(resp)

def run_playerctl(action):
    try:
        res = subprocess.run(["playerctl", action], capture_output=True, text=True, timeout=3)
        return res.returncode == 0
    except Exception:
        return False

def switch_next_track():
    # 1. Try system playerctl first
    if run_playerctl("next"):
        print("Switched to next track via playerctl.")
        return

    # 2. Try CDP on existing YouTube Music tab
    tabs = get_open_tabs()
    ytm_tab = None
    for t in tabs:
        url = t.get("url", "")
        if "music.youtube.com" in url or "youtube.com" in url:
            ytm_tab = t
            break

    if ytm_tab and ytm_tab.get("webSocketDebuggerUrl"):
        js_code = """
        (function() {
            var nextBtn = document.querySelector('ytmusic-player-bar .next-button') || document.querySelector('.next-button');
            if (nextBtn) {
                nextBtn.click();
                return 'Clicked next button';
            }
            var video = document.querySelector('video');
            if (video) {
                video.currentTime = video.duration || 99999;
                return 'Fast-forwarded to trigger next track';
            }
            return 'No next button found';
        })();
        """
        try:
            res = asyncio.run(cdp_evaluate(ytm_tab["webSocketDebuggerUrl"], js_code))
            print(f"Switched track in existing tab: {res.get('result', {}).get('result', {}).get('value')}")
            return
        except Exception as e:
            print(f"Failed to trigger next track via CDP: {e}")
            pass

    print("No active YouTube Music session found to switch tracks.")

def switch_prev_track():
    if run_playerctl("previous"):
        print("Switched to previous track via playerctl.")
        return

    tabs = get_open_tabs()
    for t in tabs:
        url = t.get("url", "")
        if ("music.youtube.com" in url or "youtube.com" in url) and t.get("webSocketDebuggerUrl"):
            js_code = "document.querySelector('ytmusic-player-bar .previous-button')?.click();"
            try:
                asyncio.run(cdp_evaluate(t["webSocketDebuggerUrl"], js_code))
                print("Switched to previous track in existing tab.")
                return
            except Exception:
                pass
    print("No active YouTube Music session found.")

def toggle_playback():
    if run_playerctl("play-pause"):
        print("Toggled playback via playerctl.")
        return
    tabs = get_open_tabs()
    for t in tabs:
        url = t.get("url", "")
        if ("music.youtube.com" in url or "youtube.com" in url) and t.get("webSocketDebuggerUrl"):
            js_code = "document.querySelector('#play-pause-button')?.click() || (document.querySelector('video')?.paused ? document.querySelector('video')?.play() : document.querySelector('video')?.pause());"
            try:
                asyncio.run(cdp_evaluate(t["webSocketDebuggerUrl"], js_code))
                print("Toggled playback in existing tab.")
                return
            except Exception:
                pass
    print("No active YouTube Music player found.")

def navigate_via_sway_wtype(target_url):
    wtype_bin = "/home/aesc/.local/bin/wtype"
    if not os.path.exists(wtype_bin):
        wtype_bin = shutil.which("wtype") or "wtype"
    try:
        # Check if Chromium window exists in Sway
        check = subprocess.run(
            ["swaymsg", "-t", "get_tree"],
            capture_output=True, text=True, timeout=2
        )
        if "chromium" not in check.stdout.lower():
            return False

        # Focus Chromium window
        subprocess.run(
            ["swaymsg", '[app_id="chromium-browser" or app_id="chromium"] focus'],
            capture_output=True, text=True, timeout=2
        )
        time.sleep(0.15)
        # Use wtype: Ctrl+L, wait, type URL, wait, Enter
        cmd = [wtype_bin, "-M", "ctrl", "-k", "l", "-m", "ctrl", "-s", "100", target_url, "-s", "100", "-k", "Return"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False

def play_or_search(query):
    should_auto_play = bool(query)
    if not query:
        target_url = YTM_URL
    elif query.startswith("http://") or query.startswith("https://"):
        target_url = query
    else:
        # Search on YouTube Music
        target_url = f"{YTM_URL}/search?q={urllib.parse.quote(query)}"

    tabs = get_open_tabs()

    # Check if a YouTube Music tab already exists via CDP
    ytm_tab = None
    for t in tabs:
        if t.get("type") == "page":
            url = t.get("url", "")
            if "music.youtube.com" in url or "youtube.com" in url:
                ytm_tab = t
                break

    if ytm_tab:
        activate_tab(ytm_tab["id"])
        ws_url = ytm_tab.get("webSocketDebuggerUrl")
        if ws_url:
            asyncio.run(cdp_navigate(ws_url, target_url, auto_play=should_auto_play))
            print(f"Reused existing YouTube Music tab via CDP: {target_url}")
            return

    # Check if blank tab exists via CDP
    for t in tabs:
        if t.get("type") == "page":
            url = t.get("url", "")
            if url in ("chrome://newtab/", "about:blank", ""):
                activate_tab(t["id"])
                ws_url = t.get("webSocketDebuggerUrl")
                if ws_url:
                    asyncio.run(cdp_navigate(ws_url, target_url, auto_play=should_auto_play))
                    print(f"Reused blank tab for YouTube Music: {target_url}")
                    return

    # If any page tab exists in CDP, reuse it
    if tabs:
        for t in tabs:
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                activate_tab(t["id"])
                asyncio.run(cdp_navigate(t["webSocketDebuggerUrl"], target_url, auto_play=should_auto_play))
                print(f"Reused tab {t.get('title', '')[:30]} for YouTube Music: {target_url}")
                return

    # If CDP is not active, try reusing the active Chromium tab via Sway + wtype
    if navigate_via_sway_wtype(target_url):
        print(f"Reused existing Chromium tab via Sway/wtype: {target_url}")
        return

    # Chromium is not running at all, launch it fresh with YouTube Music
    cmd = ["nohup", "/home/aesc/.local/bin/chromium", target_url]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    print(f"Launched Chromium with YouTube Music: {target_url}")

def main():
    if len(sys.argv) < 2:
        play_or_search("")
        return

    cmd = sys.argv[1].lower()
    args = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""

    if cmd in ("next", "switch", "switch-song", "skip"):
        if args:
            # User specified a song to switch to!
            play_or_search(args)
        else:
            # Just switch to the next track in the current player
            switch_next_track()
    elif cmd in ("prev", "previous"):
        switch_prev_track()
    elif cmd in ("toggle", "play-pause", "pause", "resume"):
        toggle_playback()
    elif cmd in ("play", "open", "start"):
        play_or_search(args)
    else:
        # Treat entire argument list as search/play query
        full_query = " ".join(sys.argv[1:])
        play_or_search(full_query)

if __name__ == "__main__":
    main()
