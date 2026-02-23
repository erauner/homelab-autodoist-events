from autodoist_events_worker.config import EventsConfig
from autodoist_events_worker.service import create_app
from autodoist_events_worker.todoist_client import TodoistEventsClient


def _base_config(tmp_path) -> EventsConfig:
    return EventsConfig(
        todoist_api_token="token",
        webhook_client_secret="secret",
        todoist_client_id="client-id",
        oauth_redirect_uri="https://autodoist-events.erauner.dev/oauth/callback",
        db_path=str(tmp_path / "events.sqlite"),
    )


def test_oauth_callback_exchanges_code(monkeypatch, tmp_path) -> None:
    called = {}

    def _fake_exchange(self, *, code, client_id, client_secret, redirect_uri):
        called["code"] = code
        called["client_id"] = client_id
        called["client_secret"] = client_secret
        called["redirect_uri"] = redirect_uri
        return {"access_token": "abc123", "scope": "data:read_write"}

    monkeypatch.setattr(TodoistEventsClient, "exchange_oauth_code", _fake_exchange)
    app = create_app(_base_config(tmp_path))
    client = app.test_client()

    resp = client.get("/oauth/callback?code=oauth-code&state=smoke")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["oauth_exchanged"] is True
    assert called["code"] == "oauth-code"
    assert called["client_id"] == "client-id"


def test_oauth_callback_fails_without_oauth_config(tmp_path) -> None:
    app = create_app(
        EventsConfig(
            todoist_api_token="token",
            webhook_client_secret="secret",
            db_path=str(tmp_path / "events.sqlite"),
        )
    )
    client = app.test_client()

    resp = client.get("/oauth/callback?code=oauth-code&state=smoke")
    assert resp.status_code == 500
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["oauth_exchanged"] is False
