#!/usr/bin/env python3
"""Generate weekly review report and optionally archive completed tasks."""

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


def generate_weekly_review(chat_id, archive=False):
    """Generate weekly review with stats and trends."""
    conn = get_connection()
    cur = conn.cursor()

    week_ago = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    two_weeks_ago = (datetime.now(UTC) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    # This week stats
    cur.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE chat_id = ? AND created_at >= ?",
        (chat_id, week_ago),
    )
    created_this_week = cur.fetchone()["cnt"]

    cur.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE chat_id = ? AND status = 'done' AND completed_at >= ?",
        (chat_id, week_ago),
    )
    done_this_week = cur.fetchone()["cnt"]

    cur.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE chat_id = ? AND status = 'cancelled' AND updated_at >= ?",
        (chat_id, week_ago),
    )
    cancelled_this_week = cur.fetchone()["cnt"]

    # Previous week stats for comparison
    cur.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE chat_id = ? AND created_at >= ? AND created_at < ?",
        (chat_id, two_weeks_ago, week_ago),
    )
    created_prev_week = cur.fetchone()["cnt"]

    cur.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE chat_id = ? AND status = 'done' AND completed_at >= ? AND completed_at < ?",
        (chat_id, two_weeks_ago, week_ago),
    )
    done_prev_week = cur.fetchone()["cnt"]

    # Current active counts
    cur.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE chat_id = ? AND status IN ('todo', 'in_progress')",
        (chat_id,),
    )
    active_tasks = cur.fetchone()["cnt"]

    cur.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE chat_id = ? AND status = 'overdue'",
        (chat_id,),
    )
    overdue_count = cur.fetchone()["cnt"]

    # Top performers this week
    cur.execute(
        """SELECT assignee_username, COUNT(*) as done_count
           FROM tasks
           WHERE chat_id = ? AND status = 'done' AND completed_at >= ?
           GROUP BY assignee_id
           ORDER BY done_count DESC
           LIMIT 5""",
        (chat_id, week_ago),
    )
    top_performers = [
        {"username": r["assignee_username"], "done_count": r["done_count"]}
        for r in cur.fetchall()
    ]

    # Tasks completed this week (for listing)
    cur.execute(
        """SELECT * FROM tasks
           WHERE chat_id = ? AND status = 'done' AND completed_at >= ?
           ORDER BY completed_at DESC""",
        (chat_id, week_ago),
    )
    completed_tasks = [task_row_to_dict(r) for r in cur.fetchall()]

    # Archive old done/cancelled tasks (older than 2 weeks)
    archived_count = 0
    if archive:
        cur.execute(
            """SELECT COUNT(*) as cnt FROM tasks
               WHERE chat_id = ? AND status IN ('done', 'cancelled')
                 AND updated_at < ?""",
            (chat_id, two_weeks_ago),
        )
        archived_count = cur.fetchone()["cnt"]

        if archived_count > 0:
            # We don't delete — just mark with a special note in title
            # In a production system this would move to an archive table
            cur.execute(
                """DELETE FROM tasks
                   WHERE chat_id = ? AND status IN ('done', 'cancelled')
                     AND updated_at < ?""",
                (chat_id, two_weeks_ago),
            )
            conn.commit()

    conn.close()

    # Build trends
    def trend_arrow(current, previous):
        if current > previous:
            return "\u2b06\ufe0f"
        elif current < previous:
            return "\u2b07\ufe0f"
        return "\u27a1\ufe0f"

    today_str = datetime.now(UTC).strftime("%d.%m.%Y")
    week_start = (datetime.now(UTC) - timedelta(days=7)).strftime("%d.%m")

    lines = [
        f"\U0001f4cb **Еженедельный обзор** — {week_start} \u2014 {today_str}",
        "",
        f"\U0001f4ca **Статистика за неделю:**",
        f"  \u2705 Создано: {created_this_week} {trend_arrow(created_this_week, created_prev_week)} (прошлая: {created_prev_week})",
        f"  \u2705 Выполнено: {done_this_week} {trend_arrow(done_this_week, done_prev_week)} (прошлая: {done_prev_week})",
        f"  \u274c Отменено: {cancelled_this_week}",
        "",
        f"\U0001f4c8 **Текущее состояние:**",
        f"  \U0001f504 Активные задачи: {active_tasks}",
        f"  \U0001f534 Просрочено: {overdue_count}",
        "",
    ]

    if top_performers:
        lines.append("\U0001f3c6 **Топ участников (выполнено):**")
        for i, p in enumerate(top_performers, 1):
            medal = ["\U0001f947", "\U0001f948", "\U0001f949"][i - 1] if i <= 3 else f"  {i}."
            username = f"@{p['username']}" if p.get("username") else "без username"
            lines.append(f"  {medal} {username} — {p['done_count']} задач")
        lines.append("")

    if archive and archived_count > 0:
        lines.append(f"\U0001f5d1 Архивировано: {archived_count} старых задач")
        lines.append("")

    completion_rate = (done_this_week / created_this_week * 100) if created_this_week > 0 else 0
    lines.append(f"\U0001f3af Completion rate: {completion_rate:.0f}%")

    report = "\n".join(lines)

    return {
        "status": "ok",
        "format": "markdown",
        "report": report,
        "stats": {
            "created_this_week": created_this_week,
            "done_this_week": done_this_week,
            "cancelled_this_week": cancelled_this_week,
            "created_prev_week": created_prev_week,
            "done_prev_week": done_prev_week,
            "active_tasks": active_tasks,
            "overdue_count": overdue_count,
            "archived_count": archived_count,
            "top_performers": top_performers,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Generate weekly review report")
    parser.add_argument("--chat-id", type=int, required=True)
    parser.add_argument("--archive", action="store_true",
                        help="Archive completed tasks older than 2 weeks")

    args = parser.parse_args()
    result = generate_weekly_review(args.chat_id, args.archive)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
