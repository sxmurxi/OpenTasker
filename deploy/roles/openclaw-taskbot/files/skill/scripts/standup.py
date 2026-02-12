#!/usr/bin/env python3
"""Generate daily standup report for a chat."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta

DB_PATH = os.path.expanduser("~/.openclaw/workspace/data/taskmanager.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def task_row_to_dict(row):
    d = dict(row)
    for field in ("cron_job_ids",):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except json.JSONDecodeError:
                d[field] = []
    return d


def now_iso():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def format_deadline(deadline_str):
    """Format deadline for display."""
    if not deadline_str:
        return "без дедлайна"
    try:
        dt = datetime.fromisoformat(deadline_str)
        return dt.strftime("%d %b, %H:%M")
    except (ValueError, TypeError):
        return deadline_str


def hours_overdue(deadline_str):
    """Calculate how long a task has been overdue."""
    if not deadline_str:
        return 0
    try:
        dt = datetime.fromisoformat(deadline_str)
        delta = datetime.now(UTC) - dt
        total_hours = delta.total_seconds() / 3600
        return max(0, total_hours)
    except (ValueError, TypeError):
        return 0


def format_overdue_duration(hours):
    """Format overdue duration as human-readable string."""
    if hours < 1:
        minutes = int(hours * 60)
        return f"{minutes}мин"
    elif hours < 24:
        return f"{hours:.0f}ч"
    else:
        days = hours / 24
        return f"{days:.0f}д"


def generate_standup(chat_id, output_format="markdown"):
    """Generate daily standup report."""
    conn = get_connection()
    cur = conn.cursor()
    now = now_iso()
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S")
    today_end = datetime.now(UTC).replace(hour=23, minute=59, second=59).strftime("%Y-%m-%dT%H:%M:%S")
    yesterday_start = (datetime.now(UTC) - timedelta(days=1)).replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S")

    # Overdue tasks
    cur.execute(
        """SELECT * FROM tasks
           WHERE chat_id = ? AND deadline IS NOT NULL AND deadline < ?
             AND status IN ('todo', 'in_progress', 'overdue')
           ORDER BY deadline ASC""",
        (chat_id, now),
    )
    overdue = [task_row_to_dict(r) for r in cur.fetchall()]

    # Due today
    cur.execute(
        """SELECT * FROM tasks
           WHERE chat_id = ? AND deadline >= ? AND deadline <= ?
             AND status IN ('todo', 'in_progress')
           ORDER BY deadline ASC""",
        (chat_id, today_start, today_end),
    )
    due_today = [task_row_to_dict(r) for r in cur.fetchall()]

    # In progress
    cur.execute(
        """SELECT * FROM tasks
           WHERE chat_id = ? AND status = 'in_progress'
           ORDER BY priority DESC, deadline ASC""",
        (chat_id,),
    )
    in_progress = [task_row_to_dict(r) for r in cur.fetchall()]

    # Completed yesterday
    cur.execute(
        """SELECT * FROM tasks
           WHERE chat_id = ? AND status = 'done' AND completed_at >= ?
           ORDER BY completed_at DESC""",
        (chat_id, yesterday_start),
    )
    done_yesterday = [task_row_to_dict(r) for r in cur.fetchall()]

    conn.close()

    today_str = datetime.now(UTC).strftime("%d.%m.%Y")

    if output_format == "json":
        return {
            "status": "ok",
            "date": today_str,
            "chat_id": chat_id,
            "overdue": overdue,
            "due_today": due_today,
            "in_progress": in_progress,
            "done_yesterday": done_yesterday,
        }

    # Build markdown report
    priority_emoji = {"high": "\U0001f534", "medium": "\U0001f7e1", "low": "\U0001f7e2"}
    lines = [f"\U0001f4ca **Ежедневный отчёт** — {today_str}", ""]

    if overdue:
        lines.append(f"\U0001f534 **Просрочено ({len(overdue)}):**")
        for t in overdue:
            h = hours_overdue(t.get("deadline"))
            assignee = f"@{t['assignee_username']}" if t.get("assignee_username") else "не назначено"
            lines.append(f"  #{t['id']} {t['description'][:60]} — {assignee} (просрочено на {format_overdue_duration(h)})")
        lines.append("")

    if due_today:
        lines.append(f"\u23f0 **Дедлайн сегодня ({len(due_today)}):**")
        for t in due_today:
            assignee = f"@{t['assignee_username']}" if t.get("assignee_username") else "не назначено"
            dl = format_deadline(t.get("deadline"))
            lines.append(f"  #{t['id']} {t['description'][:60]} — {assignee} (до {dl})")
        lines.append("")

    if in_progress:
        lines.append(f"\U0001f504 **В работе ({len(in_progress)}):**")
        for t in in_progress:
            assignee = f"@{t['assignee_username']}" if t.get("assignee_username") else "не назначено"
            emoji = priority_emoji.get(t.get("priority", "medium"), "\U0001f7e1")
            lines.append(f"  {emoji} #{t['id']} {t['description'][:60]} — {assignee}")
        lines.append("")

    done_count = len(done_yesterday)
    lines.append(f"\U0001f4c8 Выполнено вчера: {done_count} задач(и)")

    if not overdue and not due_today and not in_progress and done_count == 0:
        lines.append("")
        lines.append("Нет активных задач. Отличная работа! \U0001f389")

    report = "\n".join(lines)
    return {"status": "ok", "format": "markdown", "report": report}


def main():
    parser = argparse.ArgumentParser(description="Generate daily standup report")
    parser.add_argument("--chat-id", type=int, required=True)
    parser.add_argument("--format", dest="output_format", type=str, default="markdown",
                        choices=["markdown", "json"])

    args = parser.parse_args()
    result = generate_standup(args.chat_id, args.output_format)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
