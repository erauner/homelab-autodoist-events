import json
import sqlite3
import time
from typing import Any, Optional


class EventsDB:
    def __init__(self, db_path: str = "events.sqlite", auto_commit: bool = True) -> None:
        self._db_path = db_path
        self._auto_commit = auto_commit
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        if self._conn is not None:
            return
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("DB not connected")
        return self._conn

    def commit(self) -> None:
        self.conn.commit()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS event_receipts (
              delivery_id TEXT PRIMARY KEY,
              received_at_ms INTEGER NOT NULL,
              event_name TEXT NOT NULL,
              user_id TEXT,
              triggered_at TEXT,
              entity_type TEXT,
              entity_id TEXT,
              project_id TEXT,
              status TEXT NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 1,
              last_error TEXT,
              summary_json TEXT,
              payload_sha256 TEXT
            );

            CREATE TABLE IF NOT EXISTS action_outcomes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              delivery_id TEXT NOT NULL,
              rule_name TEXT NOT NULL,
              action_type TEXT NOT NULL,
              target_type TEXT NOT NULL,
              target_id TEXT NOT NULL,
              result TEXT NOT NULL,
              meta_json TEXT,
              UNIQUE(delivery_id, action_type, target_id)
            );
            """
        )
        if self._auto_commit:
            self.commit()

    def upsert_receipt(
        self,
        *,
        delivery_id: str,
        event_name: str,
        user_id: Optional[str],
        triggered_at: Optional[str],
        entity_type: Optional[str],
        entity_id: Optional[str],
        project_id: Optional[str],
        status: str,
        payload_sha256: Optional[str],
    ) -> tuple[bool, dict[str, Any]]:
        now_ms = int(time.time() * 1000)
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO event_receipts (
              delivery_id, received_at_ms, event_name, user_id, triggered_at,
              entity_type, entity_id, project_id, status, payload_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(delivery_id) DO UPDATE SET
              attempt_count = attempt_count + 1,
              status = excluded.status
            """,
            (
                delivery_id,
                now_ms,
                event_name,
                user_id,
                triggered_at,
                entity_type,
                entity_id,
                project_id,
                status,
                payload_sha256,
            ),
        )
        cur.execute("SELECT * FROM event_receipts WHERE delivery_id = ?", (delivery_id,))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to fetch upserted receipt")

        if self._auto_commit:
            self.commit()

        receipt = dict(row)
        is_new = receipt.get("attempt_count", 1) == 1
        return is_new, receipt

    def mark_status(
        self,
        delivery_id: str,
        status: str,
        *,
        summary: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE event_receipts
            SET status = ?, summary_json = ?, last_error = ?
            WHERE delivery_id = ?
            """,
            (status, json.dumps(summary or {}), error, delivery_id),
        )
        if self._auto_commit:
            self.commit()

    def record_action(
        self,
        delivery_id: str,
        rule_name: str,
        action_type: str,
        target_type: str,
        target_id: str,
        result: str,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO action_outcomes (
              delivery_id, rule_name, action_type, target_type, target_id, result, meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(delivery_id, action_type, target_id) DO UPDATE SET
              result = excluded.result,
              meta_json = excluded.meta_json
            """,
            (
                delivery_id,
                rule_name,
                action_type,
                target_type,
                target_id,
                result,
                json.dumps(meta or {}),
            ),
        )
        if self._auto_commit:
            self.commit()

    def list_receipts(self, limit: int = 100) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM event_receipts ORDER BY received_at_ms DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_receipt(self, delivery_id: str) -> Optional[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM event_receipts WHERE delivery_id = ?", (delivery_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_actions(self, delivery_id: str) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM action_outcomes WHERE delivery_id = ? ORDER BY id ASC", (delivery_id,)
        )
        return [dict(r) for r in cur.fetchall()]
