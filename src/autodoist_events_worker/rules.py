from dataclasses import dataclass, field
from typing import Any, Protocol

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
    raw: dict[str, Any]


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


def parse_event(payload: dict[str, Any], delivery_id: str) -> TodoistWebhookEvent:
    event_name = str(payload.get("event_name") or payload.get("eventName") or "")
    event_data = payload.get("event_data") or {}
    event_data_extra = payload.get("event_data_extra") or {}
    task_id = event_data.get("id")
    project_id = event_data.get("project_id")

    return TodoistWebhookEvent(
        delivery_id=delivery_id,
        event_name=event_name,
        user_id=(str(payload.get("user_id")) if payload.get("user_id") is not None else None),
        triggered_at=payload.get("triggered_at"),
        task_id=(str(task_id) if task_id is not None else None),
        project_id=(str(project_id) if project_id is not None else None),
        update_intent=event_data_extra.get("update_intent"),
        raw=payload,
    )
