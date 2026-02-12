#!/usr/bin/env python3
"""Standalone Telegram update handler for TaskBot.

Polls Telegram directly and routes updates:
  - callback_query  → menu.py route (instant, no LLM)
  - /start /menu    → menu.py main  (instant, no LLM)
  - text messages   → openclaw agent (LLM processing)
  - voice messages  → transcribe → openclaw agent

This replaces OpenClaw's own Telegram polling. OpenClaw is set to webhook
mode (stopped) so it doesn't poll, but can still SEND via Telegram.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

# ── Configuration ────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
POLL_TIMEOUT = 30  # Telegram long-polling timeout (seconds)
MAX_WORKERS = 4  # Max concurrent message handlers

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
MENU_SCRIPT = os.path.join(SCRIPTS_DIR, "menu.py")

# Users allowed to interact with the bot (usernames, lowercase)
ALLOWED_USERS = {"sadindeed", "eshanchik", "segovchik"}

# Commands that show the main menu (handled without LLM)
MENU_TRIGGERS = {"/start", "/menu", "меню", "menu"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("tg_handler")

# Semaphore to limit concurrent openclaw agent calls
_agent_sem = threading.Semaphore(MAX_WORKERS)


# ── Telegram Bot API helpers ─────────────────────────────────────────


def tg_api(method, data=None, files=None, timeout=None):
    """Call Telegram Bot API. Returns parsed JSON or None on error."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    if timeout is None:
        timeout = POLL_TIMEOUT + 15

    if files:
        # multipart/form-data for file uploads (not used currently)
        import io
        boundary = "----TgHandlerBoundary"
        body = io.BytesIO()
        for key, val in (data or {}).items():
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n".encode())
        for key, (fname, fdata, ctype) in files.items():
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
            body.write(fdata)
            body.write(b"\r\n")
        body.write(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(url, data=body.getvalue(), headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        })
    elif data:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
        )
    else:
        req = urllib.request.Request(url)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        log.error("Telegram API %s HTTP %d: %s", method, e.code, body)
    except Exception as e:
        log.error("Telegram API %s error: %s", method, e)
    return None


def answer_callback(callback_query_id, text=None):
    """Answer a callback query (removes loading spinner in Telegram)."""
    data = {"callback_query_id": callback_query_id}
    if text:
        data["text"] = text
    tg_api("answerCallbackQuery", data, timeout=10)


# ── Access control ───────────────────────────────────────────────────


def is_allowed(user):
    """Check if a Telegram user is in the allowlist."""
    if not user:
        return False
    username = (user.get("username") or "").lower()
    return username in ALLOWED_USERS


# ── Voice transcription ─────────────────────────────────────────────


def transcribe_voice(file_id, message_id):
    """Download a Telegram voice/audio file and transcribe via OpenAI Whisper."""
    if not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY not set, cannot transcribe voice")
        return None

    # 1. Get file path from Telegram
    info = tg_api("getFile", {"file_id": file_id}, timeout=10)
    if not info or not info.get("ok"):
        return None
    file_path = info["result"]["file_path"]

    # 2. Download the file
    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    ext = os.path.splitext(file_path)[1] or ".ogg"
    local_path = os.path.join(tempfile.gettempdir(), f"voice_{message_id}{ext}")

    try:
        urllib.request.urlretrieve(download_url, local_path)
    except Exception as e:
        log.error("Voice download failed: %s", e)
        return None

    # 3. Transcribe via OpenAI Whisper API
    try:
        import io
        boundary = "----WhisperBoundary"
        body = io.BytesIO()

        # model field
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nwhisper-1\r\n".encode())
        # response_format field
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson\r\n".encode())

        # file field
        with open(local_path, "rb") as f:
            file_data = f.read()
        fname = os.path.basename(local_path)
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fname}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode())
        body.write(file_data)
        body.write(b"\r\n")
        body.write(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/transcriptions",
            data=body.getvalue(),
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("text", "").strip()
    except Exception as e:
        log.error("Transcription failed: %s", e)
        return None
    finally:
        try:
            os.remove(local_path)
        except OSError:
            pass


# ── Update handlers ──────────────────────────────────────────────────


def handle_callback_query(update):
    """Handle button press — run menu.py route directly (no LLM)."""
    cq = update["callback_query"]
    callback_data = cq.get("data", "")
    user = cq.get("from", {})
    user_id = user.get("id")
    username = user.get("username", "")

    # Chat ID comes from the message the button is attached to
    message = cq.get("message", {})
    chat_id = message.get("chat", {}).get("id", user_id)

    log.info("Callback %s from @%s (%s) in %s", callback_data, username, user_id, chat_id)

    # Answer immediately (remove loading spinner)
    answer_callback(cq.get("id"))

    # Check access
    if not is_allowed(user):
        log.warning("Blocked callback from @%s (not in allowlist)", username)
        return

    # Run menu.py route
    cmd = [
        "python3", MENU_SCRIPT,
        "--target", str(chat_id),
        "route", callback_data,
        "--user-id", str(user_id),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log.error("menu.py route failed: %s", result.stderr[:300])
        else:
            log.info("menu.py route OK: %s", callback_data)
    except subprocess.TimeoutExpired:
        log.error("menu.py route timed out for %s", callback_data)
    except Exception as e:
        log.error("menu.py route error: %s", e)


def handle_message(update):
    """Handle a text or voice message."""
    msg = update["message"]
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type", "private")
    user = msg.get("from", {})
    user_id = user.get("id")
    username = user.get("username", "")
    first_name = user.get("first_name", "")
    last_name = user.get("last_name", "")

    # Check access
    if not is_allowed(user):
        log.info("Ignored message from @%s (not in allowlist)", username)
        return

    # Get message text
    text = msg.get("text", "")
    voice = msg.get("voice") or msg.get("audio")

    # In group chats, only process if bot is mentioned
    if chat_type in ("group", "supergroup"):
        bot_mentioned = False
        entities = msg.get("entities", [])
        for ent in entities:
            if ent.get("type") == "mention":
                mentioned = text[ent["offset"]:ent["offset"] + ent["length"]]
                if mentioned.lower() in ("@opentasker_bot", "@taskmanagerbot"):
                    bot_mentioned = True
                    # Remove the mention from text
                    text = (text[:ent["offset"]] + text[ent["offset"] + ent["length"]:]).strip()
                    break
        if not bot_mentioned and not voice:
            return  # Ignore non-mention messages in groups

    # Handle menu triggers directly (no LLM needed)
    if text.lower().strip() in MENU_TRIGGERS:
        cmd = ["python3", MENU_SCRIPT, "--target", str(chat_id), "main"]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            log.info("Menu shown for @%s in %s", username, chat_id)
        except Exception as e:
            log.error("Menu error: %s", e)
        return

    # Handle voice messages
    if voice:
        file_id = voice.get("file_id")
        log.info("Voice from @%s (%s), transcribing...", username, user_id)

        # Send typing indicator
        tg_api("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=5)

        text = transcribe_voice(file_id, msg.get("message_id", 0))
        if not text:
            tg_api("sendMessage", {
                "chat_id": chat_id,
                "text": "\u274c \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0440\u0430\u0441\u043f\u043e\u0437\u043d\u0430\u0442\u044c \u0433\u043e\u043b\u043e\u0441\u043e\u0432\u043e\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435.",
            }, timeout=10)
            return
        log.info("Transcribed: %s", text[:100])

    if not text:
        return

    # Build sender-annotated message for the LLM agent
    sender_tag = f"@{username}" if username else first_name
    annotated = f"[\u043e\u0442: {sender_tag} | id: {user_id} | chat: {chat_id}]\n{text}"

    log.info("Forwarding to agent: @%s (%s): %s", username, user_id, text[:100])

    # Send typing indicator
    tg_api("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=5)

    # Forward to openclaw agent with concurrency limit
    _agent_sem.acquire()
    try:
        session_id = f"tg-{chat_id}"
        cmd = [
            "openclaw", "agent",
            "--channel", "telegram",
            "--session-id", session_id,
            "-m", annotated,
            "--reply-to", str(chat_id),
            "--deliver",
            "--timeout", "120",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            log.error("openclaw agent failed: %s", result.stderr[:300])
            # Fallback: send error to user
            tg_api("sendMessage", {
                "chat_id": chat_id,
                "text": "\u274c \u041e\u0448\u0438\u0431\u043a\u0430 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0451 \u0440\u0430\u0437.",
            }, timeout=10)
        else:
            log.info("Agent processed message from @%s", username)
    except subprocess.TimeoutExpired:
        log.error("openclaw agent timed out for @%s", username)
        tg_api("sendMessage", {
            "chat_id": chat_id,
            "text": "\u23f0 \u0422\u0430\u0439\u043c\u0430\u0443\u0442 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0451 \u0440\u0430\u0437.",
        }, timeout=10)
    except Exception as e:
        log.error("openclaw agent error: %s", e)
    finally:
        _agent_sem.release()


# ── Main polling loop ────────────────────────────────────────────────


def process_update(update):
    """Route a single update to the right handler."""
    try:
        if "callback_query" in update:
            handle_callback_query(update)
        elif "message" in update:
            handle_message(update)
    except Exception as e:
        log.error("Error processing update %s: %s", update.get("update_id"), e, exc_info=True)


def main():
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    # Delete any existing webhook (we do our own polling)
    result = tg_api("deleteWebhook")
    if result and result.get("ok"):
        log.info("Telegram webhook cleared")

    # Graceful shutdown
    running = threading.Event()
    running.set()

    def on_signal(sig, frame):
        log.info("Received signal %s, shutting down...", sig)
        running.clear()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    offset = 0
    log.info("Started polling Telegram (timeout=%ds, workers=%d)", POLL_TIMEOUT, MAX_WORKERS)

    while running.is_set():
        try:
            result = tg_api("getUpdates", {
                "offset": offset,
                "timeout": POLL_TIMEOUT,
                "allowed_updates": ["message", "callback_query"],
            })

            if not result or not result.get("ok"):
                log.warning("getUpdates failed, retrying in 5s...")
                time.sleep(5)
                continue

            updates = result.get("result", [])

            for update in updates:
                offset = update["update_id"] + 1

                # Callbacks are handled immediately (fast, no LLM)
                if "callback_query" in update:
                    threading.Thread(
                        target=process_update,
                        args=(update,),
                        daemon=True,
                    ).start()
                # Messages go through LLM (slower, use thread)
                elif "message" in update:
                    threading.Thread(
                        target=process_update,
                        args=(update,),
                        daemon=True,
                    ).start()

        except Exception as e:
            log.error("Polling error: %s", e, exc_info=True)
            if running.is_set():
                time.sleep(5)

    log.info("Handler stopped")


if __name__ == "__main__":
    main()
