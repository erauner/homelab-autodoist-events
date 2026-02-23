# homelab-autodoist-events

Standalone Todoist webhook events worker for Autodoist automations.

## Why this is separate

This repository isolates webhook/event processing from `homelab-autodoist`'s polling loop.
It keeps runtime boundaries clean while still allowing shared code with:

- `homelab-autodoist`
- `homelab-todoist-cli`

Shared primitives live in `src/todoist_automation_shared/` and can later be split to a dedicated shared package if needed.

## Features

- Todoist webhook ingestion (`POST /hooks/todoist`)
- HMAC verification via `X-Todoist-Hmac-SHA256`
- Idempotency using `X-Todoist-Delivery-ID`
- Auditable ledger in dedicated SQLite (`events.sqlite`)
- Pluggable rule engine
- POC rule: recurring completion clears comments (with keep markers)

## Run

```bash
export TODOIST_API_KEY="..."
export TODOIST_CLIENT_SECRET="..."
autodoist-events --host 0.0.0.0 --port 8081
```

## Config

Environment variables:

- `TODOIST_API_KEY` (required)
- `TODOIST_CLIENT_SECRET` (required)
- `AUTODOIST_EVENTS_DB_PATH` (default: `events.sqlite`)
- `AUTODOIST_EVENTS_ENABLED` (default: `true`)
- `AUTODOIST_EVENTS_DRY_RUN` (default: `false`)
- `AUTODOIST_EVENTS_RULE_RECURRING_CLEAR_COMMENTS` (default: `true`)
- `AUTODOIST_EVENTS_ALLOWED_USER_IDS` (CSV, optional)
- `AUTODOIST_EVENTS_ALLOWED_PROJECT_IDS` (CSV, optional)
- `AUTODOIST_EVENTS_DENIED_PROJECT_IDS` (CSV, optional)
- `AUTODOIST_EVENTS_KEEP_MARKERS` (CSV, default: `[openclaw:plan]`)
- `AUTODOIST_EVENTS_MAX_DELETE_COMMENTS` (default: `200`)
- `AUTODOIST_EVENTS_RULE_REMINDER_NOTIFY` (default: `false`)
- `AUTODOIST_EVENTS_REMINDER_WEBHOOK_URL` (required for reminder notify)
- `AUTODOIST_EVENTS_REMINDER_WEBHOOK_TOKEN` (required for reminder notify)
- `AUTODOIST_EVENTS_REMINDER_CHANNEL` (default: `discord`)
- `AUTODOIST_EVENTS_REMINDER_TO` (optional destination override)
- `AUTODOIST_EVENTS_REMINDER_REQUIRE_FOCUS_LABEL` (default: `false`)
- `AUTODOIST_EVENTS_REMINDER_COOLDOWN_MINUTES` (default: `60`)
- `AUTODOIST_EVENTS_REMINDER_TIMEZONE` (default: `America/Chicago`)
- `AUTODOIST_EVENTS_ALLOWED_HOUR_START` (default: `9`)
- `AUTODOIST_EVENTS_ALLOWED_HOUR_END` (default: `18`)
- `AUTODOIST_EVENTS_ADMIN_TOKEN` (optional)

## Endpoints

- `GET /health`
- `POST /hooks/todoist`
- `GET /api/events` (admin token required)
- `GET /api/events/<delivery_id>` (admin token required)
