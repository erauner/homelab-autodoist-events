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
        # Todoist returns {"results":[...], "next_cursor": "..."} for this endpoint.
        # We currently process the first page only.
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
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                return results
        return []

    def delete_comment(self, comment_id: str) -> None:
        resp = requests.delete(
            f"{self.base_url}/comments/{comment_id}", headers=self.headers, timeout=self.timeout_s
        )
        if resp.status_code not in (200, 204):
            resp.raise_for_status()

    def list_active_tasks_for_project(self, project_id: str) -> list[dict[str, Any]]:
        resp = requests.get(
            f"{self.base_url}/tasks",
            headers=self.headers,
            params={"project_id": project_id},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                return results
        return []

    def list_all_active_tasks(self) -> list[dict[str, Any]]:
        resp = requests.get(
            f"{self.base_url}/tasks",
            headers=self.headers,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                return results
        return []

    def delete_task(self, task_id: str) -> None:
        resp = requests.delete(
            f"{self.base_url}/tasks/{task_id}", headers=self.headers, timeout=self.timeout_s
        )
        if resp.status_code not in (200, 204):
            resp.raise_for_status()

    def post_webhook(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout_s)
        resp.raise_for_status()
        out: dict[str, Any] = {"status_code": resp.status_code}
        try:
            out["json"] = resp.json()
        except Exception:
            out["text"] = (resp.text or "")[:1000]
        return out

    def exchange_oauth_code(
        self,
        *,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        # Todoist OAuth token exchange endpoint.
        resp = requests.post(
            "https://todoist.com/oauth/access_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()
