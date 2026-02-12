#!/usr/bin/env python3
"""User resolution: register users from Telegram messages and fuzzy-search by name."""

import argparse
import difflib
import json
import os
import sqlite3
import sys

DB_PATH = os.path.expanduser("~/.openclaw/workspace/data/taskmanager.db")
CONFIG_PATH = os.path.expanduser(
    "~/.openclaw/workspace/skills/team-taskmanager/config/config.json"
)

DEFAULT_THRESHOLD = 0.6
DEFAULT_MAX_SUGGESTIONS = 5


def get_config():
    """Load config, returning defaults if file missing."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def user_row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict."""
    d = dict(row)
    if "chat_ids" in d and isinstance(d["chat_ids"], str):
        try:
            d["chat_ids"] = json.loads(d["chat_ids"])
        except json.JSONDecodeError:
            d["chat_ids"] = []
    return d


def upsert_user(telegram_id, username, first_name, last_name, chat_id):
    """Register or update a user. Called on every incoming message."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT chat_ids FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()

    if row:
        try:
            chat_ids = json.loads(row["chat_ids"])
        except (json.JSONDecodeError, TypeError):
            chat_ids = []
        if chat_id and chat_id not in chat_ids:
            chat_ids.append(chat_id)

        cur.execute(
            """UPDATE users
               SET username = COALESCE(?, username),
                   first_name = COALESCE(?, first_name),
                   last_name = COALESCE(?, last_name),
                   chat_ids = ?,
                   last_seen_at = datetime('now')
               WHERE telegram_id = ?""",
            (username, first_name, last_name, json.dumps(chat_ids), telegram_id),
        )
    else:
        chat_ids = [chat_id] if chat_id else []
        cur.execute(
            """INSERT INTO users (telegram_id, username, first_name, last_name, chat_ids)
               VALUES (?, ?, ?, ?, ?)""",
            (telegram_id, username, first_name, last_name, json.dumps(chat_ids)),
        )

    conn.commit()

    cur.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = user_row_to_dict(cur.fetchone())
    conn.close()

    return {"status": "ok", "user": user}


def search_user(query, chat_id=None):
    """Fuzzy search for a user by name or username."""
    conn = get_connection()
    cur = conn.cursor()

    query_lower = query.lower().strip().lstrip("@")

    # First try exact username match
    cur.execute(
        "SELECT * FROM users WHERE LOWER(username) = ?", (query_lower,)
    )
    exact = cur.fetchone()
    if exact:
        user = user_row_to_dict(exact)
        if chat_id is None or chat_id in user.get("chat_ids", []):
            conn.close()
            return {"status": "EXACT_MATCH", "user": user}

    # Fetch all users (optionally filtered by chat)
    if chat_id:
        cur.execute("SELECT * FROM users")
        all_users = [
            user_row_to_dict(r)
            for r in cur.fetchall()
            if chat_id in (json.loads(r["chat_ids"]) if isinstance(r["chat_ids"], str) else r["chat_ids"])
        ]
    else:
        cur.execute("SELECT * FROM users")
        all_users = [user_row_to_dict(r) for r in cur.fetchall()]

    conn.close()

    if not all_users:
        return {"status": "NOT_FOUND", "query": query, "users": []}

    config = get_config()
    threshold = config.get("fuzzy_threshold", DEFAULT_THRESHOLD)
    max_suggestions = config.get("max_suggestions", DEFAULT_MAX_SUGGESTIONS)

    scored = []
    for user in all_users:
        candidates = []
        if user.get("username"):
            candidates.append(user["username"].lower())
        if user.get("first_name"):
            candidates.append(user["first_name"].lower())
        if user.get("last_name"):
            candidates.append(user["last_name"].lower())
        if user.get("first_name") and user.get("last_name"):
            candidates.append(f"{user['first_name']} {user['last_name']}".lower())
        if user.get("display_name"):
            candidates.append(user["display_name"].lower())

        best_score = 0.0
        for c in candidates:
            score = difflib.SequenceMatcher(None, query_lower, c).ratio()
            if score > best_score:
                best_score = score

        if best_score >= threshold:
            scored.append((best_score, user))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        return {"status": "NOT_FOUND", "query": query, "users": []}

    if scored[0][0] >= 0.95:
        return {"status": "EXACT_MATCH", "user": scored[0][1]}

    suggestions = [
        {**u, "match_score": round(s, 3)} for s, u in scored[:max_suggestions]
    ]
    return {"status": "SUGGESTIONS", "users": suggestions}


def list_users(chat_id=None):
    """List all known users, optionally filtered by chat."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY last_seen_at DESC")
    rows = cur.fetchall()
    conn.close()

    users = []
    for r in rows:
        user = user_row_to_dict(r)
        if chat_id is None or chat_id in user.get("chat_ids", []):
            users.append(user)

    return {"status": "ok", "count": len(users), "users": users}


def get_user(telegram_id):
    """Get a specific user by telegram_id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()
    conn.close()

    if row:
        return {"status": "ok", "user": user_row_to_dict(row)}
    return {"error": f"User with telegram_id {telegram_id} not found"}


def main():
    parser = argparse.ArgumentParser(description="User resolution for TaskManager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # upsert
    p_upsert = subparsers.add_parser("upsert", help="Register or update a user")
    p_upsert.add_argument("--telegram-id", type=int, required=True)
    p_upsert.add_argument("--username", type=str, default=None)
    p_upsert.add_argument("--first-name", type=str, default=None)
    p_upsert.add_argument("--last-name", type=str, default=None)
    p_upsert.add_argument("--chat-id", type=int, default=None)

    # search
    p_search = subparsers.add_parser("search", help="Fuzzy search for a user")
    p_search.add_argument("query", type=str)
    p_search.add_argument("--chat-id", type=int, default=None)

    # list
    p_list = subparsers.add_parser("list", help="List all known users")
    p_list.add_argument("--chat-id", type=int, default=None)

    # get
    p_get = subparsers.add_parser("get", help="Get a user by telegram_id")
    p_get.add_argument("--telegram-id", type=int, required=True)

    args = parser.parse_args()

    if args.command == "upsert":
        result = upsert_user(
            args.telegram_id, args.username, args.first_name, args.last_name, args.chat_id
        )
    elif args.command == "search":
        result = search_user(args.query, args.chat_id)
    elif args.command == "list":
        result = list_users(args.chat_id)
    elif args.command == "get":
        result = get_user(args.telegram_id)
    else:
        result = {"error": f"Unknown command: {args.command}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
