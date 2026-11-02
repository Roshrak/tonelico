"""Parallel Orders plugin for Hermes Gateway.

When a user sends a new message/order while an existing turn is already running on the same
session:
1. The active turn is NEVER interrupted or cut mid-way.
2. The new message immediately launches in a concurrent background AIAgent worker thread
   sharing a clean snapshot of the current session's conversation history.
3. A live self-deleting progress bubble tracks the parallel worker's tool calls and vanishes
   automatically when the parallel worker delivers its reply + media attachments.
4. Once the primary turn finishes, the parallel worker's user/assistant exchange is appended
   to the session transcript so future turns remember all parallel orders.
"""

from __future__ import annotations

import asyncio
import copy
import datetime
import logging
import os
import threading
import time
from contextlib import suppress
from typing import Any, Dict, List, Optional

logger = logging.getLogger("parallel-orders")

_CANCEL_WORDS = frozenset({
    "stop", "cancel", "abort", "halt", "quit",
    "dừng", "dừng lại", "hủy", "huỷ", "thôi",
})

_STEER_PREFIXES = ("steer:", "sửa:", "chỉnh:")

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


def _sanitize_history_snapshot(
    raw_history: Optional[List[Dict[str, Any]]],
    max_messages: int = 10,
    max_total_chars: int = 16000,
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
        if len(text) > 2500:
            text = text[:2500] + "\n...[truncated for fast parallel context]..."
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

    reply_anchor = runner._reply_anchor_for_event(event)
    _thread_metadata = runner._thread_metadata_for_source(source, reply_anchor)
    media_urls = list(event.media_urls or [])
    media_types = list(event.media_types or [])

    # 1. Prepare user prompt (text, voice transcription, or media placeholder)
    prompt = (event.text or "").strip()
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

    # 2. Load clean snapshot of the current session's conversation history
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

    # 3. Create live ephemeral progress bubble (auto-deleted in finally)
    progress_msg_id: Optional[str] = None
    progress_lines: List[str] = []
    progress_lock = threading.Lock()
    progress_dirty = threading.Event()
    progress_stop = False

    try:
        init_send = await adapter.send(
            chat_id=source.chat_id,
            content="⚡ Running in parallel...",
            reply_to=reply_anchor,
            metadata=_thread_metadata,
        )
        progress_msg_id = getattr(init_send, "message_id", None)
    except Exception as exc:
        logger.debug("parallel-orders: initial progress bubble failed: %s", exc)

    async def _progress_updater() -> None:
        last_sent = ""
        while not progress_stop:
            await asyncio.sleep(1.2)
            if progress_stop or not progress_msg_id or not progress_dirty.is_set():
                continue
            progress_dirty.clear()
            with progress_lock:
                lines_copy = list(progress_lines[-8:])
            if not lines_copy:
                continue
            body = "⚡ **Parallel Run**\n" + "\n".join(lines_copy)
            if body == last_sent:
                continue
            last_sent = body
            with suppress(Exception):
                await adapter.edit_message(
                    chat_id=source.chat_id,
                    message_id=progress_msg_id,
                    content=body,
                    metadata=_thread_metadata,
                )

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
                with progress_lock:
                    progress_lines.append(f"💬 {short}")
                progress_dirty.set()
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
        with progress_lock:
            progress_lines.append(line)
        progress_dirty.set()

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
        max_iterations = _current_max_iterations()
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

        def run_sync():
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
                fallback_model=runner._refresh_fallback_model(),
                load_soul_identity=True,
            )
            agent.tool_progress_callback = _on_tool_progress
            agent.thinking_progress = True
            try:
                return agent.run_conversation(
                    user_message=enriched_prompt,
                    conversation_history=history_snapshot,
                    task_id=task_id,
                )
            finally:
                runner._cleanup_agent_resources(agent)

        result = await runner._run_in_executor_with_context(run_sync)
    except Exception as exc:
        logger.exception("parallel-orders: parallel task %s failed", task_id)
        with suppress(Exception):
            await adapter.send(
                chat_id=source.chat_id,
                content=f"⚠️ Parallel task error: {exc}",
                reply_to=reply_anchor,
                metadata=_thread_metadata,
            )
        return
    finally:
        progress_stop = True
        updater_task.cancel()
        with suppress(Exception):
            await updater_task
        if progress_msg_id:
            with suppress(Exception):
                await adapter.delete_message(str(source.chat_id), str(progress_msg_id))

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
        await adapter.send(
            chat_id=source.chat_id,
            content=text_content,
            reply_to=reply_anchor,
            metadata=_thread_metadata,
        )
    elif not images and not media_files:
        await adapter.send(
            chat_id=source.chat_id,
            content="(Completed)",
            reply_to=reply_anchor,
            metadata=_thread_metadata,
        )

    for image_url, alt_text in images or []:
        with suppress(Exception):
            await adapter.send_image(
                chat_id=source.chat_id,
                image_url=image_url,
                caption=alt_text,
                metadata=_thread_metadata,
            )

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
            await adapter.send_multiple_images(
                chat_id=source.chat_id,
                images=[(f"file://{p}", "") for p in image_media_paths],
                metadata=_thread_metadata,
            )
    else:
        for img_path in image_media_paths:
            with suppress(Exception):
                await adapter.send_image_file(
                    chat_id=source.chat_id,
                    image_path=img_path,
                    metadata=_thread_metadata,
                )

    for media_path, is_voice in other_media_items:
        ext = os.path.splitext(media_path)[1].lower()
        with suppress(Exception):
            if should_send_media_as_audio(source.platform, ext, is_voice):
                await adapter.send_voice(
                    chat_id=source.chat_id,
                    audio_path=media_path,
                    metadata=_thread_metadata,
                    is_voice=is_voice,
                )
            elif ext in _VIDEO_EXTS:
                await adapter.send_video(
                    chat_id=source.chat_id,
                    video_path=media_path,
                    metadata=_thread_metadata,
                )
            else:
                await adapter.send_document(
                    chat_id=source.chat_id,
                    file_path=media_path,
                    metadata=_thread_metadata,
                )

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
    """Return True for control/cancel/steer/internal events that should not spawn a parallel agent."""
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
    if any(lower.startswith(prefix) for prefix in _STEER_PREFIXES):
        return True
    return False


def register(ctx) -> None:
    nix_bins = "/run/wrappers/bin:/run/current-system/sw/bin:/etc/profiles/per-user/aesc/bin:/home/aesc/.nix-profile/bin:/home/aesc/.local/bin"
    cur_path = os.environ.get("PATH", "")
    if "/run/current-system/sw/bin" not in cur_path:
        os.environ["PATH"] = f"{nix_bins}:{cur_path}"
    try:
        from gateway.run_busy import GatewayBusySessionMixin

        if getattr(GatewayBusySessionMixin, "_parallel_orders_patched", False):
            return

        orig_busy_handler = GatewayBusySessionMixin._handle_active_session_busy_message

        async def patched_handle_active_session_busy_message(
            self, event: Any, session_key: str
        ) -> bool:
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

            orig_inbound_running = GatewayInboundMixin._hm_handle_running_session_message

            async def patched_hm_handle_running_session_message(
                self, event: Any, source: Any, _quick_key: str
            ) -> Optional[str]:
                if _should_defer_to_builtin_busy_handler(event) or self._draining:
                    return await orig_inbound_running(self, event, source, _quick_key)
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
            "parallel-orders plugin: concurrent multi-order execution enabled for busy sessions"
        )
    except Exception as exc:
        logger.warning(
            "parallel-orders plugin failed to patch GatewayBusyMixin: %s", exc
        )
