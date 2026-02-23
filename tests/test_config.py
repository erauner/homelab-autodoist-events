from autodoist_events_worker.config import EventsConfig


def test_config_reads_reminder_timezone_from_env(monkeypatch) -> None:
    monkeypatch.setenv("TODOIST_API_KEY", "x")
    monkeypatch.setenv("TODOIST_CLIENT_SECRET", "y")
    monkeypatch.setenv("AUTODOIST_EVENTS_REMINDER_TIMEZONE", "UTC")

    cfg = EventsConfig.from_env_and_cli([])

    assert cfg.reminder_timezone == "UTC"
