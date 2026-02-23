from todoist_core.models import PolicyDecision

from autodoist_events_worker.config import EventsConfig
from autodoist_events_worker.service import create_app
from autodoist_events_worker.todoist_client import TodoistEventsClient


def _cfg(tmp_path) -> EventsConfig:
    return EventsConfig(
        todoist_api_token="token",
        webhook_client_secret="secret",
        db_path=str(tmp_path / "events.sqlite"),
        internal_token="internal-token",
        reminder_webhook_url="http://openclaw-main.ai.svc.cluster.local:18789/hooks/agent",
        reminder_webhook_token="hook-token",
        reminder_to="user:123",
    )


def test_internal_trigger_requires_auth(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(TodoistEventsClient, "list_all_active_tasks", lambda self: [])
    app = create_app(_cfg(tmp_path))
    client = app.test_client()

    resp = client.post("/internal/trigger", json={"source": "cron_fallback"})
    assert resp.status_code == 401
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["error"] == "unauthorized"


def test_internal_trigger_skip_decision(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(TodoistEventsClient, "list_all_active_tasks", lambda self: [])
    monkeypatch.setattr(
        "autodoist_events_worker.service.evaluate_focus_policy",
        lambda inp: PolicyDecision(False, "SKIP", "no_focus_not_tether_slot"),
    )
    app = create_app(_cfg(tmp_path))
    client = app.test_client()

    resp = client.post(
        "/internal/trigger",
        headers={"Authorization": "Bearer internal-token"},
        json={"source": "cron_fallback", "deliver": True},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["decision"]["should_notify"] is False
    assert payload["decision"]["reason"] == "no_focus_not_tether_slot"
    assert payload["delivery"]["sent"] is False
    assert payload["audit_id"].startswith("internal-")


def test_internal_trigger_delivery_success(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(TodoistEventsClient, "list_all_active_tasks", lambda self: [])
    monkeypatch.setattr(
        "autodoist_events_worker.service.evaluate_focus_policy",
        lambda inp: PolicyDecision(True, "NO_FOCUS_TETHER", "no_focus_candidates"),
    )
    monkeypatch.setattr(
        TodoistEventsClient,
        "post_webhook",
        lambda self, *, url, payload, bearer_token: {"status_code": 202, "json": {"ok": True}},
    )
    app = create_app(_cfg(tmp_path))
    client = app.test_client()

    resp = client.post(
        "/internal/trigger",
        headers={"Authorization": "Bearer internal-token"},
        json={"source": "cron_fallback", "deliver": True},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["decision"]["should_notify"] is True
    assert payload["delivery"]["sent"] is True
    assert payload["delivery"]["webhook_status"] == 202
