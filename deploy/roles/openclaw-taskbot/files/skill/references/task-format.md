# Task Format Specification

## Task Object (JSON)

```json
{
  "id": 1,
  "description": "Подготовить презентацию для клиента",
  "title": "Презентация",
  "creator_id": 123456789,
  "creator_username": "sergey",
  "assignee_id": 987654321,
  "assignee_username": "ivan_petrov",
  "chat_id": -100123456789,
  "deadline": "2026-02-15T18:00:00",
  "priority": "high",
  "status": "todo",
  "cron_job_ids": ["task-1-24h", "task-1-1h", "task-1-due"],
  "created_at": "2026-02-10T10:30:00",
  "updated_at": "2026-02-10T10:30:00",
  "completed_at": null
}
```

## Fields

| Field              | Type    | Required | Description                                      |
|--------------------|---------|----------|--------------------------------------------------|
| id                 | int     | auto     | Auto-incrementing primary key                    |
| description        | string  | YES      | Full task description                            |
| title              | string  | no       | Short title (agent-generated)                    |
| creator_id         | int     | YES      | Telegram user ID of task creator                 |
| creator_username   | string  | no       | Creator's @username                              |
| assignee_id        | int     | no       | Telegram user ID of assignee                     |
| assignee_username  | string  | no       | Assignee's @username                             |
| chat_id            | int     | YES      | Telegram chat ID (scoping)                       |
| deadline           | string  | no       | ISO 8601 datetime or null                        |
| priority           | enum    | no       | "low", "medium" (default), "high"                |
| status             | enum    | no       | "todo" (default), "in_progress", "done", "cancelled", "overdue" |
| cron_job_ids       | array   | no       | Names of scheduled cron reminder jobs            |
| created_at         | string  | auto     | ISO 8601 creation timestamp                      |
| updated_at         | string  | auto     | ISO 8601 last update timestamp                   |
| completed_at       | string  | no       | ISO 8601 completion timestamp (when done)        |

## Status Transitions

```
todo → in_progress → done
todo → cancelled
todo → overdue (automatic, when deadline passes)
in_progress → done
in_progress → cancelled
in_progress → overdue (automatic)
overdue → in_progress (user resumes work)
overdue → done (user completes it)
overdue → cancelled
overdue → todo (when deadline is extended)
```

## Priority Levels

| Priority | Emoji | Sort Order |
|----------|-------|------------|
| high     | 🔴    | 0 (first)  |
| medium   | 🟡    | 1          |
| low      | 🟢    | 2 (last)   |

## Deadline Format

All deadlines are stored in ISO 8601 format: `YYYY-MM-DDTHH:MM:SS`

When no time is specified, default to 23:59:00 of the given date.
