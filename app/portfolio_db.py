"""Registered holding storage backed by the unified stock universe."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.console_utils import safe_print as print
from app.db.runtime.legacy_dbapi import legacy_dbapi_connection
from app.db.runtime.registry import DatabaseRuntime
from app.quant_sim.db import DEFAULT_DB_FILE, QuantSimDB
from app.quant_sim.time_utils import local_now_text


DB_PATH = str(DEFAULT_DB_FILE)


class PortfolioDB:
    """Registered holding profile operations on ``stock_universe``."""

    def __init__(self, db_path: str | Path = DB_PATH, *, db_runtime: DatabaseRuntime | None = None):
        self.db_path = str(db_path)
        self.db_runtime = db_runtime
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        return legacy_dbapi_connection(
            db_path=self.db_path,
            db_runtime=self.db_runtime,
            access_mode="readwrite",
            row_factory=True,
        )

    def _init_database(self) -> None:
        QuantSimDB(self.db_path, db_runtime=self.db_runtime)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            self._ensure_stock_universe_column(cursor, "registered_quantity", "INTEGER")
            self._ensure_stock_universe_column(cursor, "registered_cost_price", "REAL")
            self._ensure_stock_universe_column(cursor, "registered_take_profit", "REAL")
            self._ensure_stock_universe_column(cursor, "registered_stop_loss", "REAL")
            self._ensure_stock_universe_column(cursor, "registered_auto_monitor", "INTEGER DEFAULT 1")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portfolio_stock_id INTEGER NOT NULL,
                    analysis_time TEXT DEFAULT (datetime('now','localtime')),
                    rating TEXT,
                    confidence REAL,
                    current_price REAL,
                    target_price REAL,
                    entry_min REAL,
                    entry_max REAL,
                    take_profit REAL,
                    stop_loss REAL,
                    summary TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_portfolio_analysis_stock_id
                ON portfolio_analysis_history(portfolio_stock_id)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_portfolio_analysis_time
                ON portfolio_analysis_history(analysis_time DESC)
                """
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_stock_universe_column(cursor: sqlite3.Cursor, column_name: str, definition: str) -> None:
        cursor.execute("PRAGMA table_info(stock_universe)")
        columns = {str(row["name"]) for row in cursor.fetchall()}
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE stock_universe ADD COLUMN {column_name} {definition}")

    @staticmethod
    def _now() -> str:
        return local_now_text()

    @staticmethod
    def _row_to_portfolio(row: sqlite3.Row) -> Dict:
        return {
            "id": row["id"],
            "code": row["stock_code"],
            "name": row["stock_name"],
            "sector": row["sector"] or row["industry"] or "",
            "cost_price": row["registered_cost_price"],
            "quantity": row["registered_quantity"],
            "take_profit": row["registered_take_profit"],
            "stop_loss": row["registered_stop_loss"],
            "note": row["notes"] or "",
            "auto_monitor": bool(row["registered_auto_monitor"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "latest_price": row["latest_price"],
            "latest_signal": row["latest_signal"],
        }

    def add_stock(
        self,
        code: str,
        name: str,
        sector: str = "",
        cost_price: Optional[float] = None,
        quantity: Optional[int] = None,
        note: str = "",
        auto_monitor: bool = True,
    ) -> int:
        code = str(code or "").strip().upper()
        if not code:
            raise ValueError("股票代码不能为空")
        if self.get_stock_by_code(code):
            raise ValueError(f"股票代码 {code} 已存在")
        conn = self._get_connection()
        cursor = conn.cursor()
        now_text = self._now()
        try:
            cursor.execute("SELECT id FROM stock_universe WHERE stock_code = ?", (code,))
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    """
                    UPDATE stock_universe
                    SET stock_name = COALESCE(NULLIF(?, ''), stock_name),
                        sector = COALESCE(NULLIF(?, ''), sector),
                        watched = 1,
                        registered_position_enabled = 1,
                        registered_quantity = ?,
                        registered_cost_price = ?,
                        registered_take_profit = registered_take_profit,
                        registered_stop_loss = registered_stop_loss,
                        registered_auto_monitor = ?,
                        notes = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (name, sector, quantity, cost_price, 1 if auto_monitor else 0, note, now_text, int(existing["id"])),
                )
                stock_id = int(existing["id"])
            else:
                cursor.execute(
                    """
                    INSERT INTO stock_universe
                    (stock_code, stock_name, sector, watched, registered_position_enabled,
                     registered_quantity, registered_cost_price, registered_auto_monitor,
                     source, notes, created_at, updated_at)
                    VALUES (?, ?, ?, 1, 1, ?, ?, ?, 'portfolio', ?, ?, ?)
                    """,
                    (code, name or code, sector, quantity, cost_price, 1 if auto_monitor else 0, note, now_text, now_text),
                )
                stock_id = int(cursor.lastrowid)
            cursor.execute(
                """
                INSERT OR IGNORE INTO stock_universe_sources (stock_universe_id, source, created_at)
                VALUES (?, 'portfolio', ?)
                """,
                (stock_id, now_text),
            )
            conn.commit()
            print(f"[OK] 登记持仓成功: {code} {name} (ID: {stock_id})")
            return stock_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_stock(self, stock_id: int, **kwargs) -> bool:
        field_map = {
            "code": "stock_code",
            "name": "stock_name",
            "sector": "sector",
            "cost_price": "registered_cost_price",
            "quantity": "registered_quantity",
            "take_profit": "registered_take_profit",
            "stop_loss": "registered_stop_loss",
            "note": "notes",
            "auto_monitor": "registered_auto_monitor",
        }
        updates: list[str] = []
        values: list = []
        for key, column in field_map.items():
            if key not in kwargs:
                continue
            value = kwargs[key]
            if key == "code" and value is not None:
                value = str(value).strip().upper()
            if key == "auto_monitor" and value is not None:
                value = 1 if bool(value) else 0
            updates.append(f"{column} = ?")
            values.append(value)
        if not updates:
            return False
        updates.append("updated_at = ?")
        values.append(self._now())
        values.append(stock_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"UPDATE stock_universe SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_stock(self, stock_id: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE stock_universe
                SET registered_position_enabled = 0, registered_quantity = NULL,
                    registered_cost_price = NULL, updated_at = ?
                WHERE id = ?
                """,
                (self._now(), stock_id),
            )
            changed = cursor.rowcount > 0
            cursor.execute("DELETE FROM portfolio_analysis_history WHERE portfolio_stock_id = ?", (stock_id,))
            conn.commit()
            return changed
        finally:
            conn.close()

    def get_stock(self, stock_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM stock_universe WHERE id = ? AND registered_position_enabled = 1", (stock_id,))
            row = cursor.fetchone()
            return self._row_to_portfolio(row) if row else None
        finally:
            conn.close()

    def get_stock_by_code(self, code: str) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM stock_universe WHERE stock_code = ? AND registered_position_enabled = 1",
                (str(code or "").strip().upper(),),
            )
            row = cursor.fetchone()
            return self._row_to_portfolio(row) if row else None
        finally:
            conn.close()

    def get_all_stocks(self, auto_monitor_only: bool = False) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            where = "registered_position_enabled = 1"
            params: list = []
            if auto_monitor_only:
                where += " AND registered_auto_monitor = 1"
            cursor.execute(f"SELECT * FROM stock_universe WHERE {where} ORDER BY created_at DESC", params)
            return [self._row_to_portfolio(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def search_stocks(self, keyword: str) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            like = f"%{keyword}%"
            cursor.execute(
                """
                SELECT * FROM stock_universe
                WHERE registered_position_enabled = 1
                  AND (stock_code LIKE ? OR stock_name LIKE ?)
                ORDER BY created_at DESC
                """,
                (like, like),
            )
            return [self._row_to_portfolio(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_stock_count(self) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) AS count FROM stock_universe WHERE registered_position_enabled = 1")
            row = cursor.fetchone()
            return int(row["count"] or 0) if row else 0
        finally:
            conn.close()

    def save_analysis(
        self,
        stock_id: int,
        rating: str,
        confidence: float,
        current_price: float,
        target_price: Optional[float] = None,
        entry_min: Optional[float] = None,
        entry_max: Optional[float] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        summary: str = "",
    ) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO portfolio_analysis_history
                (portfolio_stock_id, analysis_time, rating, confidence, current_price,
                 target_price, entry_min, entry_max, take_profit, stop_loss, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (stock_id, self._now(), rating, confidence, current_price, target_price, entry_min, entry_max, take_profit, stop_loss, summary),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def get_analysis_history(self, stock_id: int, limit: int = 10) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT * FROM portfolio_analysis_history
                WHERE portfolio_stock_id = ?
                ORDER BY analysis_time DESC
                LIMIT ?
                """,
                (stock_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_latest_analysis_history(self, stock_id: int, limit: int = 10) -> List[Dict]:
        return self.get_analysis_history(stock_id, limit)

    def get_latest_analysis(self, stock_id: int) -> Optional[Dict]:
        rows = self.get_analysis_history(stock_id, limit=1)
        return rows[0] if rows else None

    def get_rating_changes(self, stock_id: int, days: int = 30) -> List[Tuple[str, str, str]]:
        rows = self.get_analysis_history(stock_id, limit=1000)
        changes: list[Tuple[str, str, str]] = []
        for index in range(1, len(rows)):
            previous = rows[index - 1]
            current = rows[index]
            if previous.get("rating") != current.get("rating"):
                changes.append((str(current.get("analysis_time")), str(previous.get("rating")), str(current.get("rating"))))
        return changes

    def delete_old_analysis(self, days: int = 90) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM portfolio_analysis_history WHERE analysis_time < datetime('now', '-' || ? || ' days')",
                (days,),
            )
            conn.commit()
            return int(cursor.rowcount)
        finally:
            conn.close()

    def _latest_analysis_query(self, where_sql: str = "") -> str:
        return f"""
            SELECT
                s.id,
                s.stock_code AS code,
                s.stock_name AS name,
                COALESCE(s.sector, s.industry, '') AS sector,
                s.registered_cost_price AS cost_price,
                s.registered_quantity AS quantity,
                s.registered_take_profit AS take_profit,
                s.registered_stop_loss AS stop_loss,
                s.notes AS note,
                s.registered_auto_monitor AS auto_monitor,
                s.created_at,
                s.updated_at,
                h.rating, h.confidence, h.current_price, h.target_price,
                h.entry_min, h.entry_max, h.take_profit AS analysis_take_profit,
                h.stop_loss AS analysis_stop_loss, h.analysis_time
            FROM stock_universe s
            LEFT JOIN (
                SELECT h1.*
                FROM portfolio_analysis_history h1
                INNER JOIN (
                    SELECT portfolio_stock_id, MAX(analysis_time) AS max_time
                    FROM portfolio_analysis_history
                    GROUP BY portfolio_stock_id
                ) h2
                ON h1.portfolio_stock_id = h2.portfolio_stock_id
                AND h1.analysis_time = h2.max_time
            ) h ON s.id = h.portfolio_stock_id
            {where_sql}
        """

    def get_all_latest_analysis(self) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(self._latest_analysis_query("WHERE s.registered_position_enabled = 1") + " ORDER BY s.created_at DESC")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_latest_analysis_page(self, *, search: str = "", limit: int = 50, offset: int = 0) -> List[Dict]:
        keyword = str(search or "").strip()
        params: list = []
        where = "WHERE s.registered_position_enabled = 1"
        if keyword:
            like = f"%{keyword}%"
            where += " AND (s.stock_code LIKE ? OR s.stock_name LIKE ? OR s.sector LIKE ? OR COALESCE(h.rating, '') LIKE ?)"
            params.extend([like, like, like, like])
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                self._latest_analysis_query(where) + " ORDER BY s.created_at DESC LIMIT ? OFFSET ?",
                (*params, max(0, int(limit)), max(0, int(offset))),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def count_latest_analysis(self, *, search: str = "") -> int:
        keyword = str(search or "").strip()
        params: list = []
        where = "WHERE s.registered_position_enabled = 1"
        if keyword:
            like = f"%{keyword}%"
            where += " AND (s.stock_code LIKE ? OR s.stock_name LIKE ? OR s.sector LIKE ? OR COALESCE(h.rating, '') LIKE ?)"
            params.extend([like, like, like, like])
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT COUNT(*) AS total FROM ({self._latest_analysis_query(where)})", tuple(params))
            row = cursor.fetchone()
            return int(row["total"] or 0) if row else 0
        finally:
            conn.close()


portfolio_db = PortfolioDB()
