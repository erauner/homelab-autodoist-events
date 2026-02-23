from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from todoist_core.models import PolicyConfig, PolicyInput, TaskContext
from todoist_core.payloads import build_openclaw_hook_payload, build_openclaw_message
from todoist_core.policy import evaluate_focus_policy

from .config import EventsConfig
from .db import EventsDB
from .todoist_client import TodoistEventsClient


@dataclass
class Action:
    action_type: str
    target_id: str
    target_type: str = "comment"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleContext:
    config: EventsConfig
    db: EventsDB
    todoist: TodoistEventsClient


@dataclass
class TodoistWebhookEvent:
    delivery_id: str
    event_name: str
    user_id: str | None
    triggered_at: str | None
    task_id: str | None
    project_id: str | None
    update_intent: str | None
    reminder_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class Rule(Protocol):
    name: str

    def matches(self, event: TodoistWebhookEvent) -> bool:
        ...

    def plan(self, ctx: RuleContext, event: TodoistWebhookEvent) -> tuple[list[Action], dict[str, Any]]:
        ...


class RecurringClearCommentsOnCompletionRule:
    name = "recurring_clear_comments_on_completion"

    def matches(self, event: TodoistWebhookEvent) -> bool:
        if event.task_id is None:
            return False
        if event.event_name == "item:completed":
            return True
        return event.event_name == "item:updated" and event.update_intent == "item_completed"

    def plan(self, ctx: RuleContext, event: TodoistWebhookEvent) -> tuple[list[Action], dict[str, Any]]:
        if event.task_id is None:
            return [], {"reason": "missing_task_id"}

        task = ctx.todoist.get_task(event.task_id)
        due = task.get("due") or {}
        is_recurring = bool(due.get("is_recurring"))
        if not is_recurring:
            return [], {"reason": "not_recurring", "task_id": event.task_id}

        comments = ctx.todoist.list_comments_for_task(event.task_id)
        keep_markers = tuple(x.lower() for x in ctx.config.keep_markers)

        actions: list[Action] = []
        kept = 0
        for comment in comments:
            comment_id = str(comment.get("id"))
            content = str(comment.get("content") or "").strip().lower()
            if any(content.startswith(marker) for marker in keep_markers):
                kept += 1
                continue
            actions.append(Action(action_type="delete_comment", target_id=comment_id, meta={"task_id": event.task_id}))

        if len(actions) > ctx.config.max_delete_comments:
            actions = actions[: ctx.config.max_delete_comments]
            cap_hit = True
        else:
            cap_hit = False

        return actions, {
            "task_id": event.task_id,
            "is_recurring": True,
            "kept_count": kept,
            "delete_count": len(actions),
            "cap_hit": cap_hit,
            "dry_run": ctx.config.dry_run,
        }


class RecurringPurgeSubtasksOnCompletionRule:
    name = "recurring_purge_subtasks_on_completion"

    def matches(self, event: TodoistWebhookEvent) -> bool:
        if event.task_id is None:
            return False
        if event.event_name == "item:completed":
            return True
        return event.event_name == "item:updated" and event.update_intent == "item_completed"

    @staticmethod
    def _task_id(x: dict[str, Any]) -> str:
        return str(x.get("id") or "")

    @staticmethod
    def _parent_id(x: dict[str, Any]) -> str | None:
        parent = x.get("parent_id")
        if parent is None:
            return None
        parent_s = str(parent).strip()
        if not parent_s:
            return None
        return parent_s

    def plan(self, ctx: RuleContext, event: TodoistWebhookEvent) -> tuple[list[Action], dict[str, Any]]:
        if event.task_id is None:
            return [], {"reason": "missing_task_id"}
        if not event.project_id:
            return [], {"reason": "missing_project_id", "task_id": event.task_id}

        parent_task = ctx.todoist.get_task(event.task_id)
        due = parent_task.get("due") or {}
        is_recurring = bool(due.get("is_recurring"))
        if not is_recurring:
            return [], {"reason": "not_recurring", "task_id": event.task_id}

        tasks = ctx.todoist.list_active_tasks_for_project(event.project_id)
        by_parent: dict[str, list[str]] = {}
        for task in tasks:
            task_id = self._task_id(task)
            if not task_id:
                continue
            parent_id = self._parent_id(task)
            if not parent_id:
                continue
            by_parent.setdefault(parent_id, []).append(task_id)

        descendants: list[str] = []
        stack: list[str] = [event.task_id]
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            for child in by_parent.get(cur, []):
                if child in seen or child == event.task_id:
                    continue
                seen.add(child)
                descendants.append(child)
                stack.append(child)

        # Delete deepest nodes first to avoid parent/child delete ordering issues.
        actions = [Action(action_type="delete_task", target_type="task", target_id=task_id) for task_id in reversed(descendants)]
        if len(actions) > ctx.config.max_delete_subtasks:
            actions = actions[: ctx.config.max_delete_subtasks]
            cap_hit = True
        else:
            cap_hit = False

        return actions, {
            "task_id": event.task_id,
            "is_recurring": True,
            "subtasks_found": len(descendants),
            "delete_count": len(actions),
            "cap_hit": cap_hit,
            "dry_run": ctx.config.dry_run,
        }


class ReminderNotifyRule:
    name = "reminder_notify"

    @staticmethod
    def _parse_due_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except Exception:
            return None

    @staticmethod
    def _parse_due_datetime(value: str | None, tz_name: str) -> datetime | None:
        if not value:
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=ZoneInfo(tz_name))
            return dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            return None

    def matches(self, event: TodoistWebhookEvent) -> bool:
        return event.event_name == "reminder:fired" and event.task_id is not None

    def plan(self, ctx: RuleContext, event: TodoistWebhookEvent) -> tuple[list[Action], dict[str, Any]]:
        if event.task_id is None:
            return [], {"reason": "missing_task_id"}
        if not ctx.config.reminder_webhook_url:
            return [], {"reason": "missing_webhook_url", "task_id": event.task_id}
        if not ctx.config.reminder_webhook_token:
            return [], {"reason": "missing_webhook_token", "task_id": event.task_id}

        task = ctx.todoist.get_task(event.task_id)
        task_content = str(task.get("content") or "").strip()
        due = task.get("due") or {}
        labels = task.get("labels") or []
        labels_lc = {str(x).strip().lower() for x in labels if str(x).strip()}
        has_focus = "focus" in labels_lc
        due_date = self._parse_due_date(str(due.get("date")) if due.get("date") else None)
        due_dt_local = self._parse_due_datetime(
            str(due.get("datetime")) if due.get("datetime") else None,
            ctx.config.reminder_timezone or "America/Chicago",
        )
        task_ctx = TaskContext(
            id=str(event.task_id),
            content=task_content or str(event.task_id),
            labels=tuple(labels_lc),
            project_id=(str(task.get("project_id")) if task.get("project_id") is not None else None),
            due_date=due_date,
            due_datetime_local=due_dt_local,
            url=(str(task.get("url")) if task.get("url") else None),
        )
        try:
            now_local = datetime.now(ZoneInfo(ctx.config.reminder_timezone))
        except Exception:
            now_local = datetime.now(ZoneInfo("America/Chicago"))
        decision = evaluate_focus_policy(
            PolicyInput(
                source="reminder",
                now_local=now_local,
                focus_tasks=(),
                next_action_tasks=(),
                reminder_task=task_ctx,
                config=PolicyConfig(
                    require_focus_for_reminder=ctx.config.reminder_require_focus_label,
                    # Reminder path should not inherit cron allowed-hour gates.
                    allowed_hour_start=0,
                    allowed_hour_end=24,
                ),
            )
        )
        if not decision.should_notify:
            return [], {"reason": decision.reason, "task_id": event.task_id, "mode": decision.mode}

        task_id = str(event.task_id)
        last_sent_ms = ctx.db.get_last_reminder_notify_ms(task_id, decision.mode)
        cooldown_ms = max(0, int(ctx.config.reminder_cooldown_minutes)) * 60_000
        now_ms = int(now_local.timestamp() * 1000)
        if last_sent_ms is not None and cooldown_ms > 0 and (now_ms - last_sent_ms) < cooldown_ms:
            return [], {
                "reason": "cooldown_active",
                "task_id": event.task_id,
                "mode": decision.mode,
                "cooldown_minutes": int(ctx.config.reminder_cooldown_minutes),
                "last_sent_at_ms": last_sent_ms,
            }

        project_id = event.project_id or (str(task.get("project_id")) if task.get("project_id") is not None else None)
        inp = PolicyInput(
            source="reminder",
            now_local=now_local,
            focus_tasks=(task_ctx,),
            next_action_tasks=(),
            reminder_task=task_ctx,
            config=PolicyConfig(
                require_focus_for_reminder=ctx.config.reminder_require_focus_label,
                allowed_hour_start=0,
                allowed_hour_end=24,
            ),
        )
        message_decision = decision
        # Pre-due reminders should steer prep behavior, not pure execution.
        if task_ctx.due_datetime_local is not None and task_ctx.due_datetime_local > now_local:
            message_decision = type(decision)(
                should_notify=decision.should_notify,
                mode="ACTIVE_FOCUS_PREP_WINDOW",
                reason="reminder_before_due_datetime",
                focus_task_id=decision.focus_task_id,
                candidate_task_ids=decision.candidate_task_ids,
            )
        elif task_ctx.due_date is not None and task_ctx.due_date > now_local.date():
            message_decision = type(decision)(
                should_notify=decision.should_notify,
                mode="ACTIVE_FOCUS_PREP_WINDOW",
                reason="reminder_before_due_date",
                focus_task_id=decision.focus_task_id,
                candidate_task_ids=decision.candidate_task_ids,
            )

        message = build_openclaw_message(message_decision, inp)
        target_to = ctx.config.reminder_to or ""
        payload = build_openclaw_hook_payload(
            message=message,
            to=target_to,
            channel=ctx.config.reminder_channel or "discord",
            name="Focus Follow-up",
        )
        payload["meta"] = {
            "source": "autodoist-events-worker",
            "event_name": event.event_name,
            "task_id": event.task_id,
            "project_id": project_id,
            "reminder_id": event.reminder_id,
            "triggered_at": event.triggered_at,
            "policy_mode": decision.mode,
            "policy_reason": decision.reason,
            "message_mode": message_decision.mode,
            "message_reason": message_decision.reason,
        }
        if not target_to:
            payload.pop("to", None)

        action = Action(
            action_type="notify_webhook",
            target_type="webhook",
            target_id=ctx.config.reminder_webhook_url,
            meta={
                "task_id": event.task_id,
                "event_name": event.event_name,
                "policy_mode": decision.mode,
                "message_mode": message_decision.mode,
                "cooldown_minutes": int(ctx.config.reminder_cooldown_minutes),
                "payload": payload,
            },
        )
        return [action], {
            "task_id": event.task_id,
            "reminder_id": event.reminder_id,
            "webhook_url_set": True,
            "has_focus_label": has_focus,
            "policy_mode": decision.mode,
            "policy_reason": decision.reason,
            "message_mode": message_decision.mode,
            "message_reason": message_decision.reason,
            "cooldown_minutes": int(ctx.config.reminder_cooldown_minutes),
            "dry_run": ctx.config.dry_run,
        }


def parse_event(payload: dict[str, Any], delivery_id: str) -> TodoistWebhookEvent:
    event_name = str(payload.get("event_name") or payload.get("eventName") or "")
    event_data = payload.get("event_data") or {}
    event_data_extra = payload.get("event_data_extra") or {}
    if event_name == "reminder:fired":
        task_id = event_data.get("item_id") or event_data.get("id")
    else:
        task_id = event_data.get("id") or event_data.get("item_id")
    project_id = event_data.get("project_id")

    return TodoistWebhookEvent(
        delivery_id=delivery_id,
        event_name=event_name,
        user_id=(str(payload.get("user_id")) if payload.get("user_id") is not None else None),
        triggered_at=payload.get("triggered_at"),
        task_id=(str(task_id) if task_id is not None else None),
        project_id=(str(project_id) if project_id is not None else None),
        update_intent=event_data_extra.get("update_intent"),
        reminder_id=(str(event_data.get("id")) if event_name == "reminder:fired" and event_data.get("id") is not None else None),
        raw=payload,
    )
