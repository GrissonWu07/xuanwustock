from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class WatchlistDB:
    def __init__(self, db_path: str | Path = "watchlist.db"):
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
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL UNIQUE,
                    stock_name TEXT NOT NULL,
                    source_summary TEXT NOT NULL,
                    latest_price REAL DEFAULT 0,
                    latest_signal TEXT DEFAULT '',
                    in_quant_pool INTEGER DEFAULT 0,
                    notes TEXT,
                    metadata_json TEXT DEFAULT '{}',
                    sources_json TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def add_watch(
        self,
        stock_code: str,
        stock_name: str,
        source: str,
        latest_price: float | None = None,
        notes: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        normalized_code = str(stock_code).strip().upper()
        normalized_name = str(stock_name).strip()
        normalized_source = str(source).strip()
        now = datetime.now().isoformat(timespec="seconds")
        metadata = metadata or {}

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watchlist WHERE stock_code = ?", (normalized_code,))
            existing = cursor.fetchone()

            if existing:
                sources = self._decode_json(existing["sources_json"], [])
                if normalized_source and normalized_source not in sources:
                    sources.append(normalized_source)

                merged_metadata = self._decode_json(existing["metadata_json"], {})
                merged_metadata.update(metadata)

                cursor.execute(
                    """
                    UPDATE watchlist
                    SET stock_name = ?,
                        latest_price = ?,
                        notes = COALESCE(?, notes),
                        metadata_json = ?,
                        sources_json = ?,
                        updated_at = ?
                    WHERE stock_code = ?
                    """,
                    (
                        normalized_name or existing["stock_name"],
                        float(latest_price) if latest_price is not None else existing["latest_price"],
                        notes,
                        json.dumps(merged_metadata, ensure_ascii=False),
                        json.dumps(sources, ensure_ascii=False),
                        now,
                        normalized_code,
                    ),
                )
                conn.commit()
                return int(existing["id"])

            cursor.execute(
                """
                INSERT INTO watchlist (
                    stock_code,
                    stock_name,
                    source_summary,
                    latest_price,
                    latest_signal,
                    in_quant_pool,
                    notes,
                    metadata_json,
                    sources_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, '', 0, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_code,
                    normalized_name,
                    normalized_source,
                    float(latest_price) if latest_price is not None else 0.0,
                    notes,
                    json.dumps(metadata, ensure_ascii=False),
                    json.dumps([normalized_source] if normalized_source else [], ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_watches(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watchlist ORDER BY updated_at DESC, id DESC")
            rows = cursor.fetchall()
        return [self._row_to_watch(row) for row in rows]

    def get_watch(self, stock_code: str) -> dict[str, Any] | None:
        normalized_code = str(stock_code).strip().upper()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watchlist WHERE stock_code = ?", (normalized_code,))
            row = cursor.fetchone()
        return self._row_to_watch(row) if row else None

    def update_quant_membership(self, stock_code: str, in_quant_pool: bool) -> None:
        normalized_code = str(stock_code).strip().upper()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE watchlist
                SET in_quant_pool = ?, updated_at = ?
                WHERE stock_code = ?
                """,
                (1 if in_quant_pool else 0, datetime.now().isoformat(timespec="seconds"), normalized_code),
            )
            conn.commit()

    def delete_watch(self, stock_code: str) -> None:
        normalized_code = str(stock_code).strip().upper()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM watchlist WHERE stock_code = ?", (normalized_code,))
            conn.commit()

    @staticmethod
    def _decode_json(raw: str | None, default: Any) -> Any:
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    def _row_to_watch(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "stock_code": row["stock_code"],
            "stock_name": row["stock_name"],
            "source_summary": row["source_summary"],
            "latest_price": float(row["latest_price"] or 0.0),
            "latest_signal": row["latest_signal"] or "",
            "in_quant_pool": bool(row["in_quant_pool"]),
            "notes": row["notes"] or "",
            "metadata": self._decode_json(row["metadata_json"], {}),
            "sources": self._decode_json(row["sources_json"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
