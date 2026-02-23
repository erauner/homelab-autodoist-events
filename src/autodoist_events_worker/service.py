import hashlib
import json
import logging
from typing import Any

from flask import Flask, jsonify, request

from todoist_automation_shared import verify_todoist_signature

from .config import EventsConfig
from .db import EventsDB
from .rules import RecurringClearCommentsOnCompletionRule, RuleContext, parse_event
from .todoist_client import TodoistEventsClient

LOG = logging.getLogger(__name__)


def _is_admin_allowed(config: EventsConfig, auth_header: str | None) -> bool:
    if not config.admin_token:
        return False
    if not auth_header:
        return False
    return auth_header.strip() == f"Bearer {config.admin_token}"


def create_app(config: EventsConfig) -> Flask:
    app = Flask(__name__)
    db = EventsDB(config.db_path, auto_commit=True)
    db.connect()
    todoist = TodoistEventsClient(config.todoist_api_token, timeout_s=config.timeout_s)
    rules = [RecurringClearCommentsOnCompletionRule()]

    @app.get("/health")
    def health() -> Any:
        return jsonify({"ok": True})

    @app.get("/api/events")
    def api_events() -> Any:
        if not _is_admin_allowed(config, request.headers.get("Authorization")):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return jsonify({"ok": True, "items": db.list_receipts(limit=200)})

    @app.get("/api/events/<delivery_id>")
    def api_event(delivery_id: str) -> Any:
        if not _is_admin_allowed(config, request.headers.get("Authorization")):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        receipt = db.get_receipt(delivery_id)
        if receipt is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({"ok": True, "receipt": receipt, "actions": db.list_actions(delivery_id)})

    @app.post("/hooks/todoist")
    def todoist_hook() -> Any:
        raw = request.get_data(cache=False)
        sig = request.headers.get("X-Todoist-Hmac-SHA256", "")
        delivery_id = request.headers.get("X-Todoist-Delivery-ID", "")
        if not delivery_id:
            return jsonify({"ok": False, "error": "missing_delivery_id"}), 400

        payload_sha256 = hashlib.sha256(raw).hexdigest()

        if not verify_todoist_signature(raw, sig, client_secret=config.webhook_client_secret):
            db.upsert_receipt(
                delivery_id=delivery_id,
                event_name="unknown",
                user_id=None,
                triggered_at=None,
                entity_type="unknown",
                entity_id=None,
                project_id=None,
                status="rejected_signature",
                payload_sha256=payload_sha256,
            )
            return jsonify({"ok": False, "error": "invalid_signature"}), 401

        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            db.upsert_receipt(
                delivery_id=delivery_id,
                event_name="unknown",
                user_id=None,
                triggered_at=None,
                entity_type="unknown",
                entity_id=None,
                project_id=None,
                status="bad_request",
                payload_sha256=payload_sha256,
            )
            return jsonify({"ok": False, "error": "invalid_json"}), 400

        event = parse_event(payload, delivery_id)
        if not event.event_name:
            return jsonify({"ok": False, "error": "missing_event_name"}), 400

        is_new, receipt = db.upsert_receipt(
            delivery_id=delivery_id,
            event_name=event.event_name,
            user_id=event.user_id,
            triggered_at=event.triggered_at,
            entity_type="task",
            entity_id=event.task_id,
            project_id=event.project_id,
            status="received",
            payload_sha256=payload_sha256,
        )

        if not is_new and receipt.get("status") == "processed":
            return jsonify({"ok": True, "delivery_id": delivery_id, "duplicate": True}), 200

        if not config.enabled:
            db.mark_status(delivery_id, "ignored_disabled", summary={"enabled": False})
            return jsonify({"ok": True, "delivery_id": delivery_id, "status": "ignored_disabled"}), 200

        if config.allowed_user_ids and (event.user_id not in config.allowed_user_ids):
            db.mark_status(delivery_id, "ignored_allowlist", summary={"reason": "user_id"})
            return jsonify({"ok": True, "delivery_id": delivery_id, "status": "ignored_allowlist"}), 200

        if event.project_id and config.denied_project_ids and event.project_id in config.denied_project_ids:
            db.mark_status(delivery_id, "ignored_allowlist", summary={"reason": "denied_project"})
            return jsonify({"ok": True, "delivery_id": delivery_id, "status": "ignored_allowlist"}), 200

        if config.allowed_project_ids and event.project_id not in config.allowed_project_ids:
            db.mark_status(delivery_id, "ignored_allowlist", summary={"reason": "project_id"})
            return jsonify({"ok": True, "delivery_id": delivery_id, "status": "ignored_allowlist"}), 200

        outcomes: list[dict[str, Any]] = []
        try:
            db.mark_status(delivery_id, "processing")
            ctx = RuleContext(config=config, db=db, todoist=todoist)
            for rule in rules:
                if not config.rule_recurring_clear_comments and rule.name == "recurring_clear_comments_on_completion":
                    continue
                if not rule.matches(event):
                    continue
                actions, plan_meta = rule.plan(ctx, event)
                deleted = 0
                for action in actions:
                    if config.dry_run:
                        db.record_action(
                            delivery_id,
                            rule.name,
                            action.action_type,
                            action.target_type,
                            action.target_id,
                            "skipped",
                            {**action.meta, "reason": "dry_run"},
                        )
                        continue
                    todoist.delete_comment(action.target_id)
                    deleted += 1
                    db.record_action(
                        delivery_id,
                        rule.name,
                        action.action_type,
                        action.target_type,
                        action.target_id,
                        "success",
                        action.meta,
                    )
                outcomes.append({"rule": rule.name, **plan_meta, "deleted": deleted})

            if not outcomes:
                db.mark_status(delivery_id, "processed", summary={"rules_triggered": 0})
            else:
                db.mark_status(delivery_id, "processed", summary={"rules_triggered": len(outcomes), "outcomes": outcomes})
            return jsonify({"ok": True, "delivery_id": delivery_id, "duplicate": False, "outcomes": outcomes}), 200
        except Exception as exc:  # transient failure path
            LOG.exception("Failed processing delivery_id=%s", delivery_id)
            db.mark_status(delivery_id, "error", error=str(exc))
            return jsonify({"ok": False, "delivery_id": delivery_id, "error": "transient_processing_failure"}), 500

    return app
