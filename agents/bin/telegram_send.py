#!/usr/bin/env python3
"""
Telegram Direct Delivery Helper for Hermes Agent (CLI, Scripts, & Cron)
Sends text, photos, documents, audio/voice notes, or inline-button messages
directly to the user's configured Telegram chat using ~/.hermes/.env credentials.

Usage:
  telegram_send.py --text "Hello from Hermes!"
  telegram_send.py --photo /path/to/image.png --caption "Desktop screenshot"
  telegram_send.py --document /path/to/report.pdf --caption "Generated PDF"
  telegram_send.py --voice /path/to/audio.ogg --caption "Voice summary"
"""

import argparse
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request
import uuid


def load_secret(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    if val:
        return val
    env_file = os.path.join(
        os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), ".env"
    )
    try:
        with open(env_file, "r", encoding="utf-8") as fh:
            for line in fh:
                key, sep, raw = line.strip().partition("=")
                if sep and key.strip() == name:
                    return raw.strip().strip('"').strip("'")
    except OSError:
        pass
    return default


def get_credentials():
    token = load_secret("TELEGRAM_BOT_TOKEN")
    chat_id = (
        load_secret("TELEGRAM_CHAT_ID")
        or load_secret("TELEGRAM_ALLOWED_USERS").split(",")[0].strip()
    )
    if not token or not chat_id:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID/TELEGRAM_ALLOWED_USERS in ~/.hermes/.env"
        )
    return token, chat_id


def api_post_json(token: str, method: str, payload: dict) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post_multipart(
    token: str, method: str, fields: dict, file_field: str, file_path: str
) -> dict:
    boundary = f"----HermesBoundary{uuid.uuid4().hex}"
    body = bytearray()
    for k, v in fields.items():
        if v is None:
            continue
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8")
        )
    filename = os.path.basename(file_path)
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(file_path, "rb") as fh:
        file_bytes = fh.read()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode(
            "utf-8"
        )
    )
    body.extend(f"Content-Type: {ctype}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = f"https://api.telegram.org/bot{token}/{method}"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Send rich content to Telegram")
    parser.add_argument("--text", help="Text message to send")
    parser.add_argument("--photo", help="Path to photo/image file to send")
    parser.add_argument("--document", help="Path to document/file to send")
    parser.add_argument("--voice", help="Path to voice/audio file to send")
    parser.add_argument("--caption", default="", help="Caption for photo/document/voice")
    parser.add_argument(
        "--parse-mode", default="", choices=["", "HTML", "Markdown", "MarkdownV2"]
    )
    parser.add_argument(
        "--buttons",
        default="",
        help='Optional JSON array of inline buttons, e.g. \'[[{"text":"Open","url":"https://example.com"}]]\'',
    )
    args = parser.parse_args()

    token, chat_id = get_credentials()
    reply_markup = json.loads(args.buttons) if args.buttons else None

    if args.photo:
        fields = {"chat_id": chat_id, "caption": args.caption or args.text or ""}
        if args.parse_mode:
            fields["parse_mode"] = args.parse_mode
        if reply_markup:
            fields["reply_markup"] = json.dumps({"inline_keyboard": reply_markup})
        res = api_post_multipart(token, "sendPhoto", fields, "photo", args.photo)
    elif args.document:
        fields = {"chat_id": chat_id, "caption": args.caption or args.text or ""}
        if args.parse_mode:
            fields["parse_mode"] = args.parse_mode
        if reply_markup:
            fields["reply_markup"] = json.dumps({"inline_keyboard": reply_markup})
        res = api_post_multipart(token, "sendDocument", fields, "document", args.document)
    elif args.voice:
        fields = {"chat_id": chat_id, "caption": args.caption or args.text or ""}
        res = api_post_multipart(token, "sendVoice", fields, "voice", args.voice)
    elif args.text:
        payload = {"chat_id": chat_id, "text": args.text}
        if args.parse_mode:
            payload["parse_mode"] = args.parse_mode
        if reply_markup:
            payload["reply_markup"] = {"inline_keyboard": reply_markup}
        res = api_post_json(token, "sendMessage", payload)
    else:
        parser.error("Provide at least one of --text, --photo, --document, or --voice")
        return

    print(json.dumps({"ok": res.get("ok"), "message_id": res.get("result", {}).get("message_id")}))


if __name__ == "__main__":
    main()
