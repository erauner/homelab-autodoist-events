from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from todoist_core.models import PolicyConfig, PolicyInput, TaskContext
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
        task_desc = str(task.get("description") or "").strip()
        task_url = str(task.get("url") or "").strip()
        labels = task.get("labels") or []
        labels_lc = {str(x).strip().lower() for x in labels if str(x).strip()}
        has_focus = "focus" in labels_lc
        task_ctx = TaskContext(
            id=str(event.task_id),
            content=task_content or str(event.task_id),
            labels=tuple(labels_lc),
            project_id=(str(task.get("project_id")) if task.get("project_id") is not None else None),
        )
        decision = evaluate_focus_policy(
            PolicyInput(
                source="reminder",
                now_local=datetime.now(ZoneInfo("America/Chicago")),
                focus_tasks=(),
                next_action_tasks=(),
                reminder_task=task_ctx,
                # Keep reminder behavior parity with existing implementation:
                # gate by focus requirement only; do not apply quiet-hour window here.
                config=PolicyConfig(
                    require_focus_for_reminder=ctx.config.reminder_require_focus_label,
                    allowed_hour_start=0,
                    allowed_hour_end=24,
                ),
            )
        )
        if not decision.should_notify:
            return [], {"reason": decision.reason, "task_id": event.task_id, "mode": decision.mode}

        project_id = event.project_id or (str(task.get("project_id")) if task.get("project_id") is not None else None)
        subtasks_direct = 0
        if project_id:
            tasks = ctx.todoist.list_active_tasks_for_project(str(project_id))
            subtasks_direct = sum(1 for t in tasks if str(t.get("parent_id") or "") == str(event.task_id))

        comments = ctx.todoist.list_comments_for_task(event.task_id)
        recent_comments = [str(c.get("content") or "").strip() for c in comments if str(c.get("content") or "").strip()]
        recent_comments = recent_comments[-3:]
        comments_block = "\n".join(f"- {c}" for c in recent_comments) if recent_comments else "- (none)"

        message_parts = [
            "Todoist reminder fired.",
            f"Task: {task_content or event.task_id}",
        ]
        if task_desc:
            message_parts.append(f"Description: {task_desc}")
        if labels:
            message_parts.append(f"Labels: {', '.join(str(x) for x in labels)}")
        message_parts.append(f"Direct subtasks open: {subtasks_direct}")
        message_parts.append(f"Recent comments:\n{comments_block}")
        if task_url:
            message_parts.append(f"Task URL: {task_url}")
        message_parts.append("Please provide a concise nudge and next concrete step.")

        payload: dict[str, Any] = {
            "message": "\n".join(message_parts),
            "name": "Todoist Reminder",
            "deliver": True,
            "channel": ctx.config.reminder_channel or "discord",
            "meta": {
                "source": "autodoist-events-worker",
                "event_name": event.event_name,
                "task_id": event.task_id,
                "project_id": project_id,
                "reminder_id": event.reminder_id,
                "triggered_at": event.triggered_at,
            },
        }
        if ctx.config.reminder_to:
            payload["to"] = ctx.config.reminder_to

        action = Action(
            action_type="notify_webhook",
            target_type="webhook",
            target_id=ctx.config.reminder_webhook_url,
            meta={
                "task_id": event.task_id,
                "event_name": event.event_name,
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
            "comments_included": len(recent_comments),
            "direct_subtasks_open": subtasks_direct,
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
