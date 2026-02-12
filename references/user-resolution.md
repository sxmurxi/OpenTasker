# User Resolution Rules

## How Users Are Tracked

Every time a message is received in a chat where the bot operates, the sender's info is recorded via `resolve_user.py upsert`. This builds a registry of known users per chat.

## Resolution Priority

When an assignee is mentioned in a task, resolve in this order:

1. **@username** — Direct match. Search the database for this exact username.
2. **Name mention** — "для Ивана", "Anna should do this". Run fuzzy search.
3. **Reply context** — Message is a reply to another user. Assignee = replied-to user.
4. **Self-assign** — No assignee mentioned. Assign to message author.

## Fuzzy Matching Algorithm

Uses `difflib.SequenceMatcher` from Python stdlib.

### Search targets per user:
- `username` (without @)
- `first_name`
- `last_name`
- `"{first_name} {last_name}"` (full name)
- `display_name` (custom name if set)

### Process:
1. Normalize query: lowercase, strip whitespace, remove leading @
2. For each user in the chat, compute similarity score against all targets
3. Take the maximum score for each user
4. Filter: score >= threshold (default 0.6)
5. Sort by score descending
6. Return top N results (default 5)

### Result Types:

| Status       | Condition                    | Action                     |
|--------------|------------------------------|----------------------------|
| EXACT_MATCH  | Score >= 0.95 or exact username | Use this user directly     |
| SUGGESTIONS  | Multiple users above threshold | Present options to user    |
| NOT_FOUND    | No users above threshold     | Ask for explicit @username |

## User Object

```json
{
  "telegram_id": 123456789,
  "username": "ivan_petrov",
  "first_name": "Иван",
  "last_name": "Петров",
  "display_name": null,
  "chat_ids": [-100123456789, -100987654321],
  "first_seen_at": "2026-02-10T10:00:00",
  "last_seen_at": "2026-02-10T15:30:00"
}
```

## Edge Cases

- **Username changed:** telegram_id is the primary key, username is updated on every message
- **User in multiple chats:** chat_ids array tracks all chats where user was seen
- **Cyrillic names:** fuzzy matching works correctly with Unicode strings
- **Partial names:** "Ваня" may match "Иван" with lower score — threshold handles this
- **Same name, different users:** SUGGESTIONS result lets the user disambiguate
