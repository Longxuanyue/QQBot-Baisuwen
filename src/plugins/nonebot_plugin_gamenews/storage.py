"""
轻量订阅存储 —— 仅管理 QQ 群/用户订阅关系。
"""

from __future__ import annotations

import os
import sqlite3
import threading


class GameStorage:
    """订阅存储，线程安全。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_db_dir()
        self._init_tables()

    def _ensure_db_dir(self) -> None:
        d = os.path.dirname(self.db_path)
        if d:
            os.makedirs(d, exist_ok=True)

    @property
    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_tables(self) -> None:
        with self._lock:
            conn = self._conn
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        target_type   TEXT NOT NULL,
                        target_id     TEXT NOT NULL,
                        subscribed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                        UNIQUE(target_type, target_id)
                    );
                """)
                conn.commit()
            finally:
                conn.close()

    def add_subscription(self, target_type: str, target_id: str) -> bool:
        with self._lock:
            conn = self._conn
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO subscriptions (target_type, target_id) VALUES (?,?)",
                    (target_type, target_id),
                )
                conn.commit()
                return conn.total_changes > 0
            finally:
                conn.close()

    def remove_subscription(self, target_type: str, target_id: str) -> bool:
        with self._lock:
            conn = self._conn
            try:
                conn.execute(
                    "DELETE FROM subscriptions WHERE target_type=? AND target_id=?",
                    (target_type, target_id),
                )
                conn.commit()
                return conn.total_changes > 0
            finally:
                conn.close()

    def get_subscriptions(self) -> list[dict[str, str]]:
        with self._lock:
            conn = self._conn
            try:
                cur = conn.execute(
                    "SELECT target_type, target_id FROM subscriptions ORDER BY subscribed_at"
                )
                return [{"target_type": r[0], "target_id": r[1]} for r in cur.fetchall()]
            finally:
                conn.close()
