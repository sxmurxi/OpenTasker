#!/usr/bin/env python3
"""Task CRUD operations for the Team TaskManager skill."""

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
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def task_row_to_dict(row):
    """Convert sqlite3.Row to dict, parsing JSON fields."""
    d = dict(row)
    for field in ("cron_job_ids", "tags"):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except json.JSONDecodeError:
                d[field] = []
    return d


def now_iso():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def normalize_tags(tags):
    """Normalize tags: lowercase, strip #, trim whitespace, deduplicate."""
    if not tags:
        return []
    seen = set()
    result = []
    for t in tags:
        tag = t.strip().lstrip("#").lower().strip()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


# ─── ADD ────────────────────────────────────────────────────────────────────

def add_task(data):
    """Create a new task from a JSON dict."""
    required = ["description", "creator_id", "chat_id"]
    for field in required:
        key = field if field != "creator_id" else "creator_telegram_id"
        alt_key = field
        if key not in data and alt_key not in data:
            return {"error": f"Missing required field: {field}"}

    conn = get_connection()
    cur = conn.cursor()

    creator_id = data.get("creator_telegram_id") or data.get("creator_id")
    assignee_id = data.get("assignee_telegram_id") or data.get("assignee_id")

    tags = normalize_tags(data.get("tags", []))

    cur.execute(
        """INSERT INTO tasks
           (description, title, creator_id, creator_username,
            assignee_id, assignee_username, chat_id,
            deadline, priority, tags)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["description"],
            data.get("title"),
            creator_id,
            data.get("creator_username"),
            assignee_id,
            data.get("assignee_username"),
            data["chat_id"],
            data.get("deadline"),
            data.get("priority", "medium"),
            json.dumps(tags, ensure_ascii=False),
        ),
    )
    task_id = cur.lastrowid
    conn.commit()

    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = task_row_to_dict(cur.fetchone())
    conn.close()

    return {"status": "ok", "task": task}


# ─── LIST ───────────────────────────────────────────────────────────────────

def list_tasks(assignee_id=None, chat_id=None, status=None):
    """List tasks with optional filters."""
    conn = get_connection()
    cur = conn.cursor()

    conditions = []
    params = []

    if assignee_id is not None:
        conditions.append("assignee_id = ?")
        params.append(assignee_id)
    if chat_id is not None:
        conditions.append("chat_id = ?")
        params.append(chat_id)
    if status:
        statuses = [s.strip() for s in status.split(",")]
        placeholders = ",".join("?" for _ in statuses)
        conditions.append(f"status IN ({placeholders})")
        params.extend(statuses)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"SELECT * FROM tasks{where} ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, deadline ASC NULLS LAST, id DESC"

    cur.execute(query, params)
    tasks = [task_row_to_dict(r) for r in cur.fetchall()]
    conn.close()

    return {"status": "ok", "count": len(tasks), "tasks": tasks}


# ─── CREATED ────────────────────────────────────────────────────────────────

def list_created(creator_id, chat_id=None):
    """List tasks created by a specific user."""
    conn = get_connection()
    cur = conn.cursor()

    if chat_id:
        cur.execute(
            "SELECT * FROM tasks WHERE creator_id = ? AND chat_id = ? ORDER BY created_at DESC",
            (creator_id, chat_id),
        )
    else:
        cur.execute(
            "SELECT * FROM tasks WHERE creator_id = ? ORDER BY created_at DESC",
            (creator_id,),
        )

    tasks = [task_row_to_dict(r) for r in cur.fetchall()]
    conn.close()

    return {"status": "ok", "count": len(tasks), "tasks": tasks}


# ─── GET ────────────────────────────────────────────────────────────────────

def get_task(task_id):
    """Get a single task by ID."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    conn.close()

    if row:
        return {"status": "ok", "task": task_row_to_dict(row)}
    return {"error": f"Task #{task_id} not found"}


# ─── STATUS CHANGES ────────────────────────────────────────────────────────

def update_status(task_id, new_status):
    """Change task status."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"error": f"Task #{task_id} not found"}

    task = task_row_to_dict(row)
    old_status = task["status"]

    if old_status == new_status:
        conn.close()
        return {"status": "ok", "task": task, "message": f"Task already has status '{new_status}'"}

    completed_at = now_iso() if new_status == "done" else task.get("completed_at")

    cur.execute(
        """UPDATE tasks
           SET status = ?, updated_at = datetime('now'), completed_at = ?
           WHERE id = ?""",
        (new_status, completed_at, task_id),
    )
    conn.commit()

    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    updated = task_row_to_dict(cur.fetchone())
    conn.close()

    result = {
        "status": "ok",
        "task": updated,
        "old_status": old_status,
        "new_status": new_status,
    }

    if new_status in ("done", "cancelled"):
        result["cron_jobs_to_remove"] = task.get("cron_job_ids", [])

    return result


# ─── EXTEND DEADLINE ───────────────────────────────────────────────────────

def extend_deadline(task_id, new_deadline):
    """Extend the deadline for a task."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"error": f"Task #{task_id} not found"}

    task = task_row_to_dict(row)
    old_deadline = task.get("deadline")

    new_status = task["status"]
    if task["status"] == "overdue":
        new_status = "todo"

    cur.execute(
        """UPDATE tasks
           SET deadline = ?, status = ?, updated_at = datetime('now')
           WHERE id = ?""",
        (new_deadline, new_status, task_id),
    )
    conn.commit()

    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    updated = task_row_to_dict(cur.fetchone())
    conn.close()

    return {
        "status": "ok",
        "task": updated,
        "old_deadline": old_deadline,
        "new_deadline": new_deadline,
        "old_cron_jobs_to_remove": task.get("cron_job_ids", []),
    }


# ─── EDIT ──────────────────────────────────────────────────────────────────

def edit_task(task_id, updates):
    """Edit task fields (description, title, priority, assignee, etc.)."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"error": f"Task #{task_id} not found"}

    allowed_fields = {
        "description", "title", "priority", "assignee_id", "assignee_telegram_id",
        "assignee_username", "deadline", "tags",
    }
    set_clauses = []
    params = []

    for key, value in updates.items():
        field = key
        if key == "assignee_telegram_id":
            field = "assignee_id"
        if field in allowed_fields:
            if field == "tags":
                value = json.dumps(normalize_tags(value), ensure_ascii=False)
            set_clauses.append(f"{field} = ?")
            params.append(value)

    if not set_clauses:
        conn.close()
        return {"error": "No valid fields to update"}

    set_clauses.append("updated_at = datetime('now')")
    params.append(task_id)

    cur.execute(
        f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?",
        params,
    )
    conn.commit()

    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    updated = task_row_to_dict(cur.fetchone())
    conn.close()

    return {"status": "ok", "task": updated}


# ─── STATS ─────────────────────────────────────────────────────────────────

def get_stats(chat_id=None, period="all"):
    """Get task statistics."""
    conn = get_connection()
    cur = conn.cursor()

    conditions = []
    params = []

    if chat_id:
        conditions.append("chat_id = ?")
        params.append(chat_id)

    if period == "week":
        conditions.append("created_at >= datetime('now', '-7 days')")
    elif period == "month":
        conditions.append("created_at >= datetime('now', '-30 days')")

    where = " WHERE " + " AND ".join(conditions) if conditions else ""

    cur.execute(f"SELECT COUNT(*) as total FROM tasks{where}", params)
    total = cur.fetchone()["total"]

    stats = {"total": total}
    for s in ("todo", "in_progress", "done", "cancelled", "overdue"):
        conds = conditions + [f"status = '{s}'"]
        w = " WHERE " + " AND ".join(conds)
        cur.execute(f"SELECT COUNT(*) as cnt FROM tasks{w}", params)
        stats[s] = cur.fetchone()["cnt"]

    # Top assignees
    assignee_where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    cur.execute(
        f"""SELECT assignee_username, COUNT(*) as task_count
            FROM tasks{assignee_where}
            GROUP BY assignee_id
            ORDER BY task_count DESC
            LIMIT 10""",
        params,
    )
    stats["top_assignees"] = [
        {"username": r["assignee_username"], "task_count": r["task_count"]}
        for r in cur.fetchall()
    ]

    conn.close()
    return {"status": "ok", "period": period, "stats": stats}


# ─── SEARCH ────────────────────────────────────────────────────────────────

def search_tasks(query, chat_id=None):
    """Search tasks by description/title text."""
    conn = get_connection()
    cur = conn.cursor()

    search_pattern = f"%{query}%"
    if chat_id:
        cur.execute(
            """SELECT * FROM tasks
               WHERE chat_id = ? AND (description LIKE ? OR title LIKE ? OR tags LIKE ?)
               ORDER BY created_at DESC""",
            (chat_id, search_pattern, search_pattern, search_pattern),
        )
    else:
        cur.execute(
            """SELECT * FROM tasks
               WHERE description LIKE ? OR title LIKE ? OR tags LIKE ?
               ORDER BY created_at DESC""",
            (search_pattern, search_pattern, search_pattern),
        )

    tasks = [task_row_to_dict(r) for r in cur.fetchall()]
    conn.close()

    return {"status": "ok", "count": len(tasks), "query": query, "tasks": tasks}


# ─── TAGS ─────────────────────────────────────────────────────────────────

def list_by_tag(tag, chat_id=None):
    """List tasks with a specific tag."""
    conn = get_connection()
    cur = conn.cursor()

    tag_pattern = f'%"{tag}"%'
    if chat_id:
        cur.execute(
            """SELECT * FROM tasks
               WHERE tags LIKE ? AND chat_id = ?
               ORDER BY created_at DESC""",
            (tag_pattern, chat_id),
        )
    else:
        cur.execute(
            """SELECT * FROM tasks
               WHERE tags LIKE ?
               ORDER BY created_at DESC""",
            (tag_pattern,),
        )

    tasks = [task_row_to_dict(r) for r in cur.fetchall()]
    conn.close()

    return {"status": "ok", "tag": tag, "count": len(tasks), "tasks": tasks}


def list_tags(chat_id=None):
    """List all unique tags with task counts."""
    conn = get_connection()
    cur = conn.cursor()

    if chat_id:
        cur.execute("SELECT tags FROM tasks WHERE chat_id = ? AND tags != '[]'", (chat_id,))
    else:
        cur.execute("SELECT tags FROM tasks WHERE tags != '[]'")

    tag_counts = {}
    for row in cur.fetchall():
        try:
            tags = json.loads(row["tags"])
        except (json.JSONDecodeError, TypeError):
            continue
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    conn.close()

    tags_list = [{"tag": t, "count": c} for t, c in sorted(tag_counts.items(), key=lambda x: -x[1])]
    return {"status": "ok", "count": len(tags_list), "tags": tags_list}


# ─── OVERDUE ───────────────────────────────────────────────────────────────

def get_overdue(chat_id=None):
    """Get all overdue tasks (deadline passed, not done/cancelled)."""
    conn = get_connection()
    cur = conn.cursor()

    now = now_iso()

    if chat_id:
        cur.execute(
            """SELECT * FROM tasks
               WHERE chat_id = ?
                 AND deadline IS NOT NULL
                 AND deadline < ?
                 AND status IN ('todo', 'in_progress', 'overdue')
               ORDER BY deadline ASC""",
            (chat_id, now),
        )
    else:
        cur.execute(
            """SELECT * FROM tasks
               WHERE deadline IS NOT NULL
                 AND deadline < ?
                 AND status IN ('todo', 'in_progress', 'overdue')
               ORDER BY deadline ASC""",
            (now,),
        )

    tasks = [task_row_to_dict(r) for r in cur.fetchall()]
    conn.close()

    return {"status": "ok", "count": len(tasks), "tasks": tasks}


# ─── MAIN ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Task management CLI for TaskManager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = subparsers.add_parser("add", help="Create a new task")
    p_add.add_argument("--json", dest="json_data", type=str, required=True,
                       help="JSON string with task data")

    # list
    p_list = subparsers.add_parser("list", help="List tasks by assignee")
    p_list.add_argument("--assignee-id", type=int, default=None)
    p_list.add_argument("--chat-id", type=int, default=None)
    p_list.add_argument("--status", type=str, default=None,
                        help="Comma-separated statuses: todo,in_progress,done,cancelled,overdue")

    # created
    p_created = subparsers.add_parser("created", help="List tasks created by user")
    p_created.add_argument("--creator-id", type=int, required=True)
    p_created.add_argument("--chat-id", type=int, default=None)

    # get
    p_get = subparsers.add_parser("get", help="Get task details")
    p_get.add_argument("--id", type=int, required=True)

    # done
    p_done = subparsers.add_parser("done", help="Mark task as done")
    p_done.add_argument("--id", type=int, required=True)

    # start
    p_start = subparsers.add_parser("start", help="Mark task as in_progress")
    p_start.add_argument("--id", type=int, required=True)

    # cancel
    p_cancel = subparsers.add_parser("cancel", help="Cancel a task")
    p_cancel.add_argument("--id", type=int, required=True)

    # extend
    p_extend = subparsers.add_parser("extend", help="Extend task deadline")
    p_extend.add_argument("--id", type=int, required=True)
    p_extend.add_argument("--deadline", type=str, required=True,
                          help="New deadline in ISO 8601 format")

    # edit
    p_edit = subparsers.add_parser("edit", help="Edit task fields")
    p_edit.add_argument("--id", type=int, required=True)
    p_edit.add_argument("--json", dest="json_data", type=str, required=True,
                        help="JSON string with fields to update")

    # stats
    p_stats = subparsers.add_parser("stats", help="Show task statistics")
    p_stats.add_argument("--chat-id", type=int, default=None)
    p_stats.add_argument("--period", type=str, default="all",
                         choices=["week", "month", "all"])

    # search
    p_search = subparsers.add_parser("search", help="Search tasks by text")
    p_search.add_argument("query", type=str)
    p_search.add_argument("--chat-id", type=int, default=None)

    # overdue
    p_overdue = subparsers.add_parser("overdue", help="List overdue tasks")
    p_overdue.add_argument("--chat-id", type=int, default=None)

    # list-by-tag
    p_by_tag = subparsers.add_parser("list-by-tag", help="List tasks with a specific tag")
    p_by_tag.add_argument("tag", type=str)
    p_by_tag.add_argument("--chat-id", type=int, default=None)

    # list-tags
    p_tags = subparsers.add_parser("list-tags", help="List all unique tags")
    p_tags.add_argument("--chat-id", type=int, default=None)

    args = parser.parse_args()

    if args.command == "add":
        try:
            data = json.loads(args.json_data)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}"}))
            sys.exit(1)
        result = add_task(data)

    elif args.command == "list":
        result = list_tasks(args.assignee_id, args.chat_id, args.status)

    elif args.command == "created":
        result = list_created(args.creator_id, args.chat_id)

    elif args.command == "get":
        result = get_task(args.id)

    elif args.command == "done":
        result = update_status(args.id, "done")

    elif args.command == "start":
        result = update_status(args.id, "in_progress")

    elif args.command == "cancel":
        result = update_status(args.id, "cancelled")

    elif args.command == "extend":
        result = extend_deadline(args.id, args.deadline)

    elif args.command == "edit":
        try:
            updates = json.loads(args.json_data)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}"}))
            sys.exit(1)
        result = edit_task(args.id, updates)

    elif args.command == "stats":
        result = get_stats(args.chat_id, args.period)

    elif args.command == "search":
        result = search_tasks(args.query, args.chat_id)

    elif args.command == "overdue":
        result = get_overdue(args.chat_id)

    elif args.command == "list-by-tag":
        result = list_by_tag(args.tag, args.chat_id)

    elif args.command == "list-tags":
        result = list_tags(args.chat_id)

    else:
        result = {"error": f"Unknown command: {args.command}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
