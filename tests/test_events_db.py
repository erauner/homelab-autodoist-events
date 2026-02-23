from autodoist_events_worker.db import EventsDB


def test_upsert_receipt_idempotent(tmp_path) -> None:
    db = EventsDB(str(tmp_path / "events.sqlite"), auto_commit=True)
    db.connect()
    is_new, row = db.upsert_receipt(
        delivery_id="d1",
        event_name="item:completed",
        user_id="u1",
        triggered_at=None,
        entity_type="task",
        entity_id="t1",
        project_id="p1",
        status="received",
        payload_sha256="h1",
    )
    assert is_new is True
    assert row["attempt_count"] == 1

    is_new2, row2 = db.upsert_receipt(
        delivery_id="d1",
        event_name="item:completed",
        user_id="u1",
        triggered_at=None,
        entity_type="task",
        entity_id="t1",
        project_id="p1",
        status="received",
        payload_sha256="h1",
    )
    assert is_new2 is False
    assert row2["attempt_count"] == 2
