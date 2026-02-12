# Task Report Template

## Daily Standup

📊 **Ежедневный отчёт** — {date}

🔴 **Просрочено ({overdue_count}):**
  #{id} {description} — @{assignee} (просрочено на {overdue_duration})

⏰ **Дедлайн сегодня ({due_today_count}):**
  #{id} {description} — @{assignee} (до {deadline_time})

🔄 **В работе ({in_progress_count}):**
  {priority_emoji} #{id} {description} — @{assignee}

📈 Выполнено вчера: {done_yesterday_count} задач

---

## Weekly Review

📋 **Еженедельный обзор** — {week_start} — {week_end}

📊 **Статистика за неделю:**
  ✅ Создано: {created_count} {trend} (прошлая: {prev_created})
  ✅ Выполнено: {done_count} {trend} (прошлая: {prev_done})
  ❌ Отменено: {cancelled_count}

📈 **Текущее состояние:**
  🔄 Активные задачи: {active_count}
  🔴 Просрочено: {overdue_count}

🏆 **Топ участников (выполнено):**
  🥇 @{username} — {count} задач
  🥈 @{username} — {count} задач
  🥉 @{username} — {count} задач

🎯 Completion rate: {rate}%

---

## Task Confirmation

✅ Задача #{id} создана
📝 {description}
👤 Исполнитель: @{assignee}
📅 Дедлайн: {deadline}
{priority_emoji} Приоритет: {priority}

---

## Task List

📋 **Задачи для @{username}** ({active_count} активных)

{priority_emoji} #{id} {description} — до {deadline}

✅ Выполнено за неделю: {done_week_count}
⏰ Просрочено: {overdue_count}
