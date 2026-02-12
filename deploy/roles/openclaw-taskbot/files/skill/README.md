# Team TaskManager — OpenClaw Skill

A team task management skill for OpenClaw that works through Telegram group chats. Create tasks from natural language (text and voice), assign to team members, track deadlines, and get automatic reminders.

## Features

- **Natural language task creation** — "Подготовить презентацию @ivan до пятницы"
- **User resolution** — fuzzy matching by name, @username, or reply context
- **Deadline tracking** — automatic reminders at 24h, 1h, and at deadline
- **Daily standups** — automated morning reports on weekdays
- **Weekly reviews** — stats, trends, and auto-archival of old tasks
- **Bilingual** — supports Russian and English
- **SQLite storage** — zero external dependencies, Python stdlib only

## Installation

1. Copy the skill to your OpenClaw workspace:
   ```bash
   cp -r team-taskmanager ~/.openclaw/workspace/skills/
   ```

2. Enable in `openclaw.json`:
   ```json
   {
     "skills": {
       "entries": {
         "team-taskmanager": {
           "enabled": true
         }
       }
     }
   }
   ```

3. Initialize the database:
   ```bash
   python3 ~/.openclaw/workspace/skills/team-taskmanager/scripts/init_db.py
   ```

4. The bot will guide you through the rest (timezone, standup schedule, etc.)

## Directory Structure

```
team-taskmanager/
├── SKILL.md                    # Agent instructions (main skill file)
├── scripts/
│   ├── init_db.py              # Database initialization
│   ├── tasks.py                # Task CRUD operations
│   ├── resolve_user.py         # User registration & fuzzy search
│   ├── reminders.py            # Deadline checking
│   ├── standup.py              # Daily standup report
│   └── weekly_review.py        # Weekly review & archival
├── references/
│   ├── task-format.md          # Task data specification
│   └── user-resolution.md      # User resolution rules
├── assets/
│   └── templates/
│       └── TASKS_TEMPLATE.md   # Report templates
├── config/
│   └── config.json             # Skill configuration
└── README.md                   # This file
```

## Scripts CLI Reference

### init_db.py
```bash
python3 scripts/init_db.py
# → {"status": "ok", "db_path": "...", "message": "Database initialized successfully"}
```

### tasks.py
```bash
# Create task
python3 scripts/tasks.py add --json '{"description":"...","creator_id":123,"chat_id":-100}'

# List tasks
python3 scripts/tasks.py list --assignee-id 123 --chat-id -100 --status todo,in_progress

# Get details
python3 scripts/tasks.py get --id 1

# Status changes
python3 scripts/tasks.py done --id 1
python3 scripts/tasks.py start --id 1
python3 scripts/tasks.py cancel --id 1

# Modify
python3 scripts/tasks.py extend --id 1 --deadline "2026-02-20T18:00:00"
python3 scripts/tasks.py edit --id 1 --json '{"description":"updated","priority":"high"}'

# Reports
python3 scripts/tasks.py stats --chat-id -100 --period week
python3 scripts/tasks.py search "презентация" --chat-id -100
python3 scripts/tasks.py overdue --chat-id -100
```

### resolve_user.py
```bash
# Register user
python3 scripts/resolve_user.py upsert --telegram-id 123 --username "ivan" --first-name "Иван" --chat-id -100

# Fuzzy search
python3 scripts/resolve_user.py search "Иван" --chat-id -100

# List users in chat
python3 scripts/resolve_user.py list --chat-id -100
```

### reminders.py
```bash
python3 scripts/reminders.py check-overdue --chat-id -100
python3 scripts/reminders.py upcoming --chat-id -100 --hours 24
```

### standup.py
```bash
python3 scripts/standup.py --chat-id -100
python3 scripts/standup.py --chat-id -100 --format json
```

### weekly_review.py
```bash
python3 scripts/weekly_review.py --chat-id -100
python3 scripts/weekly_review.py --chat-id -100 --archive
```

## Configuration

Edit `config/config.json`:

| Key               | Default        | Description                        |
|--------------------|----------------|------------------------------------|
| timezone           | Europe/Kiev    | Default timezone for cron jobs     |
| language           | auto           | "auto", "ru", or "en"             |
| default_priority   | medium         | Default task priority              |
| fuzzy_threshold    | 0.6            | Minimum similarity for user match  |
| max_suggestions    | 5              | Max user suggestions in fuzzy search |

## Requirements

- Python 3.11+ (uses only stdlib)
- OpenClaw with Telegram gateway configured
- SQLite3 (bundled with Python)
