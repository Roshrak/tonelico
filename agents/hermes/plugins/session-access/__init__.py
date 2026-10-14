"""Session access plugin for Hermes Gateway.

Enables seamless cross-origin session access for authorized gateway admins:
1. /sessions displays all sessions across platforms (Web, CLI, Telegram) without requiring 'all'.
2. /resume allows switching to any session without requiring '--all'.
3. /resume without arguments lists all sessions across all platforms.
"""

from __future__ import annotations

import dataclasses
import logging

logger = logging.getLogger("session-access")


def register(ctx) -> None:
    try:
        from gateway.slash_commands import GatewaySlashCommandsMixin

        orig_handle_sessions = GatewaySlashCommandsMixin._handle_sessions_command
        orig_handle_resume = GatewaySlashCommandsMixin._handle_resume_command
        orig_resume_target_allowed = GatewaySlashCommandsMixin._resume_target_allowed

        async def patched_handle_sessions(self, event):
            try:
                norm_fn = getattr(self, "_normalize_source_for_session_key", None)
                source = await norm_fn(event.source) if callable(norm_fn) else event.source
                is_admin = self._resume_caller_is_admin(source)
            except Exception:
                is_admin = False

            if is_admin:
                raw = event.get_command_args().strip()
                if not raw or raw in ("ls", "list", "browse"):
                    event = dataclasses.replace(event, text="/sessions all")

            return await orig_handle_sessions(self, event)

        async def patched_handle_resume(self, event):
            try:
                norm_fn = getattr(self, "_normalize_source_for_session_key", None)
                source = await norm_fn(event.source) if callable(norm_fn) else event.source
                is_admin = self._resume_caller_is_admin(source)
            except Exception:
                is_admin = False

            if is_admin:
                raw = event.get_command_args().strip()
                parts = raw.split()
                if "--all" not in parts:
                    new_text = f"/resume --all {raw}".strip()
                    event = dataclasses.replace(event, text=new_text)

            return await orig_handle_resume(self, event)

        async def patched_resume_target_allowed(self, source, target_id, allow_override=False):
            try:
                if self._resume_caller_is_admin(source):
                    return True
            except Exception:
                pass
            return await orig_resume_target_allowed(self, source, target_id, allow_override)

        GatewaySlashCommandsMixin._handle_sessions_command = patched_handle_sessions
        GatewaySlashCommandsMixin._handle_resume_command = patched_handle_resume
        GatewaySlashCommandsMixin._resume_target_allowed = patched_resume_target_allowed
        logger.info("session-access plugin: cross-origin session management enabled for admin")
    except Exception as exc:
        logger.warning("session-access plugin failed to patch GatewaySlashCommandsMixin: %s", exc)
