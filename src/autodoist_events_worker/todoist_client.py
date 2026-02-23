from typing import Any

import requests


class TodoistEventsClient:
    def __init__(self, api_key: str, timeout_s: float = 10.0) -> None:
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.base_url = "https://api.todoist.com/api/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def get_task(self, task_id: str) -> dict[str, Any]:
        resp = requests.get(
            f"{self.base_url}/tasks/{task_id}", headers=self.headers, timeout=self.timeout_s
        )
        resp.raise_for_status()
        return resp.json()

    def list_comments_for_task(self, task_id: str) -> list[dict[str, Any]]:
        # Todoist comments endpoint is paginated, but this first pass handles one page.
        resp = requests.get(
            f"{self.base_url}/comments",
            headers=self.headers,
            params={"task_id": task_id},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return []

    def delete_comment(self, comment_id: str) -> None:
        resp = requests.delete(
            f"{self.base_url}/comments/{comment_id}", headers=self.headers, timeout=self.timeout_s
        )
        if resp.status_code not in (200, 204):
            resp.raise_for_status()
