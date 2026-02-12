#!/usr/bin/env python3
"""Deadline checking and overdue task management."""

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


def check_overdue(chat_id=None):
    """Find tasks that just became overdue and update their status.

    Returns tasks that were NOT already marked as overdue (newly overdue).
    """
    conn = get_connection()
    cur = conn.cursor()
    now = now_iso()

    conditions = [
        "deadline IS NOT NULL",
        "deadline < ?",
        "status IN ('todo', 'in_progress')",
    ]
    params = [now]

    if chat_id:
        conditions.append("chat_id = ?")
        params.append(chat_id)

    where = " WHERE " + " AND ".join(conditions)
    cur.execute(f"SELECT * FROM tasks{where}", params)
    newly_overdue = [task_row_to_dict(r) for r in cur.fetchall()]

    # Update status to overdue
    if newly_overdue:
        ids = [t["id"] for t in newly_overdue]
        placeholders = ",".join("?" for _ in ids)
        cur.execute(
            f"UPDATE tasks SET status = 'overdue', updated_at = datetime('now') WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()

    conn.close()

    notifications = []
    for task in newly_overdue:
        deadline_dt = datetime.fromisoformat(task["deadline"]) if task["deadline"] else None
        if deadline_dt:
            delta = datetime.now(UTC) - deadline_dt
            hours_overdue = delta.total_seconds() / 3600
        else:
            hours_overdue = 0

        notifications.append({
            "task_id": task["id"],
            "description": task["description"],
            "title": task.get("title"),
            "assignee_username": task.get("assignee_username"),
            "assignee_id": task.get("assignee_id"),
            "deadline": task.get("deadline"),
            "hours_overdue": round(hours_overdue, 1),
            "priority": task.get("priority"),
            "chat_id": task.get("chat_id"),
        })

    return {
        "status": "ok",
        "newly_overdue_count": len(notifications),
        "tasks": notifications,
    }


def upcoming(chat_id=None, hours=24):
    """Get tasks with deadlines in the next N hours."""
    conn = get_connection()
    cur = conn.cursor()

    now = now_iso()
    future = (datetime.now(UTC) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")

    conditions = [
        "deadline IS NOT NULL",
        "deadline >= ?",
        "deadline <= ?",
        "status IN ('todo', 'in_progress')",
    ]
    params = [now, future]

    if chat_id:
        conditions.append("chat_id = ?")
        params.append(chat_id)

    where = " WHERE " + " AND ".join(conditions)
    cur.execute(
        f"SELECT * FROM tasks{where} ORDER BY deadline ASC",
        params,
    )
    tasks = [task_row_to_dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "status": "ok",
        "hours_window": hours,
        "count": len(tasks),
        "tasks": tasks,
    }


def main():
    parser = argparse.ArgumentParser(description="Reminders and deadline checking")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # check-overdue
    p_overdue = subparsers.add_parser("check-overdue", help="Check for newly overdue tasks")
    p_overdue.add_argument("--chat-id", type=int, default=None)

    # upcoming
    p_upcoming = subparsers.add_parser("upcoming", help="Tasks with upcoming deadlines")
    p_upcoming.add_argument("--chat-id", type=int, default=None)
    p_upcoming.add_argument("--hours", type=int, default=24)

    args = parser.parse_args()

    if args.command == "check-overdue":
        result = check_overdue(args.chat_id)
    elif args.command == "upcoming":
        result = upcoming(args.chat_id, args.hours)
    else:
        result = {"error": f"Unknown command: {args.command}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
