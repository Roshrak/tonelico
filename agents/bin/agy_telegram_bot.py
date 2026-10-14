#!/usr/bin/env python3
"""
Direct Antigravity Telegram Gateway
Connects Telegram (@aescauto_bot) directly to Google Antigravity (agy)
running Gemini 3.8 Flash High under official Google AI Pro subscription quota.
Zero middlemen, full direct laptop execution with auto-approved tools.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import shutil
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("AgyTelegramBot")

def _load_secret(name: str, default: str = "") -> str:
    """Read a secret from the environment, then from ~/.hermes/.env."""
    value = os.environ.get(name)
    if value:
        return value
    env_file = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / ".env"
    try:
        for line in env_file.read_text().splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() == name:
                return val.strip().strip('"').strip("'")
    except OSError:
        pass
    return default


BOT_TOKEN = _load_secret("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN is not set (environment or ~/.hermes/.env)")
ALLOWED_USER_ID = int(_load_secret("TELEGRAM_ALLOWED_USERS").split(",")[0] or 0)

def resolve_agy_bin() -> str:
    candidate_env = os.environ.get("AGY_BIN")
    if candidate_env and Path(candidate_env).is_file() and os.access(candidate_env, os.X_OK):
        return candidate_env
    which_bin = shutil.which("agy")
    if which_bin and Path(which_bin).is_file() and os.access(which_bin, os.X_OK):
        return which_bin
    for candidate in ("/run/current-system/sw/bin/agy", "/home/aesc/.nix-profile/bin/agy", "/home/aesc/.local/bin/agy"):
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    for match in sorted(Path("/nix/store").glob("*-antigravity-cli-*/bin/agy"), reverse=True):
        if match.is_file() and os.access(match, os.X_OK):
            return str(match)
    return "agy"

AGY_BIN = resolve_agy_bin()

# Session state: whether to continue previous conversation
is_continued = False
conversation_lock = asyncio.Lock()

def check_auth(update: Update) -> bool:
    user = update.effective_user
    if not user or user.id != ALLOWED_USER_ID:
        logger.warning(f"Unauthorized access attempt from ID: {user.id if user else 'Unknown'}")
        return False
    return True

async def run_agy(prompt: str, continue_session: bool) -> str:
    system_directive = (
        "[MANDATORY DIRECTIVE: Follow /home/aesc/AGENTS.md strictly]\n"
        "1. For shopping, hardware, or price queries: NEVER output generic shopping guides, buying tips, or price ranges. ALWAYS output concrete individual listings (Seller/Shop, Exact Model/Variant & Condition, Exact Asking Price in VNĐ, Location in HCM/Đồng Nai, Source/Link) and a visual ASCII/Markdown Price Comparison Graph ranking them from lowest to highest.\n"
        "2. For desktop control: Verify with swaymsg/ps aux before confirming success. Never claim an action succeeded unless verified.\n"
        "---\n"
    )
    full_prompt = f"{system_directive}User Request: {prompt}"
    cmd = [
        AGY_BIN,
        "-p", full_prompt,
        "--model", "gemini-3.8-flash-high",
        "--effort", "high",
        "--dangerously-skip-permissions",
        "--output-format", "json",
    ]
    if continue_session:
        cmd.insert(1, "-c")

    logger.info(f"Running agy (continue={continue_session}): {prompt[:80]}...")
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy()
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180.0)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        logger.warning(f"agy process timed out on prompt: {prompt[:60]}")
        return "⚠️ Task timed out after 3 minutes. You can continue chatting."

    out_text = stdout.decode("utf-8", errors="replace")
    
    try:
        data = json.loads(out_text)
        resp = data.get("response", "").strip()
        if not resp:
            err = data.get("error", "").strip()
            if err:
                return f"⚠️ Antigravity Error: {err}"
            return "✅ Action executed successfully."
        return resp
    except Exception as e:
        logger.error(f"Failed to parse agy JSON: {e}\nRaw output: {out_text[:300]}")
        if out_text.strip():
            return out_text.strip()
        return f"⚠️ Execution error (exit code {proc.returncode}): {stderr.decode()[:200]}"

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    await update.message.reply_text(
        "👋 **Antigravity (Google AI Pro) Direct Gateway**\n\n"
        "• Model: **Gemini 3.8 Flash High**\n"
        "• Quota: **Google AI Pro Subscription**\n"
        "• Direct execution on your NixOS laptop is **ENABLED**.\n\n"
        "Commands:\n"
        "/new - Start a fresh conversation session\n"
        "/usage - Check your Google AI Pro subscription quota\n"
        "/help - Show help",
        parse_mode="Markdown"
    )

async def new_session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_continued
    if not check_auth(update):
        return
    async with conversation_lock:
        is_continued = False
    await update.message.reply_text("🔄 **New conversation started.** Context has been reset.")

async def usage_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    await update.message.reply_chat_action(ChatAction.TYPING)
    try:
        p = await asyncio.create_subprocess_exec(
            AGY_BIN, "-p", "/usage", "--output-format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await p.communicate()
        data = json.loads(stdout.decode())
        resp = data.get("response", "").strip()
        await update.message.reply_text(f"📊 **Google AI Pro Quota Status:**\n\n```\n{resp}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Could not check usage: {e}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_continued
    if not check_auth(update):
        return

    text = update.message.text
    if not text:
        return

    # Keep typing status while processing
    async def keep_typing():
        while True:
            try:
                await update.message.reply_chat_action(ChatAction.TYPING)
                await asyncio.sleep(4)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    typing_task = asyncio.create_task(keep_typing())

    try:
        async with conversation_lock:
            reply = await run_agy(text, continue_session=is_continued)
            is_continued = True

        # Telegram message length limit is 4096 characters
        if len(reply) > 4000:
            for i in range(0, len(reply), 4000):
                await update.message.reply_text(reply[i:i+4000])
        else:
            await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text(f"⚠️ Error: {e}")
    finally:
        typing_task.cancel()

def main():
    logger.info("Starting Direct Antigravity Telegram Bot...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", start_handler))
    app.add_handler(CommandHandler("new", new_session_handler))
    app.add_handler(CommandHandler("reset", new_session_handler))
    app.add_handler(CommandHandler("usage", usage_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
