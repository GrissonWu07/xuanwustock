"""SQLite persistence for the quant simulation workflow."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from quant_sim.stockpolicy_core import LotStatus, PositionLot


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
            CREATE TABLE IF NOT EXISTS candidate_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(candidate_id, source),
                FOREIGN KEY(candidate_id) REFERENCES candidate_pool(id)
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
                decision_type TEXT,
                tech_score REAL DEFAULT 0,
                context_score REAL DEFAULT 0,
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
                lot_id TEXT,
                stock_code TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                entry_date TEXT,
                unlock_date TEXT NOT NULL,
                status TEXT DEFAULT 'locked',
                closed_at TEXT,
                FOREIGN KEY(position_id) REFERENCES sim_positions(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                initial_cash REAL NOT NULL DEFAULT 100000,
                available_cash REAL NOT NULL DEFAULT 100000,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                action TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                amount REAL NOT NULL,
                realized_pnl REAL DEFAULT 0,
                note TEXT,
                executed_at TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_reason TEXT NOT NULL,
                initial_cash REAL NOT NULL,
                available_cash REAL NOT NULL,
                market_value REAL NOT NULL,
                total_equity REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_scheduler_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER DEFAULT 0,
                interval_minutes INTEGER DEFAULT 15,
                trading_hours_only INTEGER DEFAULT 1,
                market TEXT DEFAULT 'CN',
                last_run_at TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self._ensure_column(cursor, "strategy_signals", "decision_type", "TEXT")
        self._ensure_column(cursor, "strategy_signals", "tech_score", "REAL DEFAULT 0")
        self._ensure_column(cursor, "strategy_signals", "context_score", "REAL DEFAULT 0")
        self._ensure_column(cursor, "sim_position_lots", "lot_id", "TEXT")
        self._ensure_column(cursor, "sim_position_lots", "entry_date", "TEXT")
        self._ensure_column(cursor, "sim_position_lots", "closed_at", "TEXT")

        self._backfill_candidate_sources(cursor)
        self._backfill_lot_defaults(cursor)
        self._ensure_sim_account(cursor)
        self._ensure_scheduler_config(cursor)

        conn.commit()
        conn.close()

    def add_candidate(self, candidate: dict[str, Any]) -> int:
        payload = {
            "stock_code": str(candidate["stock_code"]).strip(),
            "stock_name": candidate.get("stock_name"),
            "source": candidate.get("source", "manual"),
            "latest_price": float(candidate.get("latest_price") or 0),
            "notes": candidate.get("notes"),
            "metadata": candidate.get("metadata", {}) or {},
            "status": candidate.get("status", "active"),
        }

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM candidate_pool WHERE stock_code = ?", (payload["stock_code"],))
        existing = cursor.fetchone()

        if existing:
            existing_metadata = self._loads_metadata(existing["metadata_json"])
            merged_metadata = {**existing_metadata, **payload["metadata"]}
            next_status = self._merge_candidate_status(existing["status"], payload["status"])
            next_price = payload["latest_price"] if payload["latest_price"] > 0 else float(existing["latest_price"] or 0)
            cursor.execute(
                """
                UPDATE candidate_pool
                SET stock_name = ?, latest_price = ?, notes = ?, metadata_json = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["stock_name"] or existing["stock_name"],
                    next_price,
                    payload["notes"] or existing["notes"],
                    json.dumps(merged_metadata, ensure_ascii=False),
                    next_status,
                    self._now(),
                    int(existing["id"]),
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
                    json.dumps(payload["metadata"], ensure_ascii=False),
                    payload["status"],
                    self._now(),
                ),
            )
            candidate_id = int(cursor.lastrowid)

        self._attach_candidate_source(cursor, candidate_id, payload["source"])

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

        rows = [self._candidate_row_to_dict(cursor, row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_candidate(self, stock_code: str) -> Optional[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM candidate_pool WHERE stock_code = ?", (stock_code,))
        row = cursor.fetchone()
        if row is None:
            conn.close()
            return None
        payload = self._candidate_row_to_dict(cursor, row)
        conn.close()
        return payload

    def add_signal(self, signal: dict[str, Any]) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        status = signal.get("status", "observed")
        action = str(signal["action"]).upper()

        if status == "pending":
            cursor.execute(
                """
                UPDATE strategy_signals
                SET status = 'superseded',
                    updated_at = ?
                WHERE stock_code = ? AND status = 'pending' AND action <> ?
                """,
                (self._now(), signal["stock_code"], action),
            )
            cursor.execute(
                """
                SELECT id FROM strategy_signals
                WHERE stock_code = ? AND action = ? AND status = 'pending'
                ORDER BY id DESC
                LIMIT 1
                """,
                (signal["stock_code"], action),
            )
            existing = cursor.fetchone()
            if existing is not None:
                signal_id = int(existing["id"])
                cursor.execute(
                    """
                    UPDATE strategy_signals
                    SET candidate_id = ?, stock_name = ?, confidence = ?, reasoning = ?,
                        position_size_pct = ?, stop_loss_pct = ?, take_profit_pct = ?,
                        decision_type = ?, tech_score = ?, context_score = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        signal.get("candidate_id"),
                        signal.get("stock_name"),
                        signal.get("confidence", 0),
                        signal.get("reasoning"),
                        signal.get("position_size_pct", 0),
                        signal.get("stop_loss_pct", 0),
                        signal.get("take_profit_pct", 0),
                        signal.get("decision_type"),
                        signal.get("tech_score", 0),
                        signal.get("context_score", 0),
                        self._now(),
                        signal_id,
                    ),
                )
                conn.commit()
                conn.close()
                return signal_id

        cursor.execute(
            """
            INSERT INTO strategy_signals
            (
                candidate_id, stock_code, stock_name, action, confidence, reasoning,
                position_size_pct, stop_loss_pct, take_profit_pct, decision_type,
                tech_score, context_score, status, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.get("candidate_id"),
                signal["stock_code"],
                signal.get("stock_name"),
                action,
                signal.get("confidence", 0),
                signal.get("reasoning"),
                signal.get("position_size_pct", 0),
                signal.get("stop_loss_pct", 0),
                signal.get("take_profit_pct", 0),
                signal.get("decision_type"),
                signal.get("tech_score", 0),
                signal.get("context_score", 0),
                status,
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

    def configure_account(self, initial_cash: float) -> None:
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")

        summary = self.get_account_summary()
        if summary["trade_count"] > 0 or summary["position_count"] > 0:
            raise ValueError("account can only be reconfigured before trading starts")

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE sim_account
            SET initial_cash = ?, available_cash = ?, updated_at = ?
            WHERE id = 1
            """,
            (round(initial_cash, 4), round(initial_cash, 4), self._now()),
        )
        conn.commit()
        conn.close()

    def get_account_summary(self) -> dict[str, Any]:
        conn = self._connect()
        cursor = conn.cursor()
        summary = self._build_account_summary(cursor)
        conn.close()
        return summary

    def add_account_snapshot(self, run_reason: str) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        snapshot_id = self._insert_account_snapshot(cursor, run_reason)
        conn.commit()
        conn.close()
        return snapshot_id

    def get_account_snapshots(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM sim_account_snapshots ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_trade_history(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM sim_trades ORDER BY executed_at DESC, id DESC LIMIT ?",
            (limit,),
        )
        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_scheduler_config(self) -> dict[str, Any]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sim_scheduler_config WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        return {
            "enabled": bool(row["enabled"]),
            "interval_minutes": int(row["interval_minutes"]),
            "trading_hours_only": bool(row["trading_hours_only"]),
            "market": row["market"] or "CN",
            "last_run_at": row["last_run_at"],
            "updated_at": row["updated_at"],
        }

    def update_scheduler_config(
        self,
        *,
        enabled: Optional[bool] = None,
        interval_minutes: Optional[int] = None,
        trading_hours_only: Optional[bool] = None,
        market: Optional[str] = None,
        last_run_at: Optional[str] = None,
    ) -> None:
        existing = self.get_scheduler_config()
        payload = {
            "enabled": int(existing["enabled"] if enabled is None else enabled),
            "interval_minutes": int(existing["interval_minutes"] if interval_minutes is None else interval_minutes),
            "trading_hours_only": int(existing["trading_hours_only"] if trading_hours_only is None else trading_hours_only),
            "market": existing["market"] if market is None else str(market),
            "last_run_at": existing["last_run_at"] if last_run_at is None else last_run_at,
        }
        if payload["interval_minutes"] <= 0:
            raise ValueError("interval_minutes must be positive")

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE sim_scheduler_config
            SET enabled = ?, interval_minutes = ?, trading_hours_only = ?,
                market = ?, last_run_at = ?, updated_at = ?
            WHERE id = 1
            """,
            (
                payload["enabled"],
                payload["interval_minutes"],
                payload["trading_hours_only"],
                payload["market"],
                payload["last_run_at"],
                self._now(),
            ),
        )
        conn.commit()
        conn.close()

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
        executed_at: str | datetime | None = None,
    ) -> None:
        self._validate_trade_inputs(price=price, quantity=quantity)

        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM strategy_signals WHERE id = ?", (signal_id,))
            signal = cursor.fetchone()
            if signal is None:
                raise ValueError(f"Signal not found: {signal_id}")

            executed_dt = self._ensure_datetime(executed_at)
            executed_at_text = self._format_datetime(executed_dt)
            action = executed_action.lower()

            if action == "buy":
                trade_result = self._apply_buy(
                    cursor=cursor,
                    stock_code=signal["stock_code"],
                    stock_name=signal["stock_name"],
                    price=price,
                    quantity=quantity,
                    executed_at=executed_dt,
                )
            elif action == "sell":
                trade_result = self._apply_sell(
                    cursor=cursor,
                    stock_code=signal["stock_code"],
                    price=price,
                    quantity=quantity,
                    executed_at=executed_dt,
                )
            else:
                raise ValueError(f"Unsupported executed_action: {executed_action}")

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
                (action, note, executed_at_text, executed_at_text, signal_id),
            )
            self._set_candidate_status(cursor, signal["stock_code"], trade_result["candidate_status"])
            self._record_trade(
                cursor=cursor,
                signal_id=signal_id,
                stock_code=signal["stock_code"],
                stock_name=signal["stock_name"],
                action=action,
                price=price,
                quantity=quantity,
                amount=trade_result["amount"],
                realized_pnl=trade_result["realized_pnl"],
                note=note,
                executed_at=executed_at_text,
            )
            self._insert_account_snapshot(cursor, f"manual_{action}")

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_positions(
        self,
        status: str = "holding",
        as_of: str | datetime | None = None,
    ) -> list[dict[str, Any]]:
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
        current_date = self._ensure_datetime(as_of).date()
        rows = []
        for row in cursor.fetchall():
            payload = self._row_to_dict(row)
            lots = self._load_open_lots(cursor, payload["stock_code"])
            metrics = self._lot_metrics(lots, current_date)
            payload.update(metrics)
            rows.append(payload)
        conn.close()
        return rows

    def get_position_lots(
        self,
        stock_code: str,
        as_of: str | datetime | None = None,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        current_date = self._ensure_datetime(as_of).date()
        cursor.execute(
            """
            SELECT * FROM sim_position_lots
            WHERE stock_code = ? AND remaining_quantity > 0
            ORDER BY entry_time ASC, id ASC
            """,
            (stock_code,),
        )
        rows = []
        for row in cursor.fetchall():
            payload = self._row_to_dict(row)
            lot = self._lot_from_row(row)
            payload["status"] = self._current_lot_status(lot, current_date)
            payload["is_sellable"] = lot.is_available(current_date)
            rows.append(payload)
        conn.close()
        return rows

    def update_position_market_price(self, stock_code: str, latest_price: float) -> None:
        if latest_price <= 0:
            return

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sim_positions WHERE stock_code = ? AND status = 'holding'", (stock_code,))
        position = cursor.fetchone()
        if position is None:
            conn.close()
            return

        quantity = int(position["quantity"] or 0)
        avg_price = float(position["avg_price"] or 0)
        market_value = round(quantity * latest_price, 4)
        unrealized_pnl = round((latest_price - avg_price) * quantity, 4)
        unrealized_pnl_pct = round(((latest_price - avg_price) / avg_price * 100) if avg_price > 0 else 0, 4)
        cursor.execute(
            """
            UPDATE sim_positions
            SET latest_price = ?, market_value = ?, unrealized_pnl = ?,
                unrealized_pnl_pct = ?, updated_at = ?
            WHERE stock_code = ?
            """,
            (latest_price, market_value, unrealized_pnl, unrealized_pnl_pct, self._now(), stock_code),
        )
        conn.commit()
        conn.close()

    def update_candidate_latest_price(self, stock_code: str, latest_price: float) -> None:
        if latest_price <= 0:
            return

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE candidate_pool
            SET latest_price = ?, updated_at = ?
            WHERE stock_code = ?
            """,
            (latest_price, self._now(), stock_code),
        )
        conn.commit()
        conn.close()

    def _apply_buy(
        self,
        cursor: sqlite3.Cursor,
        stock_code: str,
        stock_name: str,
        price: float,
        quantity: int,
        executed_at: datetime,
    ) -> dict[str, Any]:
        executed_at_text = self._format_datetime(executed_at)
        amount = round(price * quantity, 4)
        available_cash = self._get_available_cash(cursor)
        if amount > available_cash:
            raise ValueError("insufficient available cash")

        cursor.execute("SELECT * FROM sim_positions WHERE stock_code = ?", (stock_code,))
        position = cursor.fetchone()

        if position:
            current_quantity = int(position["quantity"])
            new_quantity = current_quantity + quantity
            total_cost = float(position["avg_price"]) * current_quantity + price * quantity
            avg_price = round(total_cost / new_quantity, 4)
            market_value = round(new_quantity * price, 4)
            cursor.execute(
                """
                UPDATE sim_positions
                SET stock_name = ?, quantity = ?, avg_price = ?, latest_price = ?,
                    market_value = ?, unrealized_pnl = ?, unrealized_pnl_pct = ?,
                    status = 'holding', updated_at = ?
                WHERE stock_code = ?
                """,
                (
                    stock_name or position["stock_name"],
                    new_quantity,
                    avg_price,
                    price,
                    market_value,
                    round((price - avg_price) * new_quantity, 4),
                    round(((price - avg_price) / avg_price * 100) if avg_price > 0 else 0, 4),
                    executed_at_text,
                    stock_code,
                ),
            )
            position_id = int(position["id"])
        else:
            market_value = round(quantity * price, 4)
            cursor.execute(
                """
                INSERT INTO sim_positions
                (
                    stock_code, stock_name, quantity, avg_price, latest_price,
                    market_value, unrealized_pnl, unrealized_pnl_pct, status, opened_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 'holding', ?, ?)
                """,
                (stock_code, stock_name, quantity, price, price, market_value, executed_at_text, executed_at_text),
            )
            position_id = int(cursor.lastrowid)

        unlock_date = (executed_at.date() + timedelta(days=1)).isoformat()
        cursor.execute(
            """
            INSERT INTO sim_position_lots
            (
                position_id, lot_id, stock_code, quantity, remaining_quantity, entry_price,
                entry_time, entry_date, unlock_date, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'locked')
            """,
            (
                position_id,
                self._build_lot_id(stock_code),
                stock_code,
                quantity,
                quantity,
                price,
                executed_at_text,
                executed_at.date().isoformat(),
                unlock_date,
            ),
        )
        self._set_available_cash(cursor, available_cash - amount)
        return {
            "candidate_status": "holding",
            "amount": amount,
            "realized_pnl": 0.0,
        }

    def _apply_sell(
        self,
        cursor: sqlite3.Cursor,
        stock_code: str,
        price: float,
        quantity: int,
        executed_at: datetime,
    ) -> dict[str, Any]:
        cursor.execute("SELECT * FROM sim_positions WHERE stock_code = ?", (stock_code,))
        position = cursor.fetchone()
        if position is None:
            raise ValueError(f"Position not found for sell: {stock_code}")

        current_quantity = int(position["quantity"])
        if quantity > current_quantity:
            raise ValueError("sell quantity exceeds position quantity")

        current_date = executed_at.date()
        lots = self._load_open_lots(cursor, stock_code)
        sellable_quantity = self._lot_metrics(lots, current_date)["sellable_quantity"]
        if quantity > sellable_quantity:
            raise ValueError("sell quantity exceeds sellable quantity")

        remaining_to_sell = quantity
        executed_at_text = self._format_datetime(executed_at)
        realized_pnl = 0.0
        for row, lot in lots:
            if remaining_to_sell <= 0:
                break
            if not lot.is_available(current_date):
                continue

            consumed = lot.consume(remaining_to_sell)
            remaining_to_sell -= consumed
            realized_pnl += round((price - lot.entry_price) * consumed, 4)
            next_status = "closed" if lot.remaining_quantity == 0 else self._current_lot_status(lot, current_date)
            cursor.execute(
                """
                UPDATE sim_position_lots
                SET remaining_quantity = ?, status = ?, closed_at = ?
                WHERE id = ?
                """,
                (
                    lot.remaining_quantity,
                    next_status,
                    executed_at_text if lot.remaining_quantity == 0 else None,
                    int(row["id"]),
                ),
            )

        if remaining_to_sell != 0:
            raise ValueError("sell quantity could not be matched to lots")

        remaining_quantity = current_quantity - quantity
        cursor.execute(
            """
            SELECT SUM(remaining_quantity * entry_price) AS remaining_cost
            FROM sim_position_lots
            WHERE stock_code = ? AND remaining_quantity > 0
            """,
            (stock_code,),
        )
        remaining_cost = float(cursor.fetchone()["remaining_cost"] or 0)
        proceeds = round(price * quantity, 4)
        self._set_available_cash(cursor, self._get_available_cash(cursor) + proceeds)

        if remaining_quantity > 0:
            avg_price = round(remaining_cost / remaining_quantity, 4)
            market_value = round(remaining_quantity * price, 4)
            cursor.execute(
                """
                UPDATE sim_positions
                SET quantity = ?, avg_price = ?, latest_price = ?, market_value = ?,
                    unrealized_pnl = ?, unrealized_pnl_pct = ?, status = 'holding', updated_at = ?
                WHERE stock_code = ?
                """,
                (
                    remaining_quantity,
                    avg_price,
                    price,
                    market_value,
                    round((price - avg_price) * remaining_quantity, 4),
                    round(((price - avg_price) / avg_price * 100) if avg_price > 0 else 0, 4),
                    executed_at_text,
                    stock_code,
                ),
            )
            return {
                "candidate_status": "holding",
                "amount": proceeds,
                "realized_pnl": round(realized_pnl, 4),
            }

        cursor.execute(
            """
            UPDATE sim_positions
            SET quantity = 0, latest_price = ?, market_value = 0,
                unrealized_pnl = 0, unrealized_pnl_pct = 0,
                status = 'closed', updated_at = ?
            WHERE stock_code = ?
            """,
            (price, executed_at_text, stock_code),
        )
        return {
            "candidate_status": "active",
            "amount": proceeds,
            "realized_pnl": round(realized_pnl, 4),
        }

    def _build_account_summary(self, cursor: sqlite3.Cursor) -> dict[str, Any]:
        cursor.execute("SELECT * FROM sim_account WHERE id = 1")
        account = cursor.fetchone()
        initial_cash = float(account["initial_cash"])
        available_cash = float(account["available_cash"])

        cursor.execute(
            """
            SELECT
                COALESCE(SUM(quantity * avg_price), 0) AS invested_cost,
                COALESCE(SUM(market_value), 0) AS market_value,
                COALESCE(SUM(unrealized_pnl), 0) AS unrealized_pnl,
                COUNT(*) AS position_count
            FROM sim_positions
            WHERE status = 'holding'
            """
        )
        positions = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                COALESCE(SUM(realized_pnl), 0) AS realized_pnl,
                COUNT(*) AS trade_count
            FROM sim_trades
            """
        )
        trades = cursor.fetchone()

        market_value = float(positions["market_value"] or 0)
        total_equity = round(available_cash + market_value, 4)

        return {
            "initial_cash": round(initial_cash, 4),
            "available_cash": round(available_cash, 4),
            "invested_cost": round(float(positions["invested_cost"] or 0), 4),
            "market_value": round(market_value, 4),
            "total_equity": total_equity,
            "realized_pnl": round(float(trades["realized_pnl"] or 0), 4),
            "unrealized_pnl": round(float(positions["unrealized_pnl"] or 0), 4),
            "total_pnl": round(total_equity - initial_cash, 4),
            "total_return_pct": round(((total_equity - initial_cash) / initial_cash * 100) if initial_cash > 0 else 0, 4),
            "position_count": int(positions["position_count"] or 0),
            "trade_count": int(trades["trade_count"] or 0),
        }

    def _insert_account_snapshot(self, cursor: sqlite3.Cursor, run_reason: str) -> int:
        summary = self._build_account_summary(cursor)
        cursor.execute(
            """
            INSERT INTO sim_account_snapshots
            (
                run_reason, initial_cash, available_cash, market_value,
                total_equity, realized_pnl, unrealized_pnl, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_reason,
                summary["initial_cash"],
                summary["available_cash"],
                summary["market_value"],
                summary["total_equity"],
                summary["realized_pnl"],
                summary["unrealized_pnl"],
                self._now(),
            ),
        )
        return int(cursor.lastrowid)

    def _record_trade(
        self,
        cursor: sqlite3.Cursor,
        signal_id: int,
        stock_code: str,
        stock_name: str | None,
        action: str,
        price: float,
        quantity: int,
        amount: float,
        realized_pnl: float,
        note: str | None,
        executed_at: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO sim_trades
            (
                signal_id, stock_code, stock_name, action, price, quantity,
                amount, realized_pnl, note, executed_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_id,
                stock_code,
                stock_name,
                action,
                price,
                quantity,
                amount,
                realized_pnl,
                note,
                executed_at,
                self._now(),
            ),
        )

    def _ensure_sim_account(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("SELECT 1 FROM sim_account WHERE id = 1")
        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO sim_account (id, initial_cash, available_cash, updated_at)
                VALUES (1, 100000, 100000, ?)
                """,
                (self._now(),),
            )

    def _ensure_scheduler_config(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("SELECT 1 FROM sim_scheduler_config WHERE id = 1")
        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO sim_scheduler_config
                (id, enabled, interval_minutes, trading_hours_only, market, last_run_at, updated_at)
                VALUES (1, 0, 15, 1, 'CN', NULL, ?)
                """,
                (self._now(),),
            )

    def _get_available_cash(self, cursor: sqlite3.Cursor) -> float:
        cursor.execute("SELECT available_cash FROM sim_account WHERE id = 1")
        row = cursor.fetchone()
        return float(row["available_cash"] or 0)

    def _set_available_cash(self, cursor: sqlite3.Cursor, value: float) -> None:
        cursor.execute(
            """
            UPDATE sim_account
            SET available_cash = ?, updated_at = ?
            WHERE id = 1
            """,
            (round(value, 4), self._now()),
        )

    def _candidate_row_to_dict(self, cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._row_to_dict(row)
        payload["metadata"] = self._loads_metadata(payload.pop("metadata_json", None))
        payload["sources"] = self._get_candidate_sources(cursor, int(row["id"]))
        return payload

    def _get_candidate_sources(self, cursor: sqlite3.Cursor, candidate_id: int) -> list[str]:
        cursor.execute(
            """
            SELECT source FROM candidate_sources
            WHERE candidate_id = ?
            ORDER BY id ASC
            """,
            (candidate_id,),
        )
        return [row["source"] for row in cursor.fetchall()]

    def _attach_candidate_source(self, cursor: sqlite3.Cursor, candidate_id: int, source: str) -> None:
        if not source:
            return
        cursor.execute(
            """
            INSERT OR IGNORE INTO candidate_sources (candidate_id, source, created_at)
            VALUES (?, ?, ?)
            """,
            (candidate_id, source, self._now()),
        )

    def _set_candidate_status(self, cursor: sqlite3.Cursor, stock_code: str, status: str) -> None:
        cursor.execute(
            """
            UPDATE candidate_pool
            SET status = ?, updated_at = ?
            WHERE stock_code = ?
            """,
            (status, self._now(), stock_code),
        )

    def _load_open_lots(
        self,
        cursor: sqlite3.Cursor,
        stock_code: str,
    ) -> list[tuple[sqlite3.Row, PositionLot]]:
        cursor.execute(
            """
            SELECT * FROM sim_position_lots
            WHERE stock_code = ? AND remaining_quantity > 0
            ORDER BY entry_time ASC, id ASC
            """,
            (stock_code,),
        )
        return [(row, self._lot_from_row(row)) for row in cursor.fetchall()]

    def _lot_from_row(self, row: sqlite3.Row) -> PositionLot:
        raw_status = str(row["status"] or "locked").upper()
        if raw_status not in LotStatus.__members__:
            raw_status = "LOCKED"

        entry_time = self._ensure_datetime(row["entry_time"])
        entry_date_text = row["entry_date"] or entry_time.date().isoformat()
        unlock_date = date.fromisoformat(row["unlock_date"])
        return PositionLot(
            lot_id=row["lot_id"] or f"lot-{row['id']}",
            entry_time=entry_time,
            entry_date=date.fromisoformat(entry_date_text),
            original_quantity=int(row["quantity"]),
            remaining_quantity=int(row["remaining_quantity"]),
            entry_price=float(row["entry_price"]),
            status=LotStatus[raw_status],
            unlock_date=unlock_date,
        )

    def _lot_metrics(
        self,
        lots: list[tuple[sqlite3.Row, PositionLot]],
        current_date: date,
    ) -> dict[str, int]:
        sellable_quantity = 0
        locked_quantity = 0
        for _, lot in lots:
            if lot.is_available(current_date):
                sellable_quantity += lot.remaining_quantity
            else:
                locked_quantity += lot.remaining_quantity
        return {
            "sellable_quantity": sellable_quantity,
            "locked_quantity": locked_quantity,
        }

    @staticmethod
    def _current_lot_status(lot: PositionLot, current_date: date) -> str:
        if lot.remaining_quantity <= 0:
            return "closed"
        if lot.is_available(current_date):
            return "available"
        return "locked"

    @staticmethod
    def _validate_trade_inputs(price: float, quantity: int) -> None:
        if price <= 0:
            raise ValueError("price must be positive")
        if quantity <= 0:
            raise ValueError("quantity must be positive")

    @staticmethod
    def _merge_candidate_status(existing_status: str, new_status: str) -> str:
        if existing_status == "holding" and new_status == "active":
            return existing_status
        return new_status or existing_status

    @staticmethod
    def _build_lot_id(stock_code: str) -> str:
        return f"{stock_code}-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _loads_metadata(payload: Optional[str]) -> dict[str, Any]:
        if not payload:
            return {}
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _ensure_column(cursor: sqlite3.Cursor, table_name: str, column_name: str, definition: str) -> None:
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing = {row["name"] for row in cursor.fetchall()}
        if column_name not in existing:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _backfill_candidate_sources(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("SELECT id, source FROM candidate_pool")
        for row in cursor.fetchall():
            self._attach_candidate_source(cursor, int(row["id"]), row["source"])

    def _backfill_lot_defaults(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("SELECT id, stock_code, entry_time, entry_date, lot_id FROM sim_position_lots")
        for row in cursor.fetchall():
            entry_time = self._ensure_datetime(row["entry_time"])
            entry_date = row["entry_date"] or entry_time.date().isoformat()
            lot_id = row["lot_id"] or f"{row['stock_code']}-{row['id']}"
            cursor.execute(
                """
                UPDATE sim_position_lots
                SET lot_id = ?, entry_date = ?
                WHERE id = ?
                """,
                (lot_id, entry_date, int(row["id"])),
            )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    @staticmethod
    def _ensure_datetime(value: str | datetime | None) -> datetime:
        if value is None:
            return datetime.now().replace(microsecond=0)
        if isinstance(value, datetime):
            return value.replace(microsecond=0)
        return datetime.fromisoformat(str(value).replace("T", " ")).replace(microsecond=0)

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        return value.replace(microsecond=0).isoformat(sep=" ")

    @staticmethod
    def _now() -> str:
        return QuantSimDB._format_datetime(datetime.now())
