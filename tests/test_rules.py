from autodoist_events_worker.config import EventsConfig
from autodoist_events_worker.rules import (
    ReminderNotifyRule,
    RecurringClearCommentsOnCompletionRule,
    RecurringPurgeSubtasksOnCompletionRule,
    RuleContext,
    TodoistWebhookEvent,
    parse_event,
)


class FakeTodoist:
    def __init__(self, recurring: bool = True, labels: list[str] | None = None) -> None:
        self.recurring = recurring
        self.labels = labels if labels is not None else ["focus"]

    def get_task(self, task_id: str):
        return {
            "id": task_id,
            "content": "Focus task",
            "description": "desc",
            "url": f"https://app.todoist.com/app/task/{task_id}",
            "labels": self.labels,
            "project_id": "p1",
            "due": {"is_recurring": self.recurring},
        }

    def list_comments_for_task(self, task_id: str):
        return [
            {"id": "1", "content": "[openclaw:plan] keep this"},
            {"id": "2", "content": "delete me"},
        ]

    def list_active_tasks_for_project(self, project_id: str):
        return [
            {"id": "parent", "project_id": project_id, "parent_id": None},
            {"id": "c1", "project_id": project_id, "parent_id": "parent"},
            {"id": "c2", "project_id": project_id, "parent_id": "parent"},
            {"id": "gc1", "project_id": project_id, "parent_id": "c1"},
        ]


class FakeDB:
    pass


def _config() -> EventsConfig:
    return EventsConfig(todoist_api_token="x", webhook_client_secret="y")


def test_rule_matches_item_completed() -> None:
    rule = RecurringClearCommentsOnCompletionRule()
    event = TodoistWebhookEvent(
        delivery_id="d1",
        event_name="item:completed",
        user_id="u1",
        triggered_at=None,
        task_id="t1",
        project_id="p1",
        update_intent=None,
        raw={},
    )
    assert rule.matches(event)


def test_rule_matches_item_updated_intent() -> None:
    rule = RecurringClearCommentsOnCompletionRule()
    event = TodoistWebhookEvent(
        delivery_id="d1",
        event_name="item:updated",
        user_id="u1",
        triggered_at=None,
        task_id="t1",
        project_id="p1",
        update_intent="item_completed",
        raw={},
    )
    assert rule.matches(event)


def test_rule_plan_keeps_markers_and_deletes_others() -> None:
    rule = RecurringClearCommentsOnCompletionRule()
    ctx = RuleContext(config=_config(), db=FakeDB(), todoist=FakeTodoist(recurring=True))
    event = TodoistWebhookEvent(
        delivery_id="d1",
        event_name="item:completed",
        user_id="u1",
        triggered_at=None,
        task_id="t1",
        project_id="p1",
        update_intent=None,
        raw={},
    )
    actions, meta = rule.plan(ctx, event)
    assert len(actions) == 1
    assert actions[0].target_id == "2"
    assert meta["kept_count"] == 1


def test_subtask_rule_plans_recursive_deletes() -> None:
    rule = RecurringPurgeSubtasksOnCompletionRule()
    cfg = _config()
    ctx = RuleContext(config=cfg, db=FakeDB(), todoist=FakeTodoist(recurring=True))
    event = TodoistWebhookEvent(
        delivery_id="d1",
        event_name="item:completed",
        user_id="u1",
        triggered_at=None,
        task_id="parent",
        project_id="p1",
        update_intent="item_completed",
        raw={},
    )
    actions, meta = rule.plan(ctx, event)
    assert len(actions) == 3
    assert sorted(a.target_id for a in actions) == ["c1", "c2", "gc1"]
    assert all(a.action_type == "delete_task" for a in actions)
    assert meta["subtasks_found"] == 3
    assert meta["delete_count"] == 3


def test_subtask_rule_respects_cap() -> None:
    rule = RecurringPurgeSubtasksOnCompletionRule()
    cfg = _config()
    cfg = EventsConfig(
        todoist_api_token=cfg.todoist_api_token,
        webhook_client_secret=cfg.webhook_client_secret,
        max_delete_subtasks=2,
    )
    ctx = RuleContext(config=cfg, db=FakeDB(), todoist=FakeTodoist(recurring=True))
    event = TodoistWebhookEvent(
        delivery_id="d1",
        event_name="item:completed",
        user_id="u1",
        triggered_at=None,
        task_id="parent",
        project_id="p1",
        update_intent="item_completed",
        raw={},
    )
    actions, meta = rule.plan(ctx, event)
    assert len(actions) == 2
    assert meta["cap_hit"] is True


def test_parse_event_reminder_uses_item_id_for_task() -> None:
    payload = {
        "event_name": "reminder:fired",
        "event_data": {"id": "rem-1", "item_id": "task-9", "project_id": "p1"},
        "user_id": 123,
    }
    event = parse_event(payload, "d1")
    assert event.event_name == "reminder:fired"
    assert event.task_id == "task-9"
    assert event.reminder_id == "rem-1"


def test_reminder_rule_plans_webhook_notification() -> None:
    rule = ReminderNotifyRule()
    cfg = EventsConfig(
        todoist_api_token="x",
        webhook_client_secret="y",
        reminder_webhook_url="http://openclaw-main.ai.svc.cluster.local:18789/hooks/agent",
        reminder_webhook_token="token",
        reminder_channel="discord",
        reminder_to="user:123",
    )
    ctx = RuleContext(config=cfg, db=FakeDB(), todoist=FakeTodoist(recurring=True))
    event = TodoistWebhookEvent(
        delivery_id="d1",
        event_name="reminder:fired",
        user_id="u1",
        triggered_at="2026-02-23T01:00:00Z",
        task_id="parent",
        project_id="p1",
        update_intent=None,
        reminder_id="rem-1",
    )

    assert rule.matches(event)
    actions, meta = rule.plan(ctx, event)
    assert len(actions) == 1
    assert actions[0].action_type == "notify_webhook"
    assert actions[0].target_type == "webhook"
    assert "payload" in actions[0].meta
    payload = actions[0].meta["payload"]
    assert payload["channel"] == "discord"
    assert payload["to"] == "user:123"
    assert "Todoist reminder fired" in payload["message"]
    assert meta["reminder_id"] == "rem-1"
    assert meta["policy_mode"] == "REMINDER_FOCUS"
    assert meta["policy_reason"] == "focused_reminder_task"


def test_reminder_rule_skips_when_token_missing() -> None:
    rule = ReminderNotifyRule()
    cfg = EventsConfig(
        todoist_api_token="x",
        webhook_client_secret="y",
        reminder_webhook_url="http://openclaw-main.ai.svc.cluster.local:18789/hooks/agent",
    )
    ctx = RuleContext(config=cfg, db=FakeDB(), todoist=FakeTodoist(recurring=True))
    event = TodoistWebhookEvent(
        delivery_id="d1",
        event_name="reminder:fired",
        user_id="u1",
        triggered_at="2026-02-23T01:00:00Z",
        task_id="parent",
        project_id="p1",
        update_intent=None,
        reminder_id="rem-1",
    )
    actions, meta = rule.plan(ctx, event)
    assert actions == []
    assert meta["reason"] == "missing_webhook_token"


def test_reminder_rule_skips_without_focus_when_required() -> None:
    rule = ReminderNotifyRule()
    cfg = EventsConfig(
        todoist_api_token="x",
        webhook_client_secret="y",
        reminder_webhook_url="http://openclaw-main.ai.svc.cluster.local:18789/hooks/agent",
        reminder_webhook_token="token",
        reminder_require_focus_label=True,
    )
    ctx = RuleContext(config=cfg, db=FakeDB(), todoist=FakeTodoist(recurring=True, labels=[]))
    event = TodoistWebhookEvent(
        delivery_id="d1",
        event_name="reminder:fired",
        user_id="u1",
        triggered_at="2026-02-23T01:00:00Z",
        task_id="parent",
        project_id="p1",
        update_intent=None,
        reminder_id="rem-1",
    )
    actions, meta = rule.plan(ctx, event)
    assert actions == []
    assert meta["reason"] == "reminder_task_not_focused"
