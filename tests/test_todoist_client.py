from unittest.mock import patch

from autodoist_events_worker.todoist_client import TodoistEventsClient


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_list_comments_reads_results_envelope() -> None:
    client = TodoistEventsClient("token")
    payload = {
        "results": [
            {"id": "c1", "content": "a"},
            {"id": "c2", "content": "b"},
        ],
        "next_cursor": None,
    }
    with patch("autodoist_events_worker.todoist_client.requests.get", return_value=_Resp(payload)):
        comments = client.list_comments_for_task("task1")
    assert [c["id"] for c in comments] == ["c1", "c2"]

