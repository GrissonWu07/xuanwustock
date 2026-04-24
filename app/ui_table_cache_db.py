from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.runtime_paths import default_db_path


DEFAULT_DB_FILE = str(default_db_path("ui_table_cache.db"))


class UITableCacheDB:
    """SQLite-backed cache for UI tables whose source is a computed snapshot."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_FILE):
        self.db_path = str(db_path)
        db_parent = Path(self.db_path).parent
        if db_parent and not db_parent.exists():
            db_parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ui_table_rows (
                    table_key TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    row_id TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (table_key, row_index)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ui_table_rows_lookup
                ON ui_table_rows(table_key, search_text, row_index)
                """
            )
            conn.commit()

    @staticmethod
    def _row_search_text(row: dict[str, Any]) -> str:
        parts = [
            row.get("id"),
            row.get("code"),
            row.get("name"),
            row.get("source"),
            row.get("industry"),
            row.get("reason"),
            *(row.get("cells") if isinstance(row.get("cells"), list) else []),
            *(row.get("badges") if isinstance(row.get("badges"), list) else []),
        ]
        return " ".join(str(part or "") for part in parts).lower()

    def replace_rows(self, table_key: str, rows: list[dict[str, Any]]) -> None:
        now_text = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ui_table_rows WHERE table_key = ?", (table_key,))
            cursor.executemany(
                """
                INSERT INTO ui_table_rows(table_key, row_index, row_id, search_text, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        table_key,
                        index,
                        str(row.get("id") or index),
                        self._row_search_text(row),
                        json.dumps(row, ensure_ascii=False, default=str),
                        now_text,
                    )
                    for index, row in enumerate(rows)
                ],
            )
            conn.commit()

    def count_rows(self, table_key: str, search: str | None = None) -> int:
        keyword = str(search or "").strip().lower()
        where = "WHERE table_key = ?"
        params: list[Any] = [table_key]
        if keyword:
            where += " AND search_text LIKE ?"
            params.append(f"%{keyword}%")
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) AS total FROM ui_table_rows {where}", tuple(params))
            row = cursor.fetchone()
        return int(row["total"] or 0) if row else 0

    def get_rows_page(self, table_key: str, search: str | None = None, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        keyword = str(search or "").strip().lower()
        where = "WHERE table_key = ?"
        params: list[Any] = [table_key]
        if keyword:
            where += " AND search_text LIKE ?"
            params.append(f"%{keyword}%")
        params.extend([max(0, int(limit)), max(0, int(offset))])
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT payload_json
                FROM ui_table_rows
                {where}
                ORDER BY row_index ASC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
        payloads: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (json.JSONDecodeError, TypeError):
                payload = {}
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads
