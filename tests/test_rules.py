from autodoist_events_worker.config import EventsConfig
from autodoist_events_worker.rules import RecurringClearCommentsOnCompletionRule, RuleContext, TodoistWebhookEvent


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
