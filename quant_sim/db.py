"""SQLite persistence for the quant simulation workflow."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


DEFAULT_DB_FILE = "quant_sim.db"


class QuantSimDB:
    """Persistence layer for candidate pool, strategy signals, and sim positions."""

    def __init__(self, db_file: str | Path = DEFAULT_DB_FILE):
        self.db_file = str(db_file)
        self._init_database()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self) -> None:
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS candidate_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL UNIQUE,
                stock_name TEXT,
                source TEXT NOT NULL,
                latest_price REAL DEFAULT 0,
                notes TEXT,
                metadata_json TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                action TEXT NOT NULL,
                confidence INTEGER DEFAULT 0,
                reasoning TEXT,
                position_size_pct REAL DEFAULT 0,
                stop_loss_pct REAL DEFAULT 0,
                take_profit_pct REAL DEFAULT 0,
                status TEXT DEFAULT 'observed',
                executed_action TEXT,
                execution_note TEXT,
                delay_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                executed_at TEXT,
                FOREIGN KEY(candidate_id) REFERENCES candidate_pool(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL UNIQUE,
                stock_name TEXT,
                quantity INTEGER DEFAULT 0,
                avg_price REAL DEFAULT 0,
                latest_price REAL DEFAULT 0,
                market_value REAL DEFAULT 0,
                unrealized_pnl REAL DEFAULT 0,
                unrealized_pnl_pct REAL DEFAULT 0,
                status TEXT DEFAULT 'holding',
                opened_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_position_lots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL,
                stock_code TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                unlock_date TEXT NOT NULL,
                status TEXT DEFAULT 'locked',
                FOREIGN KEY(position_id) REFERENCES sim_positions(id)
            )
            """
        )

        conn.commit()
        conn.close()

    def add_candidate(self, candidate: dict[str, Any]) -> int:
        payload = {
            "stock_code": candidate["stock_code"],
            "stock_name": candidate.get("stock_name"),
            "source": candidate.get("source", "manual"),
            "latest_price": candidate.get("latest_price", 0),
            "notes": candidate.get("notes"),
            "metadata_json": json.dumps(candidate.get("metadata", {}), ensure_ascii=False),
            "status": candidate.get("status", "active"),
            "updated_at": self._now(),
        }

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM candidate_pool WHERE stock_code = ?", (payload["stock_code"],))
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                """
                UPDATE candidate_pool
                SET stock_name = ?, source = ?, latest_price = ?, notes = ?, metadata_json = ?,
                    status = ?, updated_at = ?
                WHERE stock_code = ?
                """,
                (
                    payload["stock_name"],
                    payload["source"],
                    payload["latest_price"],
                    payload["notes"],
                    payload["metadata_json"],
                    payload["status"],
                    payload["updated_at"],
                    payload["stock_code"],
                ),
            )
            candidate_id = int(existing["id"])
        else:
            cursor.execute(
                """
                INSERT INTO candidate_pool
                (stock_code, stock_name, source, latest_price, notes, metadata_json, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["stock_code"],
                    payload["stock_name"],
                    payload["source"],
                    payload["latest_price"],
                    payload["notes"],
                    payload["metadata_json"],
                    payload["status"],
                    payload["updated_at"],
                ),
            )
            candidate_id = int(cursor.lastrowid)

        conn.commit()
        conn.close()
        return candidate_id

    def get_candidates(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()

        if status:
            cursor.execute(
                "SELECT * FROM candidate_pool WHERE status = ? ORDER BY updated_at DESC, id DESC",
                (status,),
            )
        else:
            cursor.execute("SELECT * FROM candidate_pool ORDER BY updated_at DESC, id DESC")

        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def add_signal(self, signal: dict[str, Any]) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO strategy_signals
            (candidate_id, stock_code, stock_name, action, confidence, reasoning,
             position_size_pct, stop_loss_pct, take_profit_pct, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.get("candidate_id"),
                signal["stock_code"],
                signal.get("stock_name"),
                signal["action"],
                signal.get("confidence", 0),
                signal.get("reasoning"),
                signal.get("position_size_pct", 0),
                signal.get("stop_loss_pct", 0),
                signal.get("take_profit_pct", 0),
                signal.get("status", "observed"),
                self._now(),
            ),
        )
        signal_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return signal_id

    def get_signals(self, stock_code: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        if stock_code:
            cursor.execute(
                """
                SELECT * FROM strategy_signals
                WHERE stock_code = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (stock_code, limit),
            )
        else:
            cursor.execute("SELECT * FROM strategy_signals ORDER BY id DESC LIMIT ?", (limit,))
        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_pending_signals(self) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM strategy_signals
            WHERE status = 'pending'
            ORDER BY updated_at DESC, id DESC
            """
        )
        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def delay_signal(self, signal_id: int, note: str | None = None) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE strategy_signals
            SET delay_count = delay_count + 1,
                execution_note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (note, self._now(), signal_id),
        )
        conn.commit()
        conn.close()

    def ignore_signal(self, signal_id: int, note: str | None = None) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE strategy_signals
            SET status = 'ignored',
                execution_note = ?,
                updated_at = ?,
                executed_at = ?
            WHERE id = ?
            """,
            (note, self._now(), self._now(), signal_id),
        )
        conn.commit()
        conn.close()

    def confirm_signal(
        self,
        signal_id: int,
        executed_action: str,
        price: float,
        quantity: int,
        note: str | None = None,
    ) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM strategy_signals WHERE id = ?", (signal_id,))
        signal = cursor.fetchone()
        if signal is None:
            conn.close()
            raise ValueError(f"Signal not found: {signal_id}")

        executed_at = self._now()
        cursor.execute(
            """
            UPDATE strategy_signals
            SET status = 'executed',
                executed_action = ?,
                execution_note = ?,
                updated_at = ?,
                executed_at = ?
            WHERE id = ?
            """,
            (executed_action, note, executed_at, executed_at, signal_id),
        )

        if executed_action.lower() == "buy":
            self._apply_buy(
                cursor=cursor,
                stock_code=signal["stock_code"],
                stock_name=signal["stock_name"],
                price=price,
                quantity=quantity,
                executed_at=executed_at,
            )
        elif executed_action.lower() == "sell":
            self._apply_sell(
                cursor=cursor,
                stock_code=signal["stock_code"],
                price=price,
                quantity=quantity,
                executed_at=executed_at,
            )
        else:
            conn.close()
            raise ValueError(f"Unsupported executed_action: {executed_action}")

        conn.commit()
        conn.close()

    def get_positions(self, status: str = "holding") -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sim_positions
            WHERE status = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (status,),
        )
        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def _apply_buy(
        self,
        cursor: sqlite3.Cursor,
        stock_code: str,
        stock_name: str,
        price: float,
        quantity: int,
        executed_at: str,
    ) -> None:
        cursor.execute("SELECT * FROM sim_positions WHERE stock_code = ?", (stock_code,))
        position = cursor.fetchone()
        market_value = round(price * quantity, 4)

        if position:
            new_quantity = int(position["quantity"]) + quantity
            total_cost = float(position["avg_price"]) * int(position["quantity"]) + market_value
            avg_price = round(total_cost / new_quantity, 4)
            cursor.execute(
                """
                UPDATE sim_positions
                SET stock_name = ?, quantity = ?, avg_price = ?, latest_price = ?,
                    market_value = ?, unrealized_pnl = 0, unrealized_pnl_pct = 0,
                    status = 'holding', updated_at = ?
                WHERE stock_code = ?
                """,
                (
                    stock_name,
                    new_quantity,
                    avg_price,
                    price,
                    round(new_quantity * price, 4),
                    executed_at,
                    stock_code,
                ),
            )
            position_id = int(position["id"])
        else:
            cursor.execute(
                """
                INSERT INTO sim_positions
                (stock_code, stock_name, quantity, avg_price, latest_price, market_value,
                 unrealized_pnl, unrealized_pnl_pct, status, opened_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 'holding', ?, ?)
                """,
                (stock_code, stock_name, quantity, price, price, market_value, executed_at, executed_at),
            )
            position_id = int(cursor.lastrowid)

        unlock_date = (datetime.fromisoformat(executed_at) + timedelta(days=1)).date().isoformat()
        cursor.execute(
            """
            INSERT INTO sim_position_lots
            (position_id, stock_code, quantity, remaining_quantity, entry_price, entry_time, unlock_date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'locked')
            """,
            (position_id, stock_code, quantity, quantity, price, executed_at, unlock_date),
        )

    def _apply_sell(
        self,
        cursor: sqlite3.Cursor,
        stock_code: str,
        price: float,
        quantity: int,
        executed_at: str,
    ) -> None:
        cursor.execute("SELECT * FROM sim_positions WHERE stock_code = ?", (stock_code,))
        position = cursor.fetchone()
        if position is None:
            raise ValueError(f"Position not found for sell: {stock_code}")

        current_quantity = int(position["quantity"])
        remaining_quantity = max(current_quantity - quantity, 0)
        status = "holding" if remaining_quantity > 0 else "closed"
        market_value = round(remaining_quantity * price, 4)
        cursor.execute(
            """
            UPDATE sim_positions
            SET quantity = ?, latest_price = ?, market_value = ?, status = ?, updated_at = ?
            WHERE stock_code = ?
            """,
            (remaining_quantity, price, market_value, status, executed_at, stock_code),
        )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    @staticmethod
    def _now() -> str:
        return datetime.now().replace(microsecond=0).isoformat(sep=" ")
