#!/usr/bin/env python3
"""Interactive Telegram menu system for TaskBot.

Sends messages with inline buttons. Uses Telegram Bot API directly when
TELEGRAM_BOT_TOKEN is available (fast path from tg_handler), otherwise
falls back to `openclaw message send`.
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime

DB_PATH = os.path.expanduser("~/.openclaw/workspace/data/taskmanager.db")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

PRIORITY_EMOJI = {"high": "\U0001f534", "medium": "\U0001f7e1", "low": "\U0001f7e2"}
STATUS_LABEL = {
    "todo": "\U0001f4cc \u041e\u0436\u0438\u0434\u0430\u0435\u0442",
    "in_progress": "\u25b6\ufe0f \u0412 \u0440\u0430\u0431\u043e\u0442\u0435",
    "done": "\u2705 \u0413\u043e\u0442\u043e\u0432\u043e",
    "cancelled": "\u274c \u041e\u0442\u043c\u0435\u043d\u0435\u043d\u043e",
    "overdue": "\U0001f525 \u041f\u0440\u043e\u0441\u0440\u043e\u0447\u0435\u043d\u043e",
}
MONTHS_RU = [
    "янв", "фев", "мар", "апр", "мая", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _send_via_telegram_api(target, message, buttons=None, media=None):
    """Send directly via Telegram Bot API (fast, no subprocess)."""
    if media:
        # Send photo with caption
        data = {
            "chat_id": int(target),
            "caption": message,
        }
        if buttons:
            data["reply_markup"] = {"inline_keyboard": buttons}
        # Read image file and send as multipart
        import io
        boundary = "----MenuBoundary"
        body = io.BytesIO()
        for key, val in data.items():
            if key == "reply_markup":
                val = json.dumps(val, ensure_ascii=False)
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n".encode())
        with open(media, "rb") as f:
            img_data = f.read()
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"chart.png\"\r\nContent-Type: image/png\r\n\r\n".encode())
        body.write(img_data)
        body.write(b"\r\n")
        body.write(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data=body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    else:
        data = {
            "chat_id": int(target),
            "text": message,
        }
        if buttons:
            data["reply_markup"] = {"inline_keyboard": buttons}
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=json.dumps(data, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
        )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception:
        return False


def _send_via_openclaw(target, message, buttons=None, media=None):
    """Send via openclaw CLI (fallback when BOT_TOKEN not available)."""
    cmd = [
        "openclaw", "message", "send",
        "--channel", "telegram",
        "--target", str(target),
    ]
    if media:
        cmd.extend(["--media", media])
    cmd.extend(["-m", message])
    if buttons:
        cmd.extend(["--buttons", json.dumps(buttons, ensure_ascii=False)])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0


def send_message(target, message, buttons=None, media=None):
    """Send a Telegram message. Uses Bot API directly if token available."""
    if BOT_TOKEN:
        return _send_via_telegram_api(target, message, buttons, media)
    return _send_via_openclaw(target, message, buttons, media)


def fmt_deadline(d):
    if not d:
        return "без дедлайна"
    try:
        dt = datetime.fromisoformat(d)
        time_part = ""
        if dt.hour != 23 or dt.minute != 59:
            time_part = f", {dt.hour}:{dt.minute:02d}"
        return f"{dt.day} {MONTHS_RU[dt.month - 1]}{time_part}"
    except Exception:
        return str(d)


def fmt_priority(p):
    return PRIORITY_EMOJI.get(p, "\u26aa")


# ── Menu commands ─────────────────────────────────────────────


def cmd_main(target):
    msg = "\U0001f4cb TaskBot \u2014 \u0413\u043b\u0430\u0432\u043d\u043e\u0435 \u043c\u0435\u043d\u044e\n\n\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435:"
    buttons = [
        [
            {"text": "\u2795 \u041d\u043e\u0432\u0430\u044f \u0437\u0430\u0434\u0430\u0447\u0430", "callback_data": "m_create"},
            {"text": "\U0001f4cb \u041c\u043e\u0438 \u0437\u0430\u0434\u0430\u0447\u0438", "callback_data": "m_my"},
        ],
        [
            {"text": "\U0001f465 \u0412\u0441\u0435 \u0437\u0430\u0434\u0430\u0447\u0438", "callback_data": "m_all"},
            {"text": "\u23f0 \u041f\u0440\u043e\u0441\u0440\u043e\u0447\u0435\u043d\u043d\u044b\u0435", "callback_data": "m_overdue"},
        ],
        [
            {"text": "\U0001f4ca \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430", "callback_data": "m_stats"},
            {"text": "\U0001f4c8 \u0413\u0440\u0430\u0444\u0438\u043a\u0438", "callback_data": "m_viz"},
        ],
    ]
    return send_message(target, msg, buttons)


def cmd_create_prompt(target):
    msg = (
        "\u270f\ufe0f \u041e\u043f\u0438\u0448\u0438\u0442\u0435 \u0437\u0430\u0434\u0430\u0447\u0443 \u0442\u0435\u043a\u0441\u0442\u043e\u043c.\n\n"
        "\u041c\u043e\u0436\u043d\u043e \u0443\u043a\u0430\u0437\u0430\u0442\u044c:\n"
        "\u2022 \u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u0437\u0430\u0434\u0430\u0447\u0438\n"
        "\u2022 \u0418\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044f (@username \u0438\u043b\u0438 \u0438\u043c\u044f)\n"
        "\u2022 \u0414\u0435\u0434\u043b\u0430\u0439\u043d (\u0434\u043e \u043f\u044f\u0442\u043d\u0438\u0446\u044b, \u0437\u0430\u0432\u0442\u0440\u0430, 15 \u0444\u0435\u0432\u0440\u0430\u043b\u044f)\n"
        "\u2022 \u041f\u0440\u0438\u043e\u0440\u0438\u0442\u0435\u0442 (\u0441\u0440\u043e\u0447\u043d\u043e / \u043d\u0435 \u0441\u0440\u043e\u0447\u043d\u043e)\n\n"
        "\u041f\u0440\u0438\u043c\u0435\u0440: \u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u0438\u0442\u044c \u043e\u0442\u0447\u0451\u0442 @ivan \u0434\u043e \u043f\u044f\u0442\u043d\u0438\u0446\u044b, \u0441\u0440\u043e\u0447\u043d\u043e"
    )
    buttons = [[{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]]
    return send_message(target, msg, buttons)


def cmd_my_tasks(target, user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, description, priority, status, deadline, assignee_username
        FROM tasks
        WHERE assignee_id = ? AND chat_id = ? AND status IN ('todo','in_progress','overdue')
        ORDER BY
            CASE WHEN status='overdue' THEN 0 WHEN status='in_progress' THEN 1 ELSE 2 END,
            deadline IS NULL, deadline
        LIMIT 10
        """,
        [user_id, int(target)],
    )
    tasks = cur.fetchall()
    conn.close()

    if not tasks:
        msg = "\U0001f4cb \u041c\u043e\u0438 \u0437\u0430\u0434\u0430\u0447\u0438\n\n\u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0437\u0430\u0434\u0430\u0447! \U0001f389"
        buttons = [
            [{"text": "\u2795 \u0421\u043e\u0437\u0434\u0430\u0442\u044c", "callback_data": "m_create"}],
            [{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}],
        ]
    else:
        lines = [f"\U0001f4cb \u041c\u043e\u0438 \u0437\u0430\u0434\u0430\u0447\u0438 ({len(tasks)})\n"]
        task_buttons = []
        for t in tasks:
            emoji = fmt_priority(t["priority"])
            dl = fmt_deadline(t["deadline"])
            status_icon = ""
            if t["status"] == "overdue":
                status_icon = " \U0001f525"
            elif t["status"] == "in_progress":
                status_icon = " \u25b6\ufe0f"
            desc = t["description"][:40]
            lines.append(f"{emoji} #{t['id']} {desc} \u2014 {dl}{status_icon}")
            task_buttons.append(
                {"text": f"#{t['id']}", "callback_data": f"t_{t['id']}"}
            )
        msg = "\n".join(lines)
        button_rows = [task_buttons[i : i + 4] for i in range(0, len(task_buttons), 4)]
        button_rows.append(
            [
                {"text": "\u2795 \u0421\u043e\u0437\u0434\u0430\u0442\u044c", "callback_data": "m_create"},
                {"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"},
            ]
        )
        buttons = button_rows

    return send_message(target, msg, buttons)


def cmd_all_tasks(target):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, description, priority, status, deadline, assignee_username
        FROM tasks
        WHERE chat_id = ? AND status IN ('todo','in_progress','overdue')
        ORDER BY
            CASE WHEN status='overdue' THEN 0 WHEN status='in_progress' THEN 1 ELSE 2 END,
            deadline IS NULL, deadline
        LIMIT 15
        """,
        [int(target)],
    )
    tasks = cur.fetchall()
    conn.close()

    if not tasks:
        msg = "\U0001f465 \u0412\u0441\u0435 \u0437\u0430\u0434\u0430\u0447\u0438\n\n\u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0437\u0430\u0434\u0430\u0447."
        buttons = [
            [{"text": "\u2795 \u0421\u043e\u0437\u0434\u0430\u0442\u044c", "callback_data": "m_create"}],
            [{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}],
        ]
    else:
        lines = [f"\U0001f465 \u0412\u0441\u0435 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0435 \u0437\u0430\u0434\u0430\u0447\u0438 ({len(tasks)})\n"]
        task_buttons = []
        for t in tasks:
            emoji = fmt_priority(t["priority"])
            dl = fmt_deadline(t["deadline"])
            assignee = f"@{t['assignee_username']}" if t["assignee_username"] else "\u2014"
            desc = t["description"][:30]
            lines.append(f"{emoji} #{t['id']} {desc} \u2192 {assignee} \u2014 {dl}")
            task_buttons.append(
                {"text": f"#{t['id']}", "callback_data": f"t_{t['id']}"}
            )
        msg = "\n".join(lines)
        button_rows = [task_buttons[i : i + 4] for i in range(0, len(task_buttons), 4)]
        button_rows.append(
            [
                {"text": "\u2795 \u0421\u043e\u0437\u0434\u0430\u0442\u044c", "callback_data": "m_create"},
                {"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"},
            ]
        )
        buttons = button_rows

    return send_message(target, msg, buttons)


def cmd_task_detail(target, task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id = ?", [task_id])
    t = cur.fetchone()
    conn.close()

    if not t:
        msg = f"\u274c \u0417\u0430\u0434\u0430\u0447\u0430 #{task_id} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430."
        buttons = [[{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]]
        return send_message(target, msg, buttons)

    emoji = fmt_priority(t["priority"])
    dl = fmt_deadline(t["deadline"])
    status = STATUS_LABEL.get(t["status"], t["status"])
    assignee = f"@{t['assignee_username']}" if t["assignee_username"] else "\u043d\u0435 \u043d\u0430\u0437\u043d\u0430\u0447\u0435\u043d"
    creator = f"@{t['creator_username']}" if t["creator_username"] else "\u2014"

    msg = (
        f"\U0001f4cb \u0417\u0430\u0434\u0430\u0447\u0430 #{t['id']}\n\n"
        f"\U0001f4dd {t['description']}\n"
        f"\U0001f464 \u0418\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c: {assignee}\n"
        f"\U0001f464 \u0421\u043e\u0437\u0434\u0430\u0442\u0435\u043b\u044c: {creator}\n"
        f"\U0001f4c5 \u0414\u0435\u0434\u043b\u0430\u0439\u043d: {dl}\n"
        f"{emoji} \u041f\u0440\u0438\u043e\u0440\u0438\u0442\u0435\u0442: {t['priority']}\n"
        f"{status}"
    )

    if t["status"] in ("todo", "in_progress", "overdue"):
        row1 = []
        if t["status"] != "in_progress":
            row1.append({"text": "\u25b6\ufe0f \u0412 \u0440\u0430\u0431\u043e\u0442\u0443", "callback_data": f"a_start_{t['id']}"})
        row1.append({"text": "\u2705 \u0413\u043e\u0442\u043e\u0432\u043e", "callback_data": f"a_done_{t['id']}"})

        row2 = []
        if t["deadline"]:
            row2.append({"text": "\U0001f4c5 \u041f\u0440\u043e\u0434\u043b\u0438\u0442\u044c", "callback_data": f"a_extend_{t['id']}"})
        row2.append({"text": "\u270f\ufe0f \u0418\u0437\u043c\u0435\u043d\u0438\u0442\u044c", "callback_data": f"a_edit_{t['id']}"})
        row2.append({"text": "\u274c \u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c", "callback_data": f"a_cancel_{t['id']}"})

        buttons = [
            row1,
            row2,
            [
                {"text": "\u25c0\ufe0f \u041c\u043e\u0438 \u0437\u0430\u0434\u0430\u0447\u0438", "callback_data": "m_my"},
                {"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"},
            ],
        ]
    else:
        buttons = [
            [
                {"text": "\u25c0\ufe0f \u041c\u043e\u0438 \u0437\u0430\u0434\u0430\u0447\u0438", "callback_data": "m_my"},
                {"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"},
            ]
        ]

    return send_message(target, msg, buttons)


def cmd_action(target, action, task_id):
    """Execute task action (done/start/cancel) and show updated detail."""
    script = os.path.join(SCRIPTS_DIR, "tasks.py")
    result = subprocess.run(
        ["python3", script, action, "--id", str(task_id)],
        capture_output=True,
        text=True,
        timeout=10,
    )

    try:
        data = json.loads(result.stdout)
    except Exception:
        send_message(
            target,
            f"\u274c \u041e\u0448\u0438\u0431\u043a\u0430: {result.stderr or result.stdout}",
            [[{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]],
        )
        return False

    if data.get("error"):
        send_message(
            target,
            f"\u274c {data['error']}",
            [[{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]],
        )
        return False

    action_labels = {
        "done": "\u2705 \u0417\u0430\u0434\u0430\u0447\u0430 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430!",
        "start": "\u25b6\ufe0f \u0417\u0430\u0434\u0430\u0447\u0430 \u0432\u0437\u044f\u0442\u0430 \u0432 \u0440\u0430\u0431\u043e\u0442\u0443!",
        "cancel": "\u274c \u0417\u0430\u0434\u0430\u0447\u0430 \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u0430.",
    }
    label = action_labels.get(action, action)
    send_message(target, f"{label} (#{task_id})")

    return cmd_task_detail(target, task_id)


def cmd_stats(target):
    script = os.path.join(SCRIPTS_DIR, "tasks.py")
    result = subprocess.run(
        ["python3", script, "stats", "--chat-id", str(target)],
        capture_output=True,
        text=True,
        timeout=10,
    )

    try:
        data = json.loads(result.stdout)
        s = data.get("stats", data)
    except Exception:
        return send_message(
            target,
            "\u274c \u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u043e\u043b\u0443\u0447\u0435\u043d\u0438\u044f \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0438",
            [[{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]],
        )

    top_lines = ""
    top = s.get("top_assignees", [])
    if top:
        top_parts = [f"@{a['username']} ({a['task_count']})" for a in top[:5]]
        top_lines = f"\n\U0001f3c6 \u0422\u043e\u043f: {', '.join(top_parts)}"

    msg = (
        f"\U0001f4ca \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430\n\n"
        f"\U0001f4cc \u0412\u0441\u0435\u0433\u043e: {s.get('total', 0)}\n"
        f"\u2705 \u0412\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e: {s.get('done', 0)}\n"
        f"\u25b6\ufe0f \u0412 \u0440\u0430\u0431\u043e\u0442\u0435: {s.get('in_progress', 0)}\n"
        f"\U0001f4cb \u041e\u0436\u0438\u0434\u0430\u0435\u0442: {s.get('todo', 0)}\n"
        f"\U0001f525 \u041f\u0440\u043e\u0441\u0440\u043e\u0447\u0435\u043d\u043e: {s.get('overdue', 0)}\n"
        f"\u274c \u041e\u0442\u043c\u0435\u043d\u0435\u043d\u043e: {s.get('cancelled', 0)}"
        f"{top_lines}"
    )

    buttons = [
        [{"text": "\U0001f4c8 \u0413\u0440\u0430\u0444\u0438\u043a\u0438", "callback_data": "m_viz"}],
        [{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}],
    ]
    return send_message(target, msg, buttons)


def cmd_overdue(target):
    script = os.path.join(SCRIPTS_DIR, "tasks.py")
    result = subprocess.run(
        ["python3", script, "overdue", "--chat-id", str(target)],
        capture_output=True,
        text=True,
        timeout=10,
    )

    try:
        data = json.loads(result.stdout)
    except Exception:
        return send_message(
            target,
            "\u274c \u041e\u0448\u0438\u0431\u043a\u0430",
            [[{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]],
        )

    tasks = data.get("tasks", [])
    if not tasks:
        msg = "\u23f0 \u041f\u0440\u043e\u0441\u0440\u043e\u0447\u0435\u043d\u043d\u044b\u0435 \u0437\u0430\u0434\u0430\u0447\u0438\n\n\u041d\u0435\u0442 \u043f\u0440\u043e\u0441\u0440\u043e\u0447\u0435\u043d\u043d\u044b\u0445 \u0437\u0430\u0434\u0430\u0447! \U0001f44d"
        buttons = [[{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]]
    else:
        lines = [f"\u23f0 \u041f\u0440\u043e\u0441\u0440\u043e\u0447\u0435\u043d\u043d\u044b\u0435 ({len(tasks)})\n"]
        task_buttons = []
        for t in tasks:
            dl = fmt_deadline(t.get("deadline"))
            assignee = f"@{t.get('assignee_username', '?')}"
            desc = t["description"][:30]
            lines.append(f"\U0001f525 #{t['id']} {desc} \u2192 {assignee} \u2014 {dl}")
            task_buttons.append(
                {"text": f"#{t['id']}", "callback_data": f"t_{t['id']}"}
            )
        msg = "\n".join(lines)
        button_rows = [task_buttons[i : i + 4] for i in range(0, len(task_buttons), 4)]
        button_rows.append([{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}])
        buttons = button_rows

    return send_message(target, msg, buttons)


def cmd_viz(target):
    msg = "\U0001f4c8 \u0412\u0438\u0437\u0443\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f\n\n\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0433\u0440\u0430\u0444\u0438\u043a:"
    buttons = [
        [
            {"text": "\U0001f967 \u0421\u0442\u0430\u0442\u0443\u0441\u044b", "callback_data": "v_status"},
            {"text": "\U0001f465 \u041d\u0430\u0433\u0440\u0443\u0437\u043a\u0430", "callback_data": "v_workload"},
        ],
        [
            {"text": "\U0001f534\U0001f7e1\U0001f7e2 \u041f\u0440\u0438\u043e\u0440\u0438\u0442\u0435\u0442\u044b", "callback_data": "v_priority"},
            {"text": "\U0001f4c8 \u0422\u0440\u0435\u043d\u0434", "callback_data": "v_trend"},
        ],
        [{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}],
    ]
    return send_message(target, msg, buttons)


def cmd_viz_chart(target, chart_type):
    """Generate and send a single chart. Dashboard redirects to selection menu."""
    if chart_type == "dashboard":
        return cmd_viz(target)

    viz_script = os.path.join(SCRIPTS_DIR, "visualize.py")
    args = ["python3", viz_script, chart_type, "--chat-id", str(target)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)

    nav_buttons = [
        [{"text": "\u25c0\ufe0f \u0413\u0440\u0430\u0444\u0438\u043a\u0438", "callback_data": "m_viz"},
         {"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}],
    ]

    try:
        data = json.loads(result.stdout)
    except Exception:
        return send_message(
            target,
            f"\u274c \u041e\u0448\u0438\u0431\u043a\u0430 \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u0438: {result.stderr[:200]}",
            nav_buttons,
        )

    if data.get("error"):
        return send_message(target, f"\u274c {data['error']}", nav_buttons)

    path = data.get("path")
    if path:
        chart_names = {
            "status": "\U0001f4ca \u041e\u0431\u0437\u043e\u0440 \u0441\u0442\u0430\u0442\u0443\u0441\u043e\u0432",
            "workload": "\U0001f4ca \u041d\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u043f\u043e \u0438\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044f\u043c",
            "priority": "\U0001f4ca \u041f\u0440\u0438\u043e\u0440\u0438\u0442\u0435\u0442\u044b",
            "trend": "\U0001f4ca \u0422\u0440\u0435\u043d\u0434",
        }
        label = chart_names.get(chart_type, f"\U0001f4ca {chart_type.title()}")
        return send_message(target, label, nav_buttons, media=path)
    else:
        return send_message(
            target,
            f"\u274c {data.get('error', '\u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445')}",
            nav_buttons,
        )


# ── Route — universal callback dispatcher ─────────────────────


def cmd_route(target, callback_data, user_id=None):
    """Parse callback_data and execute the corresponding menu command.

    This is the single entry point for ALL button callbacks.
    The LLM only needs to call: menu.py --target <id> route <callback_data>
    """
    cb = callback_data.strip()

    # Menu navigation
    if cb == "m_main":
        return cmd_main(target)
    if cb == "m_create":
        return cmd_create_prompt(target)
    if cb == "m_my":
        if not user_id:
            return send_message(target, "\u274c \u041d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d user-id",
                                [[{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]])
        return cmd_my_tasks(target, user_id)
    if cb == "m_all":
        return cmd_all_tasks(target)
    if cb == "m_overdue":
        return cmd_overdue(target)
    if cb == "m_stats":
        return cmd_stats(target)
    if cb == "m_viz":
        return cmd_viz(target)

    # Task detail: t_<id>
    if cb.startswith("t_"):
        try:
            task_id = int(cb[2:])
            return cmd_task_detail(target, task_id)
        except ValueError:
            pass

    # Task actions: a_done_<id>, a_start_<id>, a_cancel_<id>
    for prefix, action in [("a_done_", "done"), ("a_start_", "start"), ("a_cancel_", "cancel")]:
        if cb.startswith(prefix):
            try:
                task_id = int(cb[len(prefix):])
                return cmd_action(target, action, task_id)
            except ValueError:
                pass

    # Edit/extend — return instruction for LLM to handle via text
    if cb.startswith("a_edit_"):
        task_id = cb[7:]
        send_message(
            target,
            f"\u270f\ufe0f \u0427\u0442\u043e \u0438\u0437\u043c\u0435\u043d\u0438\u0442\u044c \u0432 \u0437\u0430\u0434\u0430\u0447\u0435 #{task_id}?\n\u041d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u043d\u043e\u0432\u043e\u0435 \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435, \u043f\u0440\u0438\u043e\u0440\u0438\u0442\u0435\u0442 \u0438\u043b\u0438 \u0438\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044f.",
            [[{"text": "\u25c0\ufe0f \u041d\u0430\u0437\u0430\u0434", "callback_data": f"t_{task_id}"},
              {"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]],
        )
        return True

    if cb.startswith("a_extend_"):
        task_id = cb[9:]
        send_message(
            target,
            f"\U0001f4c5 \u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u043d\u043e\u0432\u044b\u0439 \u0434\u0435\u0434\u043b\u0430\u0439\u043d \u0434\u043b\u044f \u0437\u0430\u0434\u0430\u0447\u0438 #{task_id}\n\u041d\u0430\u043f\u0440\u0438\u043c\u0435\u0440: \u0434\u043e \u043f\u044f\u0442\u043d\u0438\u0446\u044b, 20 \u0444\u0435\u0432\u0440\u0430\u043b\u044f, \u0447\u0435\u0440\u0435\u0437 3 \u0434\u043d\u044f",
            [[{"text": "\u25c0\ufe0f \u041d\u0430\u0437\u0430\u0434", "callback_data": f"t_{task_id}"},
              {"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]],
        )
        return True

    # Visualization charts: v_<type>
    if cb.startswith("v_"):
        chart = cb[2:]
        return cmd_viz_chart(target, chart)

    # Unknown callback
    return send_message(
        target,
        f"\u2753 \u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u0430\u044f \u043a\u043e\u043c\u0430\u043d\u0434\u0430: {cb}",
        [[{"text": "\u25c0\ufe0f \u041c\u0435\u043d\u044e", "callback_data": "m_main"}]],
    )


# ── CLI ───────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="TaskBot interactive menu")
    parser.add_argument("--target", required=True, help="Telegram chat_id")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("main")
    subparsers.add_parser("create_prompt")

    p_my = subparsers.add_parser("my_tasks")
    p_my.add_argument("--user-id", type=int, required=True)

    subparsers.add_parser("all_tasks")

    p_task = subparsers.add_parser("task")
    p_task.add_argument("--id", type=int, required=True)

    p_action = subparsers.add_parser("action")
    p_action.add_argument("--action", required=True, choices=["done", "start", "cancel"])
    p_action.add_argument("--id", type=int, required=True)

    subparsers.add_parser("stats")
    subparsers.add_parser("overdue")
    subparsers.add_parser("viz")

    p_viz = subparsers.add_parser("viz_chart")
    p_viz.add_argument("--chart", required=True,
                       choices=["status", "workload", "priority", "trend", "dashboard"])

    p_route = subparsers.add_parser("route")
    p_route.add_argument("callback_data", help="Telegram callback_data string")
    p_route.add_argument("--user-id", type=int, default=None)

    args = parser.parse_args()
    ok = False

    if args.command == "route":
        ok = cmd_route(args.target, args.callback_data, args.user_id)
    elif args.command == "main":
        ok = cmd_main(args.target)
    elif args.command == "create_prompt":
        ok = cmd_create_prompt(args.target)
    elif args.command == "my_tasks":
        ok = cmd_my_tasks(args.target, args.user_id)
    elif args.command == "all_tasks":
        ok = cmd_all_tasks(args.target)
    elif args.command == "task":
        ok = cmd_task_detail(args.target, args.id)
    elif args.command == "action":
        ok = cmd_action(args.target, args.action, args.id)
    elif args.command == "stats":
        ok = cmd_stats(args.target)
    elif args.command == "overdue":
        ok = cmd_overdue(args.target)
    elif args.command == "viz":
        ok = cmd_viz(args.target)
    elif args.command == "viz_chart":
        ok = cmd_viz_chart(args.target, args.chart)

    result = {"ok": bool(ok), "command": args.command}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
