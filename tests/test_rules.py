from autodoist_events_worker.config import EventsConfig
from autodoist_events_worker.rules import (
    RecurringClearCommentsOnCompletionRule,
    RecurringPurgeSubtasksOnCompletionRule,
    RuleContext,
    TodoistWebhookEvent,
)


class FakeTodoist:
    def __init__(self, recurring: bool = True) -> None:
        self.recurring = recurring

    def get_task(self, task_id: str):
        return {"id": task_id, "due": {"is_recurring": self.recurring}}

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
