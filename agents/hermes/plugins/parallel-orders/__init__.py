"""Parallel Orders plugin for Hermes Gateway.

Capabilities:
1. Non-Disruptive Concurrent Execution:
   - Never interrupts or cuts off an in-flight turn when a new user message arrives.
   - Spawns an isolated concurrent AIAgent worker (`par_<HHMMSS>_<hex>`) with its own
     session/task ID (preventing shared bash/terminal session lock collisions) and a
     lightweight recent history snapshot (preventing 4-minute context compaction locks).
2. Smart Steer-vs-Parallel Router:
   - Appends follow-up instructions directly into an already-running process (`agent.steer`)
     instead of spawning a separate parallel worker when:
       a) The user replies on Telegram (`reply_to_message_id`) to a running task's prompt
          or its live progress bubble.
       b) The user prefixes the message with `+ `, `steer:`, or `add:`.
       c) The message starts with a natural continuation/modifier phrase (`"also ..."`,
          `"and ..."`, `"make sure ..."`, `"don't forget ..."`, `"instead ..."`,
          `"actually ..."`, `"wait ..."`, `"add ..."`, `"include ..."`, `"remember to ..."`).
   - Prefixing with `// ` or `parallel:` forces a new parallel worker even for `"also ..."` messages.
3. Bottom-Anchored Live Progress Bubbles:
   - Tracks the highest permanent `message_id` per chat (`_LATEST_PERMANENT_MSG_ID`).
   - Whenever any user message or completed process output is sent, all still-running
     progress bubbles (both primary `TurnRunner` and parallel workers) are automatically
     deleted from above the new message and re-posted at the VERY BOTTOM of the chat.
4. Tier-0 Instant Reflex Fast-Path (While Busy):
   - Executes unambiguous zero-LLM instant commands (`fastfetch`, `jobs` / `ps`) in <0.15s
     without waiting on any LLM queue.
5. Strict Gemini 4 Argon Lock + Cooldown Auto-Resume:
   - Forces `fallback_model=None` (`gemini-4-argon` only, never falls back).
   - If all 9 Argon accounts in `aistudio2api` (`127.0.0.1:2048`) are on quota cooldown,
     updates the bottom progress bubble and automatically waits & retries as soon as an
     Argon account becomes ready.
"""

from __future__ import annotations

import asyncio
import contextvars
import datetime
import functools
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("parallel-orders")

_CANCEL_WORDS = frozenset({
    "stop", "cancel", "abort", "halt", "quit",
    "dừng", "dừng lại", "hủy", "huỷ", "thôi",
})

_EXPLICIT_STEER_PREFIXES = ("+ ", "+", "steer:", "add:", "append:", "sửa:", "chỉnh:")
_EXPLICIT_PARALLEL_PREFIXES = ("// ", "//", "parallel:", "par:")

# Natural continuation phrases that indicate the user is adding onto or adjusting
# the currently running process rather than starting an unrelated parallel order.
_ADDITIVE_FOLLOWUP_PREFIXES = (
    "also ",
    "and ",
    "plus ",
    "make sure ",
    "don't forget ",
    "dont forget ",
    "actually ",
    "instead ",
    "wait ",
    "add ",
    "include ",
    "remember to ",
    "by the way ",
    "btw ",
    "while you're at it",
    "while youre at it",
    "skip ",
)

_TOOL_EMOJIS = {
    "terminal": "💻",
    "execute_code": "🐍",
    "web_search": "🔍",
    "web_extract": "🌐",
    "read_file": "📖",
    "write_file": "✍️",
    "patch": "🩹",
    "search_files": "📂",
    "vision_analyze": "👁️",
    "browser_exec": "🌍",
    "delegate_task": "🤖",
    "skill_view": "📚",
    "skill_manage": "🛠️",
    "memory": "🧠",
}

_STATE_DIR = Path("/home/aesc/.hermes/cache/scratch")
_LIVE_STATE_FILE = _STATE_DIR / "parallel_orders_state.json"
_IPC_COMMANDS_FILE = _STATE_DIR / "parallel_orders_commands.jsonl"

# Context variable marking sends that are ephemeral progress bubbles (so they don't count as
# permanent chat messages and never cause two active progress bubbles to leapfrog each other).
_IS_PROGRESS_SEND: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_IS_PROGRESS_SEND", default=False
)

# Highest integer message_id of any permanent message (user message or completed process output)
# per chat_id. Any active progress bubble with message_id < _LATEST_PERMANENT_MSG_ID[chat_id]
# is automatically deleted and re-posted at the bottom of the chat.
_LATEST_PERMANENT_MSG_ID: Dict[str, int] = {}

# Registry of active progress bubbles per chat_id so they can be sunk to the bottom immediately
# when another process finishes and posts its result.
_ACTIVE_PARALLEL_STATES: Dict[str, Set["_ParallelProgressBubble"]] = {}
_ACTIVE_PRIMARY_STATES: Dict[str, Set[tuple[Any, Any]]] = {}
_SINK_TASKS: Dict[str, asyncio.Task] = {}

# Registry of active parallel runs by task_id for smart steering, status inspection, and MCP control.
_ACTIVE_PARALLEL_RUNS: Dict[str, Dict[str, Any]] = {}
_RUNS_LOCK = threading.Lock()


def _msg_id_int(msg_id: Any) -> int:
    """Parse a platform message_id into an int when possible, else 0."""
    if msg_id is None:
        return 0
    try:
        return int(str(msg_id).strip())
    except (ValueError, TypeError):
        return 0


def _write_live_state_snapshot(runner: Any = None) -> None:
    """Persist a real-time JSON snapshot of active primary and parallel runs for MCP inspection."""
    with suppress(Exception):
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()
        runs_out: List[Dict[str, Any]] = []

        if runner is not None:
            with suppress(Exception):
                for skey in runner._snapshot_running_agents():
                    st = runner._peek_session_state(skey)
                    if not st or not st.turn or not st.turn.agent:
                        continue
                    ag = st.turn.agent
                    summary = {}
                    if hasattr(ag, "get_activity_summary"):
                        with suppress(Exception):
                            summary = ag.get_activity_summary() or {}
                    ev = st.turn.event
                    runs_out.append({
                        "task_id": f"primary:{skey}",
                        "kind": "primary",
                        "session_key": skey,
                        "chat_id": str(getattr( getattr(ev, "source", None), "chat_id", "") or ""),
                        "trigger_msg_id": str(getattr(ev, "message_id", "") or ""),
                        "prompt": (getattr(ev, "text", "") or "")[:160],
                        "started_ts": getattr(st.turn, "started_ts", 0.0) or now,
                        "elapsed_s": round(now - (getattr(st.turn, "started_ts", now) or now), 1),
                        "current_tool": summary.get("current_tool"),
                        "api_call_count": summary.get("api_call_count", 0),
                    })

        with _RUNS_LOCK:
            for tid, info in list(_ACTIVE_PARALLEL_RUNS.items()):
                ag = info.get("agent")
                summary = {}
                if ag is not None and hasattr(ag, "get_activity_summary"):
                    with suppress(Exception):
                        summary = ag.get_activity_summary() or {}
                bstate: Optional[_ParallelProgressBubble] = info.get("bubble")
                runs_out.append({
                    "task_id": tid,
                    "kind": "parallel",
                    "session_key": info.get("session_key", ""),
                    "chat_id": info.get("chat_id", ""),
                    "trigger_msg_id": info.get("trigger_msg_id", ""),
                    "progress_msg_id": getattr(bstate, "progress_msg_id", None) if bstate else None,
                    "prompt": info.get("prompt", "")[:160],
                    "started_ts": info.get("started_ts", now),
                    "elapsed_s": round(now - info.get("started_ts", now), 1),
                    "current_tool": summary.get("current_tool") or info.get("current_tool"),
                    "api_call_count": summary.get("api_call_count", 0),
                    "steered_notes": list(info.get("steered_notes", [])),
                })

        payload = {
            "updated_at": now,
            "active_count": len(runs_out),
            "runs": runs_out,
        }
        tmp_path = _LIVE_STATE_FILE.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(_LIVE_STATE_FILE)


def _drain_ipc_commands(runner: Any) -> None:
    """Process any pending steer/cancel commands written by `parallel-ops-mcp`."""
    if not _IPC_COMMANDS_FILE.exists():
        return
    with suppress(Exception):
        raw = _IPC_COMMANDS_FILE.read_text(encoding="utf-8")
        _IPC_COMMANDS_FILE.unlink(missing_ok=True)
        for line in raw.splitlines():
            if not line.strip():
                continue
            cmd = json.loads(line)
            action = cmd.get("action")
            target_id = str(cmd.get("task_id") or "latest").strip()
            text = str(cmd.get("text") or "").strip()

            if action == "steer" and text:
                with _RUNS_LOCK:
                    if target_id == "latest" and _ACTIVE_PARALLEL_RUNS:
                        target_id = max(
                            _ACTIVE_PARALLEL_RUNS.keys(),
                            key=lambda k: _ACTIVE_PARALLEL_RUNS[k].get("started_ts", 0.0),
                        )
                    info = _ACTIVE_PARALLEL_RUNS.get(target_id)
                if info and info.get("agent") is not None:
                    ag = info["agent"]
                    if hasattr(ag, "steer"):
                        ag.steer(text)
                        info.setdefault("steered_notes", []).append(text)
                        bstate = info.get("bubble")
                        if bstate is not None:
                            with bstate.line_lock:
                                bstate.progress_lines.append(f"⏩ Steered: {text[:65]}")
                            bstate.dirty.set()
                        continue
                # Fallback to primary running agent
                if runner is not None:
                    for skey in runner._snapshot_running_agents():
                        if target_id in ("latest", "primary", f"primary:{skey}", skey):
                            st = runner._peek_session_state(skey)
                            if st and st.turn and st.turn.agent:
                                runner._steer_running_agent(st.turn.agent, text)
                                break

            elif action == "cancel":
                with _RUNS_LOCK:
                    if target_id == "latest" and _ACTIVE_PARALLEL_RUNS:
                        target_id = max(
                            _ACTIVE_PARALLEL_RUNS.keys(),
                            key=lambda k: _ACTIVE_PARALLEL_RUNS[k].get("started_ts", 0.0),
                        )
                    info = _ACTIVE_PARALLEL_RUNS.get(target_id)
                if info and info.get("agent") is not None:
                    ag = info["agent"]
                    if hasattr(ag, "interrupt"):
                        ag.interrupt("Cancelled via parallel-ops-mcp")


def _record_permanent_message(chat_id: Any, message_id: Any) -> None:
    """Record a permanent message (user inbound or process result) and schedule bottom-sinking."""
    cid = str(chat_id or "").strip()
    mid = _msg_id_int(message_id)
    if not cid or mid <= 0:
        return
    prev = _LATEST_PERMANENT_MSG_ID.get(cid, 0)
    if mid > prev:
        _LATEST_PERMANENT_MSG_ID[cid] = mid
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    existing = _SINK_TASKS.get(cid)
    if existing is None or existing.done():
        _SINK_TASKS[cid] = loop.create_task(_sink_all_progress_bubbles_below(cid))


async def _send_as_progress(coro):
    """Await an adapter send coroutine with _IS_PROGRESS_SEND=True so it is not treated as a result."""
    token = _IS_PROGRESS_SEND.set(True)
    try:
        return await coro
    finally:
        _IS_PROGRESS_SEND.reset(token)


class _ParallelProgressBubble:
    def __init__(
        self,
        adapter: Any,
        chat_id: str,
        reply_anchor: Any,
        thread_metadata: Any,
        label: str,
        task_id: str = "",
    ) -> None:
        self.adapter = adapter
        self.chat_id = chat_id
        self.reply_anchor = reply_anchor
        self.thread_metadata = thread_metadata
        self.label = label
        self.task_id = task_id
        self.progress_msg_id: Optional[str] = None
        self.progress_lines: List[str] = []
        self.line_lock = threading.Lock()
        self.async_lock = asyncio.Lock()
        self.dirty = threading.Event()
        self.stop = False
        self.last_sent_body = ""

    def render_body(self) -> str:
        with self.line_lock:
            lines_copy = list(self.progress_lines[-8:])
        if not lines_copy:
            return f"⚡ **{self.label}**\n⏳ Working..."
        return f"⚡ **{self.label}**\n" + "\n".join(lines_copy)

    async def ensure_at_bottom_or_update(self, force_update: bool = False) -> None:
        if self.stop:
            return
        async with self.async_lock:
            if self.stop:
                return
            body = self.render_body()
            latest_perm = _LATEST_PERMANENT_MSG_ID.get(self.chat_id, 0)
            cur_id = _msg_id_int(self.progress_msg_id)
            needs_reanchor = bool(self.progress_msg_id and latest_perm > cur_id > 0)

            if needs_reanchor:
                old_id = self.progress_msg_id
                self.progress_msg_id = None
                with suppress(Exception):
                    await self.adapter.delete_message(self.chat_id, str(old_id))
                with suppress(Exception):
                    res = await _send_as_progress(
                        self.adapter.send(
                            chat_id=self.chat_id,
                            content=body,
                            reply_to=self.reply_anchor,
                            metadata=self.thread_metadata,
                        )
                    )
                    new_id = getattr(res, "message_id", None)
                    if new_id:
                        self.progress_msg_id = str(new_id)
                        self.last_sent_body = body
                return

            if not self.progress_msg_id:
                with suppress(Exception):
                    res = await _send_as_progress(
                        self.adapter.send(
                            chat_id=self.chat_id,
                            content=body,
                            reply_to=self.reply_anchor,
                            metadata=self.thread_metadata,
                        )
                    )
                    new_id = getattr(res, "message_id", None)
                    if new_id:
                        self.progress_msg_id = str(new_id)
                        self.last_sent_body = body
                return

            if (force_update or self.dirty.is_set()) and body != self.last_sent_body:
                self.dirty.clear()
                self.last_sent_body = body
                with suppress(Exception):
                    await self.adapter.edit_message(
                        chat_id=self.chat_id,
                        message_id=self.progress_msg_id,
                        content=body,
                        metadata=self.thread_metadata,
                    )

    async def cleanup(self) -> None:
        self.stop = True
        async with self.async_lock:
            if self.progress_msg_id:
                old_id = self.progress_msg_id
                self.progress_msg_id = None
                with suppress(Exception):
                    await self.adapter.delete_message(self.chat_id, str(old_id))


async def _sink_primary_progress_bubble(turn_runner: Any, st: Any, chat_id: str) -> None:
    """If the primary turn's progress bubble is above a newer permanent message, move it below."""
    ctx = getattr(turn_runner, "_ctx", None)
    if ctx is None or not ctx._run_still_current() or turn_runner._agent_interrupted():
        return
    lock = getattr(st, "_sink_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        st._sink_lock = lock
    async with lock:
        if not ctx._run_still_current() or not st.progress_msg_id:
            return
        latest_perm = _LATEST_PERMANENT_MSG_ID.get(chat_id, 0)
        cur_id = _msg_id_int(st.progress_msg_id)
        if not (latest_perm > cur_id > 0):
            return
        old_id = str(st.progress_msg_id)
        st.progress_msg_id = None
        with suppress(Exception):
            await st.adapter.delete_message(chat_id, old_id)
        lines = list(st.progress_lines) if st.progress_lines else [getattr(st, "_header_line", "⚡ **Task**\n⏳ Working...")]
        text = "\n".join(str(x) for x in lines[-10:])
        with suppress(Exception):
            res = await _send_as_progress(turn_runner._send_progress_text(st, text))
            if getattr(res, "success", False) and getattr(res, "message_id", None):
                st.progress_msg_id = res.message_id


async def _sink_all_progress_bubbles_below(chat_id: str) -> None:
    """Wait briefly for burst sends to settle, then sink all active progress bubbles to the bottom."""
    await asyncio.sleep(0.15)
    for turn_runner, st in list(_ACTIVE_PRIMARY_STATES.get(chat_id, ())):
        with suppress(Exception):
            await _sink_primary_progress_bubble(turn_runner, st, chat_id)
    for pstate in list(_ACTIVE_PARALLEL_STATES.get(chat_id, ())):
        with suppress(Exception):
            await pstate.ensure_at_bottom_or_update(force_update=False)


def _is_additive_followup(text: str) -> bool:
    """Return True when `text` is a natural addition/adjustment to an already-running task."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    lower = stripped.lower()
    if any(lower.startswith(p) for p in _EXPLICIT_PARALLEL_PREFIXES):
        return False
    if any(lower.startswith(p) for p in _EXPLICIT_STEER_PREFIXES):
        return True
    if any(lower.startswith(p) for p in _ADDITIVE_FOLLOWUP_PREFIXES):
        return True
    return False


def _strip_mode_prefix(text: str) -> str:
    """Strip explicit steer (`+`) or parallel (`//`) prefixes from the prompt text."""
    stripped = (text or "").strip()
    lower = stripped.lower()
    for p in _EXPLICIT_PARALLEL_PREFIXES + _EXPLICIT_STEER_PREFIXES:
        if lower.startswith(p):
            return stripped[len(p):].strip() or stripped
    return stripped


async def _try_smart_steer_into_running_process(
    runner: Any,
    event: Any,
    session_key: str,
) -> bool:
    """Attempt to steer/append `event` into an active process (primary or parallel) when appropriate.

    Routes into an existing process when:
    1. User explicitly replies (`reply_to_message_id`) to a running task's trigger message or
       its live progress bubble.
    2. User starts the message with `+` / `steer:` / `add:` or a natural continuation phrase
       (`"also ..."`, `"and ..."`, `"make sure ..."`, `"don't forget ..."`, `"instead ..."`, etc.).
    Returns True if steered into an active process, False if it should run as a parallel order.
    """
    from gateway.run import _AGENT_PENDING_SENTINEL

    raw_text = (getattr(event, "text", None) or "").strip()
    if not raw_text:
        return False
    lower = raw_text.lower()
    if any(lower.startswith(p) for p in _EXPLICIT_PARALLEL_PREFIXES):
        event.text = _strip_mode_prefix(raw_text)
        return False

    source = getattr(event, "source", None)
    chat_id_str = str(getattr(source, "chat_id", "") or "")
    reply_to_id = str(getattr(event, "reply_to_message_id", "") or "").strip()
    steer_body = _strip_mode_prefix(raw_text)

    # 1. Check if replying directly to a specific parallel worker's prompt or progress bubble
    target_parallel_info: Optional[Dict[str, Any]] = None
    if reply_to_id:
        with _RUNS_LOCK:
            for info in _ACTIVE_PARALLEL_RUNS.values():
                if info.get("chat_id") != chat_id_str:
                    continue
                bstate = info.get("bubble")
                b_msg_id = str(getattr(bstate, "progress_msg_id", "") or "") if bstate else ""
                if reply_to_id in (str(info.get("trigger_msg_id") or ""), b_msg_id):
                    target_parallel_info = info
                    break

    # 2. Check if replying directly to the primary turn's prompt or progress bubble
    target_primary_agent: Any = None
    _busy_state = runner._peek_session_state(session_key)
    primary_agent = _busy_state.turn.agent if (_busy_state and _busy_state.turn) else None
    if primary_agent is _AGENT_PENDING_SENTINEL:
        primary_agent = None

    if reply_to_id and target_parallel_info is None and primary_agent is not None:
        primary_ev = getattr(_busy_state.turn, "event", None)
        primary_trig_id = str(getattr(primary_ev, "message_id", "") or "")
        primary_prog_ids = {
            str(getattr(st, "progress_msg_id", "") or "")
            for _, st in list(_ACTIVE_PRIMARY_STATES.get(chat_id_str, ()))
        }
        if reply_to_id == primary_trig_id or reply_to_id in primary_prog_ids:
            target_primary_agent = primary_agent

    # 3. If not an explicit reply to a specific process, check if the text is an additive follow-up
    if target_parallel_info is None and target_primary_agent is None:
        if not _is_additive_followup(raw_text):
            return False
        # Route to the most recently started active process in this chat (parallel or primary)
        latest_par: Optional[Dict[str, Any]] = None
        with _RUNS_LOCK:
            chat_pars = [
                info
                for info in _ACTIVE_PARALLEL_RUNS.values()
                if info.get("chat_id") == chat_id_str and info.get("agent") is not None
            ]
            if chat_pars:
                latest_par = max(chat_pars, key=lambda x: x.get("started_ts", 0.0))

        primary_started = (
            getattr(_busy_state.turn, "started_ts", 0.0)
            if (_busy_state and _busy_state.turn and primary_agent is not None)
            else 0.0
        )
        if latest_par and latest_par.get("started_ts", 0.0) >= (primary_started or 0.0):
            target_parallel_info = latest_par
        elif primary_agent is not None:
            target_primary_agent = primary_agent
        elif latest_par is not None:
            target_parallel_info = latest_par

    # Execute steer into parallel worker if selected
    if target_parallel_info is not None:
        ag = target_parallel_info.get("agent")
        if ag is not None and hasattr(ag, "steer"):
            steered = runner._try_agent_verb(
                ag, "steer", steer_body, session_key, event=event
            )
            if steered:
                target_parallel_info.setdefault("steered_notes", []).append(steer_body)
                bstate: Optional[_ParallelProgressBubble] = target_parallel_info.get("bubble")
                if bstate is not None:
                    short_note = steer_body[:68] + ("…" if len(steer_body) > 68 else "")
                    with bstate.line_lock:
                        bstate.progress_lines.append(f"⏩ Added to task: {short_note}")
                    bstate.dirty.set()
                    await bstate.ensure_at_bottom_or_update(force_update=True)
                _write_live_state_snapshot(runner)
                logger.info(
                    "parallel-orders: steered follow-up into parallel worker %s: %r",
                    target_parallel_info.get("task_id"),
                    steer_body[:80],
                )
                return True

    # Execute steer into primary agent if selected
    if target_primary_agent is not None and hasattr(target_primary_agent, "steer"):
        steered = runner._try_agent_verb(
            target_primary_agent, "steer", steer_body, session_key, event=event
        )
        if steered:
            short_note = steer_body[:68] + ("…" if len(steer_body) > 68 else "")
            for turn_runner, st in list(_ACTIVE_PRIMARY_STATES.get(chat_id_str, ())):
                with suppress(Exception):
                    st.progress_lines.append(f"⏩ Added to task: {short_note}")
                    await _sink_primary_progress_bubble(turn_runner, st, chat_id_str)
            _write_live_state_snapshot(runner)
            logger.info(
                "parallel-orders: steered follow-up into primary session %s: %r",
                session_key,
                steer_body[:80],
            )
            return True

    return False


async def _try_instant_reflex_while_busy(
    runner: Any,
    event: Any,
    session_key: str,
) -> bool:
    """Tier-0 Zero-Wait Reflex lane for instant unambiguous OS commands while busy."""
    text = (getattr(event, "text", None) or "").strip()
    if not text or getattr(event, "media_urls", None):
        return False
    lower = text.lower()
    source = event.source
    adapter = runner._delivery_adapter_for(source)
    if not adapter:
        return False
    chat_id_str = str(source.chat_id or "")
    reply_anchor = runner._reply_anchor_for_event(event)
    thread_metadata = runner._thread_metadata_for_source(source, reply_anchor)

    if lower == "fastfetch":
        def _run_ff() -> str:
            env = os.environ.copy()
            env["WAYLAND_DISPLAY"] = env.get("WAYLAND_DISPLAY", "wayland-1")
            with suppress(Exception):
                subprocess.Popen(
                    ["kitty", "--hold", "-e", "fastfetch"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    start_new_session=True,
                )
            proc = subprocess.run(
                ["fastfetch", "--pipe"],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
            return (proc.stdout or "").strip()

        ff_out = await asyncio.to_thread(_run_ff)
        reply = (
            f"Launched `fastfetch` on your monitor and captured output:\n```text\n{ff_out[:3500]}\n```"
            if ff_out
            else "Launched `fastfetch` on your monitor."
        )
        sent = await adapter.send(
            chat_id=source.chat_id,
            content=reply,
            reply_to=reply_anchor,
            metadata=thread_metadata,
        )
        _record_permanent_message(chat_id_str, getattr(sent, "message_id", None))
        return True

    if lower in ("jobs", "ps", "running orders", "active orders"):
        _write_live_state_snapshot(runner)
        data = {}
        with suppress(Exception):
            data = json.loads(_LIVE_STATE_FILE.read_text(encoding="utf-8"))
        runs = data.get("runs", [])
        if not runs:
            msg = "No active background orders right now."
        else:
            lines = [f"⚡ **Active Orders ({len(runs)})**:"]
            for r in runs:
                tool_str = f" — `{r['current_tool']}`" if r.get("current_tool") else ""
                lines.append(
                    f"• `{r['task_id']}` ({r['elapsed_s']}s){tool_str}: _{r.get('prompt', '')[:60]}_"
                )
            lines.append("\nTip: Reply to any bubble or start with `+ ` to add to a running task, or `// ` to force parallel.")
            msg = "\n".join(lines)
        sent = await adapter.send(
            chat_id=source.chat_id,
            content=msg,
            reply_to=reply_anchor,
            metadata=thread_metadata,
        )
        _record_permanent_message(chat_id_str, getattr(sent, "message_id", None))
        return True

    mc_ctl_match = re.match(
        r"^(?:(activate|start|enable|turn on|deactivate|stop|disable|turn off|turn of|status)\s+(?:the\s+)?(?:mc|minecraft)\s*(?:auto\s*)?(?:chat\s*)?(?:responder|respond|reply)|(?:mc|minecraft)\s*(?:auto\s*)?(?:chat\s*)?(?:responder|respond|reply)\s+(on|off|of|start|stop|activate|deactivate|status))(?:\s+(alt|miracle|miracle_involker|roshrak|main))?[!?. ]*$",
        lower,
    )
    if mc_ctl_match:
        verb = (mc_ctl_match.group(1) or mc_ctl_match.group(2) or "").strip()
        acct = (mc_ctl_match.group(3) or "roshrak").strip()
        if verb in ("activate", "start", "enable", "turn on", "on"):
            ctl_action = "start"
        elif verb in ("deactivate", "stop", "disable", "turn off", "turn of", "off", "of"):
            ctl_action = "stop"
        else:
            ctl_action = "status"

        def _run_mc_ctl() -> str:
            res = subprocess.run(
                ["/home/aesc/.local/bin/mc_responder_ctl", ctl_action, acct],
                capture_output=True,
                text=True,
                timeout=10,
            )
            try:
                info = json.loads(res.stdout)
                st = info.get("status", ctl_action)
                gate = info.get("gate", {})
                running = info.get("running", [])
                if st == "activated":
                    return f"✅ **MC Chat Responder Activated**\n• Account: `{gate.get('user')}` (`{gate.get('persona')}` persona)\n• Instance: `{gate.get('instance')}`\n• Process: `{running[0] if running else 'starting'}`"
                elif st == "deactivated":
                    return "🛑 **MC Chat Responder Deactivated** (0 processes running)."
                else:
                    return f"ℹ️ **MC Chat Responder Status**: `{st}`\n• Gate Active: `{gate.get('active')}` (`{gate.get('user')}`)\n• Running: `{len(running)}` process(es)"
            except Exception:
                return (res.stdout or res.stderr or "Done.").strip()

        reply_msg = await asyncio.to_thread(_run_mc_ctl)
        sent = await adapter.send(
            chat_id=source.chat_id,
            content=reply_msg,
            reply_to=reply_anchor,
            metadata=thread_metadata,
        )
        _record_permanent_message(chat_id_str, getattr(sent, "message_id", None))
        return True

    return False


def _argon_ready_account_count() -> int:
    """Check how many `gemini-4-argon` accounts are currently ready (not cooling down) in aistudio2api."""
    with suppress(Exception):
        req = urllib.request.Request("http://127.0.0.1:2048/v1/models/gemini-4-argon")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                return 1
    return 0


def _sanitize_history_snapshot(
    raw_history: Optional[List[Dict[str, Any]]],
    max_messages: int = 6,
    max_total_chars: int = 6000,
) -> List[Dict[str, Any]]:
    """Return a lightweight recent transcript window so parallel workers never trigger context compaction."""
    if not raw_history or not isinstance(raw_history, list):
        return []
    clean_turns: List[Dict[str, Any]] = []
    for msg in raw_history:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        if role == "assistant" and msg.get("tool_calls"):
            continue
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        text = content.strip()
        if len(text) > 1200:
            text = text[:1200] + "\n...[truncated for fast parallel context]..."
        clean_turns.append({"role": role, "content": text})

    while clean_turns and clean_turns[-1].get("role") != "assistant":
        clean_turns.pop()

    selected: List[Dict[str, Any]] = []
    total_chars = 0
    for msg in reversed(clean_turns[-max_messages:]):
        c_len = len(msg.get("content", ""))
        if selected and total_chars + c_len > max_total_chars:
            break
        selected.append(msg)
        total_chars += c_len
    selected.reverse()
    return selected


async def _sync_parallel_turn_to_transcript(
    runner: Any,
    adapter: Any,
    session_key: str,
    session_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    """Wait until the active session lock clears, then append the parallel exchange to the transcript."""
    try:
        for _ in range(600):
            active = getattr(adapter, "_active_sessions", None) or {}
            guard = active.get(session_key)
            if guard is None or guard.is_set():
                break
            await asyncio.sleep(1.0)
        await asyncio.sleep(0.5)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        store = getattr(runner, "session_store", None)
        if store is not None and hasattr(store, "append_to_transcript"):
            if user_text:
                await asyncio.to_thread(
                    store.append_to_transcript,
                    session_id,
                    {"role": "user", "content": user_text, "timestamp": now_iso},
                )
            if assistant_text:
                await asyncio.to_thread(
                    store.append_to_transcript,
                    session_id,
                    {"role": "assistant", "content": assistant_text, "timestamp": now_iso},
                )
        evict = getattr(runner, "_evict_cached_agent", None)
        if callable(evict):
            with suppress(Exception):
                evict(session_key)
        logger.info("parallel-orders: synced parallel turn to transcript for %s", session_key)
    except Exception as exc:
        logger.debug("parallel-orders: transcript sync skipped for %s: %s", session_key, exc)


async def _run_parallel_order_inner(
    runner: Any,
    event: Any,
    session_key: str,
    task_id: str,
) -> None:
    from gateway.platforms.base import BasePlatformAdapter, should_send_media_as_audio
    from gateway.run import (
        _build_media_placeholder,
        _checkpoint_agent_kwargs,
        _collect_auto_append_media_tags,
        _current_max_iterations,
        _load_gateway_config,
        _platform_config_key,
    )
    from gateway.run_notifications import _IMAGE_EXTS, _VIDEO_EXTS
    from run_agent import AIAgent

    source = event.source
    adapter = runner._delivery_adapter_for(source)
    if not adapter:
        logger.warning("parallel-orders: no adapter for %s in %s", source.platform, task_id)
        return

    chat_id_str = str(source.chat_id or "")
    _record_permanent_message(chat_id_str, getattr(event, "message_id", None))

    reply_anchor = runner._reply_anchor_for_event(event)
    _thread_metadata = runner._thread_metadata_for_source(source, reply_anchor)
    media_urls = list(event.media_urls or [])
    media_types = list(event.media_types or [])

    # 1. Prepare user prompt (text, voice transcription, or media placeholder)
    prompt = _strip_mode_prefix((event.text or "").strip())
    if runner._pending_event_audio_paths(event):
        with suppress(Exception):
            prompt, _ = await runner._transcribe_and_echo_pending_voice(
                event,
                adapter,
                source,
                prompt,
                log_context="Parallel-order-voice",
                metadata=_thread_metadata,
            )
    if not prompt and media_urls:
        prompt = _build_media_placeholder(event)
    if not prompt:
        return

    # 2. Load lightweight snapshot of the current session's conversation history
    session_id = None
    history_snapshot: List[Dict[str, Any]] = []
    try:
        session_entry = await runner.async_session_store.get_or_create_session(source)
        session_id = getattr(session_entry, "session_id", None)
        if session_id:
            raw_history = await runner.async_session_store.load_transcript(session_id)
            history_snapshot = _sanitize_history_snapshot(raw_history)
    except Exception as exc:
        logger.debug("parallel-orders: history snapshot load failed: %s", exc)

    # 3. Create live bottom-anchored progress bubble (auto-deleted before final delivery)
    short_label = prompt.splitlines()[0][:36] + ("…" if len(prompt.splitlines()[0]) > 36 else "")
    pstate = _ParallelProgressBubble(
        adapter=adapter,
        chat_id=chat_id_str,
        reply_anchor=reply_anchor,
        thread_metadata=_thread_metadata,
        label=f"Parallel: {short_label}",
        task_id=task_id,
    )
    _ACTIVE_PARALLEL_STATES.setdefault(chat_id_str, set()).add(pstate)
    with _RUNS_LOCK:
        _ACTIVE_PARALLEL_RUNS[task_id] = {
            "task_id": task_id,
            "session_key": session_key,
            "chat_id": chat_id_str,
            "trigger_msg_id": str(getattr(event, "message_id", "") or ""),
            "prompt": prompt,
            "started_ts": time.time(),
            "bubble": pstate,
            "agent": None,
            "current_tool": None,
            "steered_notes": [],
        }
    _write_live_state_snapshot(runner)
    await pstate.ensure_at_bottom_or_update(force_update=True)

    async def _progress_updater() -> None:
        while not pstate.stop:
            await asyncio.sleep(1.0)
            if pstate.stop:
                break
            _drain_ipc_commands(runner)
            await pstate.ensure_at_bottom_or_update(force_update=False)

    updater_task = asyncio.create_task(_progress_updater())

    def _on_tool_progress(
        event_type: str,
        tool_name: Optional[str] = None,
        preview: Optional[str] = None,
        args: Optional[dict] = None,
        **kwargs: Any,
    ) -> None:
        if event_type in ("_thinking", "thinking") or tool_name == "_thinking":
            text = (preview if tool_name == "_thinking" else tool_name) or ""
            text = str(text).strip()
            if text:
                short = text[:90] + ("…" if len(text) > 90 else "")
                with pstate.line_lock:
                    pstate.progress_lines.append(f"💬 {short}")
                pstate.dirty.set()
            return
        if event_type != "tool.started" or not tool_name or tool_name == "clarify":
            return
        emoji = _TOOL_EMOJIS.get(tool_name, "🔧")
        detail = ""
        if preview:
            detail = str(preview).strip()
        elif isinstance(args, dict):
            for k in ("command", "query", "path", "url", "pattern"):
                if args.get(k):
                    detail = str(args[k]).strip().splitlines()[0]
                    break
        if detail:
            detail = detail[:65] + ("…" if len(detail) > 65 else "")
            line = f"{emoji} `{tool_name}` — {detail}"
        else:
            line = f"{emoji} `{tool_name}`"
        with pstate.line_lock:
            pstate.progress_lines.append(line)
        with _RUNS_LOCK:
            if task_id in _ACTIVE_PARALLEL_RUNS:
                _ACTIVE_PARALLEL_RUNS[task_id]["current_tool"] = tool_name
        _write_live_state_snapshot(runner)
        pstate.dirty.set()

    try:
        user_config = _load_gateway_config()
        model, runtime_kwargs = runner._resolve_session_agent_runtime(
            source=source, session_key=session_key, user_config=user_config
        )
        platform_key = _platform_config_key(source.platform)
        enabled_toolsets, disabled_toolsets = runner._resolve_turn_toolsets(
            user_config, source, platform_key
        )
        pr = runner._provider_routing
        max_iterations = min(_current_max_iterations(), 30)
        reasoning_config = runner._resolve_session_reasoning_config(
            source=source, session_key=session_key, model=model
        )
        service_tier = runner._resolve_session_service_tier(
            source=source, session_key=session_key
        )
        turn_route = runner._resolve_turn_agent_config(prompt, model, runtime_kwargs)

        enriched_prompt = prompt
        image_paths = [
            path
            for i, path in enumerate(media_urls)
            if (media_types[i] if i < len(media_types) else "").startswith("image/")
        ]
        if image_paths:
            with suppress(Exception):
                enriched_prompt = await runner._enrich_message_with_vision(prompt, image_paths)

        ephemeral_prompt = ""
        with suppress(Exception):
            ephemeral_prompt = runner._get_system_prompt_for_channel(
                source.platform,
                source.chat_id or "",
                thread_id=getattr(source, "thread_id", None),
                parent_id=getattr(source, "parent_chat_id", None),
            ) or ""

        def run_sync_once():
            agent = AIAgent(
                model=turn_route["model"],
                **turn_route["runtime"],
                **_checkpoint_agent_kwargs(user_config),
                max_iterations=max_iterations,
                quiet_mode=True,
                verbose_logging=False,
                enabled_toolsets=enabled_toolsets,
                disabled_toolsets=disabled_toolsets,
                ephemeral_system_prompt=ephemeral_prompt or None,
                reasoning_config=reasoning_config,
                service_tier=service_tier,
                request_overrides=turn_route.get("request_overrides"),
                providers_allowed=pr.get("only"),
                providers_ignored=pr.get("ignore"),
                providers_order=pr.get("order"),
                provider_sort=pr.get("sort"),
                provider_require_parameters=pr.get("require_parameters", False),
                provider_data_collection=pr.get("data_collection"),
                session_id=task_id,
                platform=platform_key,
                user_id=source.user_id,
                user_id_alt=source.user_id_alt,
                user_name=source.user_name,
                chat_id=source.chat_id,
                chat_name=source.chat_name,
                chat_type=source.chat_type,
                thread_id=source.thread_id,
                session_db=getattr(runner._session_db, "_db", runner._session_db),
                fallback_model=turn_route.get("fallback_model") or user_config.get("fallback_providers"),
                load_soul_identity=True,
            )
            agent.tool_progress_callback = _on_tool_progress
            agent.thinking_progress = True
            with _RUNS_LOCK:
                if task_id in _ACTIVE_PARALLEL_RUNS:
                    _ACTIVE_PARALLEL_RUNS[task_id]["agent"] = agent
            _write_live_state_snapshot(runner)
            try:
                return agent.run_conversation(
                    user_message=enriched_prompt,
                    conversation_history=history_snapshot,
                    task_id=task_id,
                )
            finally:
                runner._cleanup_agent_resources(agent)

        result = None
        for attempt in range(24):
            result = await runner._run_in_executor_with_context(run_sync_once)
            err_str = str((result or {}).get("error") or "")
            final_str = str((result or {}).get("final_response") or "")
            combined_err = (err_str + " " + final_str).lower()
            if (
                not final_str.strip()
                and ("cooling down" in combined_err or "429" in combined_err or "rate limit" in combined_err)
            ):
                with pstate.line_lock:
                    pstate.progress_lines.append(
                        f"⏸️ Argon accounts cooling down — auto-retrying (attempt {attempt + 1}/24)..."
                    )
                pstate.dirty.set()
                await pstate.ensure_at_bottom_or_update(force_update=True)
                await asyncio.sleep(30.0)
                continue
            break

    except Exception as exc:
        logger.exception("parallel-orders: parallel task %s failed", task_id)
        with suppress(Exception):
            err_res = await adapter.send(
                chat_id=source.chat_id,
                content=f"⚠️ Parallel task error: {exc}",
                reply_to=reply_anchor,
                metadata=_thread_metadata,
            )
            _record_permanent_message(chat_id_str, getattr(err_res, "message_id", None))
        return
    finally:
        with _RUNS_LOCK:
            _ACTIVE_PARALLEL_RUNS.pop(task_id, None)
        _write_live_state_snapshot(runner)
        _ACTIVE_PARALLEL_STATES.get(chat_id_str, set()).discard(pstate)
        pstate.stop = True
        updater_task.cancel()
        with suppress(Exception):
            await updater_task
        await pstate.cleanup()

    response = (result.get("final_response", "") if result else "") or ""
    if not response and result and result.get("error"):
        response = f"⚠️ {result['error']}"

    # Append any tool-emitted MEDIA: tags from this turn
    if result and "MEDIA:" not in response:
        with suppress(Exception):
            media_tags, has_voice = _collect_auto_append_media_tags(
                result.get("messages", []),
                history_offset=len(history_snapshot),
                history_media_paths=set(),
            )
            if media_tags:
                unique_tags = (["[[audio_as_voice]]"] if has_voice else []) + list(
                    dict.fromkeys(media_tags)
                )
                response = (response + "\n" + "\n".join(unique_tags)).strip()

    raw_final_for_transcript = response
    images, media_files, text_content = [], [], ""
    if response:
        media_files, response = adapter.extract_media(response)
        media_files = BasePlatformAdapter.filter_media_delivery_paths(media_files)
        images, text_content = adapter.extract_images(response)

    if text_content and text_content.strip():
        sent = await adapter.send(
            chat_id=source.chat_id,
            content=text_content,
            reply_to=reply_anchor,
            metadata=_thread_metadata,
        )
        _record_permanent_message(chat_id_str, getattr(sent, "message_id", None))
    elif not images and not media_files:
        sent = await adapter.send(
            chat_id=source.chat_id,
            content="(Completed)",
            reply_to=reply_anchor,
            metadata=_thread_metadata,
        )
        _record_permanent_message(chat_id_str, getattr(sent, "message_id", None))

    for image_url, alt_text in images or []:
        with suppress(Exception):
            sent = await adapter.send_image(
                chat_id=source.chat_id,
                image_url=image_url,
                caption=alt_text,
                metadata=_thread_metadata,
            )
            _record_permanent_message(chat_id_str, getattr(sent, "message_id", None))

    # Separate local image files so multi-image bursts use send_multiple_images when available
    image_media_paths: List[str] = []
    other_media_items: List[tuple[str, bool]] = []
    for media_path, is_voice in media_files or []:
        ext = os.path.splitext(media_path)[1].lower()
        if ext in _IMAGE_EXTS and not is_voice:
            image_media_paths.append(media_path)
        else:
            other_media_items.append((media_path, is_voice))

    if len(image_media_paths) > 1 and hasattr(adapter, "send_multiple_images"):
        with suppress(Exception):
            sent = await adapter.send_multiple_images(
                chat_id=source.chat_id,
                images=[(f"file://{p}", "") for p in image_media_paths],
                metadata=_thread_metadata,
            )
            _record_permanent_message(chat_id_str, getattr(sent, "message_id", None))
    else:
        for img_path in image_media_paths:
            with suppress(Exception):
                sent = await adapter.send_image_file(
                    chat_id=source.chat_id,
                    image_path=img_path,
                    metadata=_thread_metadata,
                )
                _record_permanent_message(chat_id_str, getattr(sent, "message_id", None))

    for media_path, is_voice in other_media_items:
        ext = os.path.splitext(media_path)[1].lower()
        with suppress(Exception):
            if should_send_media_as_audio(source.platform, ext, is_voice):
                sent = await adapter.send_voice(
                    chat_id=source.chat_id,
                    audio_path=media_path,
                    metadata=_thread_metadata,
                    is_voice=is_voice,
                )
            elif ext in _VIDEO_EXTS:
                sent = await adapter.send_video(
                    chat_id=source.chat_id,
                    video_path=media_path,
                    metadata=_thread_metadata,
                )
            else:
                sent = await adapter.send_document(
                    chat_id=source.chat_id,
                    file_path=media_path,
                    metadata=_thread_metadata,
                )
            _record_permanent_message(chat_id_str, getattr(sent, "message_id", None))

    if session_id:
        runner._track_background_task(
            _sync_parallel_turn_to_transcript(
                runner,
                adapter,
                session_key,
                session_id,
                prompt,
                raw_final_for_transcript,
            )
        )


async def _run_parallel_order(
    runner: Any,
    event: Any,
    session_key: str,
    task_id: str,
) -> None:
    with runner._profile_scope_for_source(event.source):
        await _run_parallel_order_inner(runner, event, session_key, task_id)


def _should_defer_to_builtin_busy_handler(event: Any) -> bool:
    """Return True for control/cancel/slash/internal events that should not spawn a parallel agent."""
    if getattr(event, "internal", False):
        return True
    if event.get_command():
        return True
    text = (event.text or "").strip()
    lower = text.lower()
    if lower in _CANCEL_WORDS:
        return True
    if lower.startswith("/"):
        return True
    return False


_DESIRED_FALLBACK_CHAIN = [
    {"provider": "antigravity-manager", "model": "gemini-4-argon-high"},
    {"provider": "aistudio2api", "model": "gemini-3.8-flash-high"},
    {"provider": "antigravity-manager", "model": "gemini-3.8-flash-high"},
]


def _is_primary_aistudio_argon(agent: Any) -> bool:
    if getattr(agent, "_fallback_activated", False):
        return False
    prov = str(getattr(agent, "provider", "") or "").lower()
    burl = str(getattr(agent, "base_url", "") or "").lower()
    mdl = str(getattr(agent, "model", "") or "").lower()
    return ("aistudio" in prov or ":2048" in burl) and "argon" in mdl


def _normalize_agent_argon_routing(agent: Any) -> None:
    with suppress(Exception):
        mdl = str(getattr(agent, "model", "") or "").strip()
        mdl_lower = mdl.lower()
        if "argon" in mdl_lower and mdl != "gemini-4-argon-high":
            agent.model = "gemini-4-argon-high"
        elif "3.8-flash" in mdl_lower and mdl != "gemini-3.8-flash-high":
            agent.model = "gemini-3.8-flash-high"

        fb_chain = getattr(agent, "_fallback_chain", None)
        desired_tuples = [(d["provider"], d["model"]) for d in _DESIRED_FALLBACK_CHAIN]
        cur_tuples = [
            (str(d.get("provider", "")).strip().lower(), str(d.get("model", "")).strip())
            for d in (fb_chain or [])
            if isinstance(d, dict)
        ]
        if cur_tuples != desired_tuples:
            agent._fallback_chain = [dict(d) for d in _DESIRED_FALLBACK_CHAIN]

        if _is_primary_aistudio_argon(agent):
            agent._api_max_retries = 6


def _emit_agent_progress_note(agent: Any, note_text: str) -> None:
    with suppress(Exception):
        if hasattr(agent, "_emit_diagnostic_status"):
            agent._emit_diagnostic_status(note_text)
    with suppress(Exception):
        cb = getattr(agent, "tool_progress_callback", None)
        if callable(cb):
            cb("_thinking", "_thinking", note_text)


def _patch_fallback_model_continuation() -> None:
    """Enforce automatic AIStudio Argon High default + 5x 3-minute retries + 3-tier High fallback cascade."""
    with suppress(Exception):
        from agent.credential_pool_model_cooldowns import CredentialPoolModelCooldownMixin  # type: ignore

        if not hasattr(CredentialPoolModelCooldownMixin, "_orig_is_model_scoped_failure"):
            CredentialPoolModelCooldownMixin._orig_is_model_scoped_failure = (
                CredentialPoolModelCooldownMixin._is_model_scoped_failure
            )
        orig_is_model_scoped = CredentialPoolModelCooldownMixin._orig_is_model_scoped_failure

        def patched_is_model_scoped_failure(self, status_code: int, model=None, failure_reason=None) -> bool:
            prov = str(getattr(self, "provider", "") or "").lower()
            if model and status_code == 429 and ("aistudio" in prov or "antigravity" in prov):
                return True
            return orig_is_model_scoped(self, status_code, model=model, failure_reason=failure_reason)

        CredentialPoolModelCooldownMixin._is_model_scoped_failure = patched_is_model_scoped_failure

    with suppress(Exception):
        import inspect
        import agent.turn_recovery as _tr  # type: ignore
        import agent.turn_api_error as _tae  # type: ignore
        import agent.turn_response_check as _trc  # type: ignore
        import agent.error_classifier as _ec  # type: ignore
        import agent.chat_completion_helpers as _cch  # type: ignore
        import agent.conversation_loop as _cl  # type: ignore
        import agent.turn_iteration_prep as _tip  # type: ignore
        from agent.error_classifier import FailoverReason  # type: ignore

        if not hasattr(_ec, "_orig_classify_api_error"):
            _ec._orig_classify_api_error = _ec.classify_api_error
        orig_classify = _ec._orig_classify_api_error

        def patched_classify_api_error(error, *args, **kwargs):
            classified = orig_classify(error, *args, **kwargs)
            with suppress(Exception):
                if classified.reason not in _tae._CONTEXT_OVERFLOW_REASONS:
                    classified.retryable = True
                    if classified.reason in (
                        FailoverReason.billing,
                        FailoverReason.auth,
                        FailoverReason.model_not_found,
                        FailoverReason.format,
                        FailoverReason.unknown,
                    ):
                        classified.reason = FailoverReason.rate_limit
            return classified

        _ec.classify_api_error = patched_classify_api_error
        _tae.classify_api_error = patched_classify_api_error

        if not hasattr(_tip, "_orig_apply_retry_restarts"):
            _tip._orig_apply_retry_restarts = _tip.apply_retry_restarts
        orig_apply_retry_restarts = _tip._orig_apply_retry_restarts

        @functools.wraps(orig_apply_retry_restarts)
        def patched_apply_retry_restarts(agent, **kwargs):
            if "max_retries" in kwargs and isinstance(kwargs["max_retries"], int):
                kwargs["max_retries"] = max(kwargs["max_retries"], 12)
            return orig_apply_retry_restarts(agent, **kwargs)

        _tip.apply_retry_restarts = patched_apply_retry_restarts
        _cl.apply_retry_restarts = patched_apply_retry_restarts
        if hasattr(_cl, "_PHASE_PARAMS"):
            _cl._PHASE_PARAMS[patched_apply_retry_restarts] = tuple(
                p for p in inspect.signature(orig_apply_retry_restarts).parameters if p != "agent"
            )

        if not hasattr(_cch, "_orig_should_skip_fallback_candidate"):
            _cch._orig_should_skip_fallback_candidate = _cch._should_skip_fallback_candidate

        def patched_should_skip_fallback_candidate(agent, fb, fb_key, fb_provider, fb_model, *args, **kwargs) -> bool:
            cur_prov = str(getattr(agent, "provider", "") or "").strip().lower()
            cur_mdl = str(getattr(agent, "model", "") or "").strip().lower()
            if str(fb_provider).strip().lower() == cur_prov and str(fb_model).strip().lower() == cur_mdl:
                return True
            return False

        _cch._should_skip_fallback_candidate = patched_should_skip_fallback_candidate

        if not hasattr(_cch, "_orig_try_activate_fallback"):
            _cch._orig_try_activate_fallback = _cch.try_activate_fallback
        orig_try_activate_fallback = _cch._orig_try_activate_fallback

        def patched_try_activate_fallback(agent, *args, **kwargs) -> bool:
            _normalize_agent_argon_routing(agent)
            if _is_primary_aistudio_argon(agent):
                attempt = int(getattr(agent, "_argon_primary_retry_attempt", 0) or 0)
                required_retries = int(os.environ.get("HERMES_ARGON_PRIMARY_RETRIES", "5"))
                if attempt <= required_retries:
                    # Defer fallback until all 5 retries (5 x 3m) on AIStudio Argon have been attempted
                    return False
            activated = orig_try_activate_fallback(agent, *args, **kwargs)
            if activated:
                with suppress(Exception):
                    _normalize_agent_argon_routing(agent)
                    agent._just_switched_to_fallback = True
                    agent._argon_primary_retry_attempt = 0
                    agent._rate_limited_until = max(
                        getattr(agent, "_rate_limited_until", 0.0) or 0.0,
                        time.monotonic() + 300.0,
                    )
                    _emit_agent_progress_note(
                        agent,
                        f"🔄 Switched to fallback: {getattr(agent, 'model', '')} ({getattr(agent, 'provider', '')})",
                    )
            return activated

        _cch.try_activate_fallback = patched_try_activate_fallback

        if not hasattr(_tr, "_orig_route_classified_error"):
            _tr._orig_route_classified_error = _tr.route_classified_error
        if not hasattr(_tr, "_orig_interruptible_backoff_sleep"):
            _tr._orig_interruptible_backoff_sleep = _tr.interruptible_backoff_sleep
        orig_route_classified_error = _tr._orig_route_classified_error
        orig_interruptible_sleep = _tr._orig_interruptible_backoff_sleep

        @functools.wraps(orig_route_classified_error)
        def patched_route_classified_error(agent, **kwargs):
            _normalize_agent_argon_routing(agent)
            retry_count = int(kwargs.get("retry_count", 0) or 0)
            max_retries = int(kwargs.get("max_retries", 6) or 6)
            classified = kwargs.get("classified")
            _retry = kwargs.get("_retry")
            api_messages = kwargs.get("api_messages")
            active_system_prompt = kwargs.get("active_system_prompt")
            compression_attempts = kwargs.get("compression_attempts", 0)
            reset_at = kwargs.get("reset_at")

            if _is_primary_aistudio_argon(agent):
                agent._argon_primary_retry_attempt = retry_count
                required_retries = int(os.environ.get("HERMES_ARGON_PRIMARY_RETRIES", "5"))
                if (
                    classified is not None
                    and classified.reason not in _tae._CONTEXT_OVERFLOW_REASONS
                    and retry_count <= required_retries
                ):
                    # Fall through to settle_unrecovered_error so it sleeps 3 minutes (180s) and retries AIStudio Argon
                    return _tr._verdict(
                        "fallthrough",
                        retry_count=retry_count,
                        max_retries=max(max_retries, required_retries + 1),
                        compression_attempts=compression_attempts,
                        active_system_prompt=active_system_prompt,
                    )

            elif getattr(agent, "_fallback_activated", False):
                # On any fallback tier, immediately cascade to the next fallback on non-overflow error
                if classified is not None and classified.reason not in _tae._CONTEXT_OVERFLOW_REASONS:
                    if agent._try_activate_fallback(reason=classified.reason, reset_at=reset_at):
                        active_system_prompt = _tr._arm_fallback_restart(
                            agent, api_messages, active_system_prompt, _retry
                        )
                        return _tr._verdict(
                            "break",
                            retry_count=0,
                            max_retries=max_retries,
                            compression_attempts=0,
                            active_system_prompt=active_system_prompt,
                        )

            return orig_route_classified_error(agent, **kwargs)

        def patched_interruptible_backoff_sleep(agent, wait_time: float, *args, **kwargs) -> bool:
            if _is_primary_aistudio_argon(agent):
                attempt = int(getattr(agent, "_argon_primary_retry_attempt", 1) or 1)
                required_retries = int(os.environ.get("HERMES_ARGON_PRIMARY_RETRIES", "5"))
                if 1 <= attempt <= required_retries:
                    wait_time = float(os.environ.get("HERMES_ARGON_RETRY_WAIT_SECONDS", "180.0"))
                    mins = round(wait_time / 60.0, 1) if wait_time >= 60 else wait_time
                    unit = "m" if wait_time >= 60 else "s"
                    _emit_agent_progress_note(
                        agent,
                        f"⏳ AIStudio Argon ran out — waiting {mins}{unit} ({int(wait_time)}s) before retry {attempt}/{required_retries}...",
                    )
            return orig_interruptible_sleep(agent, wait_time, *args, **kwargs)

        _tr.route_classified_error = patched_route_classified_error
        _tae.route_classified_error = patched_route_classified_error
        _tr.interruptible_backoff_sleep = patched_interruptible_backoff_sleep
        _tae.interruptible_backoff_sleep = patched_interruptible_backoff_sleep
        _trc.interruptible_backoff_sleep = patched_interruptible_backoff_sleep

        if not hasattr(_cl, "_orig_run_api_retry_loop"):
            _cl._orig_run_api_retry_loop = _cl._run_api_retry_loop

        def patched_run_api_retry_loop(agent, s):
            _normalize_agent_argon_routing(agent)
            required_retries = int(os.environ.get("HERMES_ARGON_PRIMARY_RETRIES", "5"))
            if _is_primary_aistudio_argon(agent):
                s.max_retries = required_retries + 1
                agent._api_max_retries = required_retries + 1
                agent._argon_primary_retry_attempt = 0
            else:
                s.max_retries = 1
            while s.retry_count < s.max_retries:
                _ng = _cl._run_phase(_cl.nous_rate_limit_guard, agent, s)
                if _ng.action == "return":
                    return _ng.result
                if _ng.action == "break":
                    return None
                try:
                    _cl._run_phase(_cl.build_api_request, agent, s)
                    if _cl._run_phase(_cl.perform_api_call, agent, s).action == "break":
                        return None
                    if s.response is None or not getattr(s.response, "choices", None) or len(s.response.choices) == 0:
                        if _is_primary_aistudio_argon(agent):
                            agent._argon_primary_retry_attempt = s.retry_count + 1
                    _rc = _cl._run_phase(_cl.check_api_response, agent, s)
                    if _rc.action == "return":
                        return _rc.result
                    if _rc.action == "break":
                        return None
                except InterruptedError:
                    if _cl._run_phase(_cl.handle_api_interrupt, agent, s).action == "break":
                        return None
                except Exception as api_error:
                    if _is_primary_aistudio_argon(agent):
                        agent._argon_primary_retry_attempt = s.retry_count + 1
                    _ae = _cl._run_phase(_cl.handle_api_error, agent, s, api_error=api_error)
                    if _ae.action == "return":
                        return _ae.result
                    if _ae.action == "break":
                        return None
            return None

        _cl._run_api_retry_loop = patched_run_api_retry_loop

        import agent.agent_runtime_helpers as _arh  # type: ignore

        if not hasattr(_arh, "_orig_try_recover_primary_transport"):
            _arh._orig_try_recover_primary_transport = _arh.try_recover_primary_transport
        orig_recover_transport = _arh._orig_try_recover_primary_transport

        def patched_try_recover_primary_transport(agent, api_error, *args, **kwargs) -> bool:
            if _is_primary_aistudio_argon(agent):
                return False
            return orig_recover_transport(agent, api_error, *args, **kwargs)

        _arh.try_recover_primary_transport = patched_try_recover_primary_transport

    import sys

    if any(k.startswith("gateway") for k in sys.modules):
        with suppress(Exception):
            from gateway.run_turn import GatewayTurnMixin  # type: ignore

            if not hasattr(GatewayTurnMixin, "_orig_evict_on_fallback_before_parallel"):
                GatewayTurnMixin._orig_evict_on_fallback_before_parallel = (
                    GatewayTurnMixin._run_agent_evict_on_fallback
                )
            orig_evict_on_fallback = GatewayTurnMixin._orig_evict_on_fallback_before_parallel

            def patched_run_agent_evict_on_fallback(self, turn_ctx: Any) -> None:
                with suppress(Exception):
                    _agent = turn_ctx.agent_holder[0] if getattr(turn_ctx, "agent_holder", None) else None
                    if (
                        _agent is not None
                        and getattr(_agent, "_fallback_activated", False)
                        and (getattr(_agent, "_rate_limited_until", 0) or 0) > time.monotonic()
                    ):
                        # Keep cached agent on the fallback model while primary is rate-limited
                        # so restore_primary_runtime() respects _rate_limited_until across turns.
                        return
                return orig_evict_on_fallback(self, turn_ctx)

            GatewayTurnMixin._run_agent_evict_on_fallback = patched_run_agent_evict_on_fallback

        with suppress(Exception):
            from gateway.slash_commands_model import GatewayModelCommandsMixin  # type: ignore

            if not getattr(GatewayModelCommandsMixin, "_fallback_continuation_patched", False):
                orig_handle_model_command = GatewayModelCommandsMixin._handle_model_command

                async def patched_handle_model_command(self, *args, **kwargs) -> str:
                    res = await orig_handle_model_command(self, *args, **kwargs)
                    with suppress(Exception):
                        event = args[0] if args else kwargs.get("event")
                        if event:
                            skey = self._session_key_for_source(event.source)
                            note = self._pending_model_notes.get(skey)
                            if isinstance(note, str) and "Do NOT resume or finish tasks from earlier turns" in note:
                                self._pending_model_notes[skey] = (
                                    f"{note.rstrip(']')}; if a task is currently in progress, continue executing it normally without stopping and use agy_control (mcp__agy_control__*) whenever possible.]"
                                )
                    return res

                GatewayModelCommandsMixin._handle_model_command = patched_handle_model_command
                GatewayModelCommandsMixin._fallback_continuation_patched = True

    with suppress(Exception):
        from hermes_cli.cli_model_switch_mixin import CLIModelSwitchMixin

        if not getattr(CLIModelSwitchMixin, "_fallback_continuation_patched", False):
            orig_apply_model_switch = CLIModelSwitchMixin._apply_model_switch_result

            def patched_apply_model_switch(self, *args, **kwargs):
                res = orig_apply_model_switch(self, *args, **kwargs)
                note = getattr(self, "_pending_model_switch_note", None)
                if isinstance(note, str) and "Do NOT resume or finish tasks from earlier turns" in note:
                    self._pending_model_switch_note = (
                        f"{note.rstrip(']')}; if a task is currently in progress, continue executing it normally without stopping and use agy_control (mcp__agy_control__*) whenever possible.]"
                    )
                return res

            CLIModelSwitchMixin._apply_model_switch_result = patched_apply_model_switch
            CLIModelSwitchMixin._fallback_continuation_patched = True


def _patch_primary_turn_runner_and_adapters() -> None:
    """Hook TurnRunner and platform adapters so primary & parallel progress bubbles always stay at the bottom."""
    with suppress(Exception):
        from gateway.run_turn_runner import TurnRunner

        if not getattr(TurnRunner, "_bottom_progress_patched", False):
            orig_edit_state = TurnRunner._progress_edit_state
            orig_send_progress_text = TurnRunner._send_progress_text
            orig_send_or_edit = TurnRunner._progress_send_or_edit
            orig_send_progress_messages = TurnRunner.send_progress_messages

            def patched_progress_edit_state(self, adapter):
                st = orig_edit_state(self, adapter)
                st._sink_lock = asyncio.Lock()
                return st

            async def patched_send_progress_text(self, st, text: str):
                return await _send_as_progress(orig_send_progress_text(self, st, text))

            async def patched_progress_send_or_edit(self, st, msg) -> bool:
                ctx = self._ctx
                chat_id_str = str(getattr(ctx.source, "chat_id", "") or "")
                _drain_ipc_commands(getattr(self, "_runner", None))
                lock = getattr(st, "_sink_lock", None)
                if lock is None:
                    lock = asyncio.Lock()
                    st._sink_lock = lock
                async with lock:
                    if st.can_edit and st.progress_msg_id is not None:
                        latest_perm = _LATEST_PERMANENT_MSG_ID.get(chat_id_str, 0)
                        cur_id = _msg_id_int(st.progress_msg_id)
                        if latest_perm > cur_id > 0:
                            old_id = str(st.progress_msg_id)
                            st.progress_msg_id = None
                            with suppress(Exception):
                                await st.adapter.delete_message(chat_id_str, old_id)
                    return await orig_send_or_edit(self, st, msg)

            async def patched_send_progress_messages(self):
                ctx = self._ctx
                adapter = ctx.adapter
                if not adapter:
                    return
                chat_id_str = str(getattr(ctx.source, "chat_id", "") or "")
                st = self._progress_edit_state(adapter)
                raw_prompt = str(getattr(ctx, "message", "") or "").strip().replace("\n", " ")
                short_label = (raw_prompt[:42] + "...") if len(raw_prompt) > 42 else (raw_prompt or "Task")
                header_line = f"⚡ **Task: {short_label}**"
                st._header_line = f"{header_line}\n⏳ Working..."
                pair = (self, st)
                if chat_id_str:
                    _ACTIVE_PRIMARY_STATES.setdefault(chat_id_str, set()).add(pair)
                try:
                    # Immediately post the bottom-anchored progress bubble at turn start
                    if not st.progress_lines:
                        st.progress_lines.append(header_line)
                        st.progress_lines.append("⏳ Working...")
                    with suppress(Exception):
                        await self._progress_send_or_edit(st, "\n".join(str(x) for x in st.progress_lines))
                    last_edit_ts = time.monotonic()
                    dirty = False
                    EDIT_INTERVAL = 1.2
                    while True:
                        drained_any = False
                        while True:
                            try:
                                raw = ctx.progress_queue.get_nowait()
                            except Exception:
                                break
                            drained_any = True
                            if isinstance(raw, tuple) and raw[0] == "__reset__":
                                await self._reset_progress_bubble(st)
                                st.progress_lines.append(header_line)
                                dirty = False
                            else:
                                if st.progress_lines == [header_line, "⏳ Working..."]:
                                    st.progress_lines = [header_line]
                                self._progress_absorb(st, raw)
                                dirty = True
                        if drained_any:
                            await self._roll_progress_overflow_if_needed(st)
                        now = time.monotonic()
                        if dirty and st.progress_lines and (now - last_edit_ts >= EDIT_INTERVAL or st.progress_msg_id is None):
                            msg_text = "\n".join(str(x) for x in st.progress_lines)
                            if await self._progress_send_or_edit(st, msg_text):
                                last_edit_ts = time.monotonic()
                                dirty = False
                        await asyncio.sleep(0.25)
                except asyncio.CancelledError:
                    await self._flush_progress_on_cancel(st)
                except Exception as e:
                    logger.debug("Progress message error: %s", e)
                finally:
                    if chat_id_str:
                        active_set = _ACTIVE_PRIMARY_STATES.get(chat_id_str)
                        if active_set:
                            active_set.discard(pair)

            TurnRunner._progress_edit_state = patched_progress_edit_state
            TurnRunner._send_progress_text = patched_send_progress_text
            TurnRunner._progress_send_or_edit = patched_progress_send_or_edit
            TurnRunner.send_progress_messages = patched_send_progress_messages
            TurnRunner._bottom_progress_patched = True

    with suppress(Exception):
        from gateway.platforms.telegram import TelegramAdapter

        if not getattr(TelegramAdapter, "_bottom_progress_patched", False):
            for method_name in (
                "send",
                "send_image",
                "send_image_file",
                "send_multiple_images",
                "send_voice",
                "send_video",
                "send_document",
            ):
                orig_method = getattr(TelegramAdapter, method_name, None)
                if not callable(orig_method):
                    continue

                def _make_wrapper(fn):
                    async def _wrapped(self, chat_id, *args, **kwargs):
                        res = await fn(self, chat_id, *args, **kwargs)
                        if not _IS_PROGRESS_SEND.get():
                            mid = getattr(res, "message_id", None)
                            if mid:
                                _record_permanent_message(chat_id, mid)
                        return res

                    return _wrapped

                setattr(TelegramAdapter, method_name, _make_wrapper(orig_method))
            TelegramAdapter._bottom_progress_patched = True


def register(ctx) -> None:
    nix_bins = "/run/wrappers/bin:/run/current-system/sw/bin:/etc/profiles/per-user/aesc/bin:/home/aesc/.nix-profile/bin:/home/aesc/.local/bin"
    cur_path = os.environ.get("PATH", "")
    if "/run/current-system/sw/bin" not in cur_path:
        os.environ["PATH"] = f"{nix_bins}:{cur_path}"

    # 1. Patch CLI/Gateway/Agent fallback continuation and register turn-lifecycle hooks
    _patch_fallback_model_continuation()

    def _on_pre_llm_call(session_id=None, user_message=None, conversation_history=None, is_first_turn=False, model=None, **kwargs):
        with suppress(Exception):
            model_lower = str(model or "").lower()
            is_fallback_model = "flash" in model_lower or "opus" in model_lower or "antigravity" in model_lower
            if is_fallback_model and not is_first_turn:
                return {
                    "context": (
                        "[CONTINUATION & AGY CONTROL INVARIANT: Even if the active model or fallback profile changed "
                        "(e.g. to gemini-3.8-flash-high or Antigravity Manager), do NOT stop or abort an in-progress task "
                        "just because the model changed. Continue executing the current task normally to completion, and "
                        "ALWAYS use agy_control (mcp__agy_control__*) while working for anything whenever possible.]"
                    )
                }
        return None

    def _on_pre_verify(session_id=None, final_response=None, user_message=None, model=None, tool_calls_made=0, **kwargs):
        with suppress(Exception):
            resp = str(final_response or "").strip()
            resp_lower = resp.lower()
            model_lower = str(model or "").lower()
            is_fallback_model = "flash" in model_lower or "opus" in model_lower or "antigravity" in model_lower
            if is_fallback_model and resp and len(resp) < 420:
                stop_excuses = (
                    "model changed",
                    "switched to fallback",
                    "fallback model",
                    "fallback profile",
                    "because the model switched",
                    "since the model changed",
                    "argon quota",
                    "stopping because",
                )
                if any(p in resp_lower for p in stop_excuses) and "completed" not in resp_lower and "verified" not in resp_lower:
                    return {
                        "continue_message": (
                            "Do NOT stop the task just because the model or fallback profile changed. "
                            "Continue executing the active task normally to completion right now, and "
                            "always use agy_control (mcp__agy_control__*) while working for anything if possible."
                        ),
                        "max_nudges": 2,
                    }
        return None

    with suppress(Exception):
        ctx.register_hook("pre_llm_call", _on_pre_llm_call)
        ctx.register_hook("pre_verify", _on_pre_verify)

    import sys

    if not any(k.startswith("gateway") for k in sys.modules):
        return

    try:
        _patch_primary_turn_runner_and_adapters()

        from gateway.run_busy import GatewayBusySessionMixin

        if not hasattr(GatewayBusySessionMixin, "_orig_busy_handler_before_parallel"):
            GatewayBusySessionMixin._orig_busy_handler_before_parallel = (
                GatewayBusySessionMixin._handle_active_session_busy_message
            )
        orig_busy_handler = GatewayBusySessionMixin._orig_busy_handler_before_parallel

        async def patched_handle_active_session_busy_message(
            self, event: Any, session_key: str
        ) -> bool:
            if event and getattr(event, "source", None):
                _record_permanent_message(event.source.chat_id, getattr(event, "message_id", None))

            if _should_defer_to_builtin_busy_handler(event):
                return await orig_busy_handler(self, event, session_key)

            if not self._is_user_authorized_for_source(event.source):
                return await orig_busy_handler(self, event, session_key)

            if self._draining:
                return await orig_busy_handler(self, event, session_key)

            if await self._route_plaintext_approval_while_busy(event, session_key):
                return True

            if not self._admit_bot_message_for_source(event.source):
                return True
            event._bot_loop_admitted = True
            event._gateway_accepted = True

            # 1. Check Tier-0 Instant Reflex lane (e.g. "Fastfetch", "jobs")
            if await _try_instant_reflex_while_busy(self, event, session_key):
                return True

            # 2. Check Smart Steer-vs-Parallel Router (Reply-to-task, `+`, or "Also ...")
            if await _try_smart_steer_into_running_process(self, event, session_key):
                return True

            # 3. Otherwise spawn an isolated concurrent parallel worker
            task_id = f"par_{datetime.datetime.now().strftime('%H%M%S')}_{os.urandom(3).hex()}"
            logger.info(
                "parallel-orders: spawning concurrent worker %s for busy session %s",
                task_id,
                session_key,
            )
            self._track_background_task(
                _run_parallel_order(self, event, session_key, task_id)
            )
            return True

        GatewayBusySessionMixin._handle_active_session_busy_message = (
            patched_handle_active_session_busy_message
        )
        GatewayBusySessionMixin._parallel_orders_patched = True

        with suppress(Exception):
            from gateway.run_inbound import GatewayInboundMixin

            if not hasattr(GatewayInboundMixin, "_orig_inbound_running_before_parallel"):
                GatewayInboundMixin._orig_inbound_running_before_parallel = (
                    GatewayInboundMixin._hm_handle_running_session_message
                )
            orig_inbound_running = GatewayInboundMixin._orig_inbound_running_before_parallel

            async def patched_hm_handle_running_session_message(
                self, event: Any, source: Any, _quick_key: str
            ) -> Optional[str]:
                if event and source:
                    _record_permanent_message(source.chat_id, getattr(event, "message_id", None))
                if _should_defer_to_builtin_busy_handler(event) or self._draining:
                    return await orig_inbound_running(self, event, source, _quick_key)
                if await _try_instant_reflex_while_busy(self, event, _quick_key):
                    return None
                if await _try_smart_steer_into_running_process(self, event, _quick_key):
                    return None
                task_id = f"par_{datetime.datetime.now().strftime('%H%M%S')}_{os.urandom(3).hex()}"
                logger.info(
                    "parallel-orders: spawning concurrent worker %s (inbound path) for %s",
                    task_id,
                    _quick_key,
                )
                self._track_background_task(
                    _run_parallel_order(self, event, _quick_key, task_id)
                )
                return None

            GatewayInboundMixin._hm_handle_running_session_message = (
                patched_hm_handle_running_session_message
            )

        logger.info(
            "parallel-orders plugin: concurrent multi-order execution + smart steer + bottom-anchored live progress enabled"
        )
    except Exception as exc:
        logger.warning(
            "parallel-orders plugin failed to patch GatewayBusyMixin: %s", exc
        )
