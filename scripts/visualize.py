#!/usr/bin/env python3
"""Generate task visualization charts as PNG images."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta

DB_PATH = os.path.expanduser("~/.openclaw/workspace/data/taskmanager.db")
OUTPUT_DIR = os.path.expanduser("~/.openclaw/workspace/data/charts")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def chart_status_overview(chat_id=None):
    """Pie chart: task distribution by status."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    conn = get_connection()
    cur = conn.cursor()

    where = f" WHERE chat_id = {chat_id}" if chat_id else ""
    cur.execute(f"""
        SELECT status, COUNT(*) as cnt
        FROM tasks{where}
        GROUP BY status
        ORDER BY cnt DESC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return {"error": "No tasks found"}

    labels = []
    sizes = []
    colors_map = {
        "todo": "#3498db",
        "in_progress": "#f39c12",
        "done": "#2ecc71",
        "cancelled": "#95a5a6",
        "overdue": "#e74c3c",
    }
    label_map = {
        "todo": "To Do",
        "in_progress": "In Progress",
        "done": "Done",
        "cancelled": "Cancelled",
        "overdue": "Overdue",
    }
    colors = []

    for r in rows:
        labels.append(label_map.get(r["status"], r["status"]))
        sizes.append(r["cnt"])
        colors.append(colors_map.get(r["status"], "#bdc3c7"))

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors, autopct="%1.0f%%",
        startangle=90, textprops={"fontsize": 13, "fontweight": "bold"},
    )
    for t in autotexts:
        t.set_fontsize(12)
        t.set_color("white")
        t.set_fontweight("bold")
    ax.set_title("Task Status Overview", fontsize=16, fontweight="bold", pad=20)

    total = sum(sizes)
    ax.text(0, -1.35, f"Total: {total} tasks", ha="center", fontsize=12, color="#555")

    ensure_output_dir()
    path = os.path.join(OUTPUT_DIR, "status_overview.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return {"status": "ok", "chart": "status_overview", "path": path}


def chart_assignee_workload(chat_id=None):
    """Horizontal bar chart: tasks per assignee."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    conn = get_connection()
    cur = conn.cursor()

    conditions = ["status IN ('todo','in_progress','overdue')"]
    params = []
    if chat_id:
        conditions.append("chat_id = ?")
        params.append(chat_id)

    where = " WHERE " + " AND ".join(conditions)
    cur.execute(f"""
        SELECT COALESCE(assignee_username, 'unassigned') as assignee,
               SUM(CASE WHEN status = 'todo' THEN 1 ELSE 0 END) as todo,
               SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
               SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) as overdue
        FROM tasks{where}
        GROUP BY assignee_id
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """, params)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return {"error": "No active tasks found"}

    assignees = [f"@{r['assignee']}" for r in rows]
    todo = [r["todo"] for r in rows]
    in_prog = [r["in_progress"] for r in rows]
    overdue = [r["overdue"] for r in rows]

    fig, ax = plt.subplots(figsize=(10, max(4, len(assignees) * 0.8 + 2)))

    y = range(len(assignees))
    bar_height = 0.6

    bars1 = ax.barh(y, overdue, bar_height, label="Overdue", color="#e74c3c")
    bars2 = ax.barh(y, in_prog, bar_height, left=overdue, label="In Progress", color="#f39c12")
    bars3 = ax.barh(y, todo, bar_height,
                    left=[o + i for o, i in zip(overdue, in_prog)],
                    label="To Do", color="#3498db")

    ax.set_yticks(y)
    ax.set_yticklabels(assignees, fontsize=12)
    ax.invert_yaxis()
    ax.set_xlabel("Tasks", fontsize=12)
    ax.set_title("Workload by Assignee", fontsize=16, fontweight="bold", pad=15)
    ax.legend(loc="lower right", fontsize=10)
    ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    ensure_output_dir()
    path = os.path.join(OUTPUT_DIR, "assignee_workload.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return {"status": "ok", "chart": "assignee_workload", "path": path}


def chart_weekly_trend(chat_id=None, weeks=4):
    """Line chart: tasks created vs completed over recent weeks."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now(UTC)

    created_by_day = {}
    done_by_day = {}

    for i in range(weeks * 7):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        created_by_day[day] = 0
        done_by_day[day] = 0

    start_date = (now - timedelta(days=weeks * 7)).strftime("%Y-%m-%dT00:00:00")

    conditions = ["created_at >= ?"]
    params = [start_date]
    if chat_id:
        conditions.append("chat_id = ?")
        params.append(chat_id)
    where = " WHERE " + " AND ".join(conditions)

    cur.execute(f"SELECT DATE(created_at) as d, COUNT(*) as cnt FROM tasks{where} GROUP BY d", params)
    for r in cur.fetchall():
        if r["d"] in created_by_day:
            created_by_day[r["d"]] = r["cnt"]

    conditions2 = ["completed_at >= ?", "status = 'done'"]
    params2 = [start_date]
    if chat_id:
        conditions2.append("chat_id = ?")
        params2.append(chat_id)
    where2 = " WHERE " + " AND ".join(conditions2)

    cur.execute(f"SELECT DATE(completed_at) as d, COUNT(*) as cnt FROM tasks{where2} GROUP BY d", params2)
    for r in cur.fetchall():
        if r["d"] in done_by_day:
            done_by_day[r["d"]] = r["cnt"]

    conn.close()

    days = sorted(created_by_day.keys())
    created_vals = [created_by_day[d] for d in days]
    done_vals = [done_by_day[d] for d in days]

    dates = [datetime.strptime(d, "%Y-%m-%d") for d in days]

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.fill_between(dates, created_vals, alpha=0.3, color="#3498db")
    ax.plot(dates, created_vals, "o-", color="#3498db", label="Created", linewidth=2, markersize=4)
    ax.fill_between(dates, done_vals, alpha=0.3, color="#2ecc71")
    ax.plot(dates, done_vals, "o-", color="#2ecc71", label="Completed", linewidth=2, markersize=4)

    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))

    ax.set_title(f"Task Trend (last {weeks} weeks)", fontsize=16, fontweight="bold", pad=15)
    ax.set_ylabel("Tasks", fontsize=12)
    ax.legend(fontsize=11)
    ax.grid(axis="y", alpha=0.3)

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    fig.autofmt_xdate()

    ensure_output_dir()
    path = os.path.join(OUTPUT_DIR, "weekly_trend.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return {"status": "ok", "chart": "weekly_trend", "path": path}


def chart_priority_breakdown(chat_id=None):
    """Bar chart: active tasks grouped by priority."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    conn = get_connection()
    cur = conn.cursor()

    conditions = ["status IN ('todo','in_progress','overdue')"]
    params = []
    if chat_id:
        conditions.append("chat_id = ?")
        params.append(chat_id)
    where = " WHERE " + " AND ".join(conditions)

    cur.execute(f"""
        SELECT priority, COUNT(*) as cnt
        FROM tasks{where}
        GROUP BY priority
    """, params)
    rows = {r["priority"]: r["cnt"] for r in cur.fetchall()}
    conn.close()

    priorities = ["high", "medium", "low"]
    labels = ["HIGH", "MEDIUM", "LOW"]
    colors = ["#e74c3c", "#f39c12", "#2ecc71"]
    values = [rows.get(p, 0) for p in priorities]

    if sum(values) == 0:
        return {"error": "No active tasks found"}

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=colors, width=0.5, edgecolor="white", linewidth=2)

    for bar, val in zip(bars, values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                    str(val), ha="center", fontsize=14, fontweight="bold")

    ax.set_title("Active Tasks by Priority", fontsize=16, fontweight="bold", pad=15)
    ax.set_ylabel("Tasks", fontsize=12)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    ensure_output_dir()
    path = os.path.join(OUTPUT_DIR, "priority_breakdown.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return {"status": "ok", "chart": "priority_breakdown", "path": path}


def chart_dashboard(chat_id=None):
    """Generate all charts and return paths."""
    results = {}
    for name, func in [
        ("status_overview", chart_status_overview),
        ("assignee_workload", chart_assignee_workload),
        ("priority_breakdown", chart_priority_breakdown),
        ("weekly_trend", chart_weekly_trend),
    ]:
        try:
            results[name] = func(chat_id)
        except Exception as e:
            results[name] = {"error": str(e)}

    paths = [r["path"] for r in results.values() if "path" in r]
    return {"status": "ok", "charts": results, "paths": paths}


def main():
    parser = argparse.ArgumentParser(description="Task visualization charts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for cmd in ["status", "workload", "priority", "trend", "dashboard"]:
        p = subparsers.add_parser(cmd)
        p.add_argument("--chat-id", type=int, default=None)
        p.add_argument("--assignee-id", type=int, default=None)
        if cmd == "trend":
            p.add_argument("--weeks", type=int, default=4)

    args = parser.parse_args()

    if args.command == "status":
        result = chart_status_overview(args.chat_id)
    elif args.command == "workload":
        result = chart_assignee_workload(args.chat_id)
    elif args.command == "priority":
        result = chart_priority_breakdown(args.chat_id)
    elif args.command == "trend":
        result = chart_weekly_trend(args.chat_id, args.weeks)
    elif args.command == "dashboard":
        result = chart_dashboard(args.chat_id)
    else:
        result = {"error": f"Unknown command: {args.command}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
