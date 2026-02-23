import argparse
import os
from dataclasses import dataclass, field
from typing import Optional, Sequence

from todoist_automation_shared import parse_bool, parse_csv_set


@dataclass(frozen=True)
class EventsConfig:
    todoist_api_token: str
    webhook_client_secret: str
    todoist_client_id: Optional[str] = None
    oauth_redirect_uri: Optional[str] = None
    db_path: str = "events.sqlite"
    enabled: bool = True
    dry_run: bool = False
    rule_recurring_clear_comments: bool = True
    rule_recurring_purge_subtasks: bool = False
    rule_reminder_notify: bool = False
    allowed_user_ids: set[str] = field(default_factory=set)
    allowed_project_ids: set[str] = field(default_factory=set)
    denied_project_ids: set[str] = field(default_factory=set)
    keep_markers: tuple[str, ...] = ("[openclaw:plan]",)
    max_delete_comments: int = 200
    max_delete_subtasks: int = 200
    reminder_webhook_url: Optional[str] = None
    reminder_webhook_token: Optional[str] = None
    reminder_require_focus_label: bool = False
    reminder_cooldown_minutes: int = 60
    reminder_timezone: str = "America/Chicago"
    allowed_hour_start: int = 9
    allowed_hour_end: int = 18
    reminder_channel: str = "discord"
    reminder_to: Optional[str] = None
    admin_token: Optional[str] = None
    host: str = "0.0.0.0"
    port: int = 8081
    timeout_s: float = 10.0

    @staticmethod
    def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="Autodoist events worker")
        parser.add_argument("--api-key")
        parser.add_argument("--webhook-secret")
        parser.add_argument("--client-id")
        parser.add_argument("--oauth-redirect-uri")
        parser.add_argument("--db-path")
        parser.add_argument("--host")
        parser.add_argument("--port", type=int)
        parser.add_argument("--admin-token")
        parser.add_argument("--timeout-s", type=float)
        return parser.parse_args(argv)

    @classmethod
    def from_env_and_cli(cls, argv: Optional[Sequence[str]] = None) -> "EventsConfig":
        args = cls._parse_args(argv)
        api_key = args.api_key or os.getenv("TODOIST_API_KEY")
        secret = args.webhook_secret or os.getenv("TODOIST_CLIENT_SECRET")
        if not api_key:
            raise ValueError("TODOIST_API_KEY (or --api-key) is required")
        if not secret:
            raise ValueError("TODOIST_CLIENT_SECRET (or --webhook-secret) is required")

        markers = os.getenv("AUTODOIST_EVENTS_KEEP_MARKERS", "[openclaw:plan]")
        keep_markers = tuple(x.strip() for x in markers.split(",") if x.strip())

        return cls(
            todoist_api_token=api_key,
            webhook_client_secret=secret,
            todoist_client_id=args.client_id or os.getenv("TODOIST_CLIENT_ID"),
            oauth_redirect_uri=args.oauth_redirect_uri
            or os.getenv("AUTODOIST_EVENTS_OAUTH_REDIRECT_URI"),
            db_path=args.db_path or os.getenv("AUTODOIST_EVENTS_DB_PATH", "events.sqlite"),
            enabled=parse_bool(os.getenv("AUTODOIST_EVENTS_ENABLED"), True),
            dry_run=parse_bool(os.getenv("AUTODOIST_EVENTS_DRY_RUN"), False),
            rule_recurring_clear_comments=parse_bool(
                os.getenv("AUTODOIST_EVENTS_RULE_RECURRING_CLEAR_COMMENTS"), True
            ),
            rule_recurring_purge_subtasks=parse_bool(
                os.getenv("AUTODOIST_EVENTS_RULE_RECURRING_PURGE_SUBTASKS"), False
            ),
            rule_reminder_notify=parse_bool(
                os.getenv("AUTODOIST_EVENTS_RULE_REMINDER_NOTIFY"), False
            ),
            allowed_user_ids=parse_csv_set(os.getenv("AUTODOIST_EVENTS_ALLOWED_USER_IDS")),
            allowed_project_ids=parse_csv_set(os.getenv("AUTODOIST_EVENTS_ALLOWED_PROJECT_IDS")),
            denied_project_ids=parse_csv_set(os.getenv("AUTODOIST_EVENTS_DENIED_PROJECT_IDS")),
            keep_markers=keep_markers,
            max_delete_comments=int(os.getenv("AUTODOIST_EVENTS_MAX_DELETE_COMMENTS", "200")),
            max_delete_subtasks=int(os.getenv("AUTODOIST_EVENTS_MAX_DELETE_SUBTASKS", "200")),
            reminder_webhook_url=os.getenv("AUTODOIST_EVENTS_REMINDER_WEBHOOK_URL"),
            reminder_webhook_token=os.getenv("AUTODOIST_EVENTS_REMINDER_WEBHOOK_TOKEN"),
            reminder_require_focus_label=parse_bool(
                os.getenv("AUTODOIST_EVENTS_REMINDER_REQUIRE_FOCUS_LABEL"), False
            ),
            reminder_cooldown_minutes=int(os.getenv("AUTODOIST_EVENTS_REMINDER_COOLDOWN_MINUTES", "60")),
            reminder_timezone=os.getenv("AUTODOIST_EVENTS_REMINDER_TIMEZONE", "America/Chicago"),
            allowed_hour_start=int(os.getenv("AUTODOIST_EVENTS_ALLOWED_HOUR_START", "9")),
            allowed_hour_end=int(os.getenv("AUTODOIST_EVENTS_ALLOWED_HOUR_END", "18")),
            reminder_channel=os.getenv("AUTODOIST_EVENTS_REMINDER_CHANNEL", "discord"),
            reminder_to=os.getenv("AUTODOIST_EVENTS_REMINDER_TO"),
            admin_token=args.admin_token or os.getenv("AUTODOIST_EVENTS_ADMIN_TOKEN"),
            host=args.host or os.getenv("AUTODOIST_EVENTS_HOST", "0.0.0.0"),
            port=args.port or int(os.getenv("AUTODOIST_EVENTS_PORT", "8081")),
            timeout_s=args.timeout_s or float(os.getenv("AUTODOIST_EVENTS_TIMEOUT_S", "10.0")),
        )
