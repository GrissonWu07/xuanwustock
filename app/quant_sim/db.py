"""SQLite persistence for the quant simulation workflow."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from app.quant_kernel.config import StrategyScoringConfig
from app.quant_kernel.replay_engine import ReplayTimepointGenerator
from app.quant_kernel.portfolio_engine import LotStatus, PositionLot
from app.runtime_paths import default_db_path


DEFAULT_DB_FILE = str(default_db_path("quant_sim.db"))
TRADING_DAY_CALENDAR = ReplayTimepointGenerator()
DEFAULT_ANALYSIS_TIMEFRAME = "30m"
SUPPORTED_ANALYSIS_TIMEFRAMES = {"30m", "1d", "1d+30m"}
DEFAULT_STRATEGY_MODE = "auto"
SUPPORTED_STRATEGY_MODES = {"auto", "aggressive", "neutral", "defensive"}
DEFAULT_COMMISSION_RATE = 0.0003
DEFAULT_SELL_TAX_RATE = 0.001
DEFAULT_AI_DYNAMIC_STRATEGY = "off"
SUPPORTED_AI_DYNAMIC_STRATEGIES = {"off", "template", "weights", "hybrid"}
DEFAULT_AI_DYNAMIC_STRENGTH = 0.5
DEFAULT_AI_DYNAMIC_LOOKBACK = 48
DEFAULT_STRATEGY_PROFILE_ID = "aggressive_v23"
DEFAULT_STRATEGY_PROFILE_NAME = "积极"
LEGACY_DEFAULT_STRATEGY_PROFILE_ID = "default_v23"
BUILTIN_STRATEGY_PROFILES: tuple[dict[str, str], ...] = (
    {
        "id": "aggressive_v23",
        "name": "积极",
        "description": "积极策略：技术轨权重更高，趋势/动量更敏感，买入阈值更低，适合进攻型交易。",
        "variant": "aggressive",
    },
    {
        "id": "stable_v23",
        "name": "稳定",
        "description": "稳定策略：技术与环境均衡，阈值居中，兼顾收益与回撤控制。",
        "variant": "stable",
    },
    {
        "id": "conservative_v23",
        "name": "保守",
        "description": "保守策略：环境与风控约束更强，买入阈值更高，优先控制回撤与仓位风险。",
        "variant": "conservative",
    },
)


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
                auto_execute INTEGER DEFAULT 0,
                interval_minutes INTEGER DEFAULT 15,
                trading_hours_only INTEGER DEFAULT 1,
                analysis_timeframe TEXT DEFAULT '30m',
                strategy_mode TEXT DEFAULT 'auto',
                strategy_profile_id TEXT,
                ai_dynamic_strategy TEXT DEFAULT 'off',
                ai_dynamic_strength REAL DEFAULT 0.5,
                ai_dynamic_lookback INTEGER DEFAULT 48,
                start_date TEXT,
                market TEXT DEFAULT 'CN',
                commission_rate REAL DEFAULT 0.0003,
                sell_tax_rate REAL DEFAULT 0.001,
                last_run_at TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                timeframe TEXT NOT NULL,
                market TEXT NOT NULL DEFAULT 'CN',
                auto_execute INTEGER DEFAULT 1,
                handoff_to_live INTEGER DEFAULT 0,
                start_datetime TEXT NOT NULL,
                end_datetime TEXT NOT NULL,
                initial_cash REAL NOT NULL,
                final_equity REAL DEFAULT 0,
                total_return_pct REAL DEFAULT 0,
                max_drawdown_pct REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                trade_count INTEGER DEFAULT 0,
                checkpoint_count INTEGER DEFAULT 0,
                progress_current INTEGER DEFAULT 0,
                progress_total INTEGER DEFAULT 0,
                latest_checkpoint_at TEXT,
                status_message TEXT,
                cancel_requested INTEGER DEFAULT 0,
                worker_pid INTEGER,
                selected_strategy_profile_id TEXT,
                selected_strategy_profile_name TEXT,
                selected_strategy_profile_version_id INTEGER,
                strategy_profile_snapshot_json TEXT,
                metadata_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                enabled INTEGER DEFAULT 1,
                is_default INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_profile_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                config_json TEXT NOT NULL,
                note TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(profile_id, version),
                FOREIGN KEY(profile_id) REFERENCES strategy_profiles(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_run_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                checkpoint_at TEXT NOT NULL,
                candidates_scanned INTEGER DEFAULT 0,
                positions_checked INTEGER DEFAULT 0,
                signals_created INTEGER DEFAULT 0,
                auto_executed INTEGER DEFAULT 0,
                available_cash REAL DEFAULT 0,
                market_value REAL DEFAULT 0,
                total_equity REAL DEFAULT 0,
                metadata_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES sim_runs(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_run_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES sim_runs(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_run_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                run_reason TEXT NOT NULL,
                initial_cash REAL NOT NULL,
                available_cash REAL NOT NULL,
                market_value REAL NOT NULL,
                total_equity REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES sim_runs(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_run_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                quantity INTEGER DEFAULT 0,
                avg_price REAL DEFAULT 0,
                latest_price REAL DEFAULT 0,
                market_value REAL DEFAULT 0,
                unrealized_pnl REAL DEFAULT 0,
                sellable_quantity INTEGER DEFAULT 0,
                locked_quantity INTEGER DEFAULT 0,
                status TEXT DEFAULT 'holding',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES sim_runs(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_run_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                action TEXT NOT NULL,
                confidence INTEGER DEFAULT 0,
                reasoning TEXT,
                position_size_pct REAL DEFAULT 0,
                decision_type TEXT,
                tech_score REAL DEFAULT 0,
                context_score REAL DEFAULT 0,
                strategy_profile_json TEXT,
                checkpoint_at TEXT,
                signal_status TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES sim_runs(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                message TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES sim_runs(id)
            )
            """
        )

        self._ensure_column(cursor, "strategy_signals", "decision_type", "TEXT")
        self._ensure_column(cursor, "strategy_signals", "tech_score", "REAL DEFAULT 0")
        self._ensure_column(cursor, "strategy_signals", "context_score", "REAL DEFAULT 0")
        self._ensure_column(cursor, "strategy_signals", "strategy_profile_json", "TEXT")
        self._ensure_column(cursor, "candidate_sources", "created_at", "TEXT DEFAULT CURRENT_TIMESTAMP")
        self._ensure_column(cursor, "sim_position_lots", "lot_id", "TEXT")
        self._ensure_column(cursor, "sim_position_lots", "entry_date", "TEXT")
        self._ensure_column(cursor, "sim_position_lots", "closed_at", "TEXT")
        self._ensure_column(cursor, "sim_scheduler_config", "auto_execute", "INTEGER DEFAULT 0")
        self._ensure_column(
            cursor,
            "sim_scheduler_config",
            "analysis_timeframe",
            "TEXT DEFAULT '30m'",
        )
        self._ensure_column(cursor, "sim_scheduler_config", "strategy_mode", "TEXT DEFAULT 'auto'")
        self._ensure_column(cursor, "sim_scheduler_config", "strategy_profile_id", "TEXT")
        self._ensure_column(cursor, "sim_scheduler_config", "ai_dynamic_strategy", "TEXT DEFAULT 'off'")
        self._ensure_column(cursor, "sim_scheduler_config", "ai_dynamic_strength", f"REAL DEFAULT {DEFAULT_AI_DYNAMIC_STRENGTH}")
        self._ensure_column(cursor, "sim_scheduler_config", "ai_dynamic_lookback", f"INTEGER DEFAULT {DEFAULT_AI_DYNAMIC_LOOKBACK}")
        self._ensure_column(cursor, "sim_scheduler_config", "start_date", "TEXT")
        self._ensure_column(cursor, "sim_scheduler_config", "commission_rate", f"REAL DEFAULT {DEFAULT_COMMISSION_RATE}")
        self._ensure_column(cursor, "sim_scheduler_config", "sell_tax_rate", f"REAL DEFAULT {DEFAULT_SELL_TAX_RATE}")
        self._ensure_column(cursor, "sim_runs", "progress_current", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "sim_runs", "progress_total", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "sim_runs", "status_message", "TEXT")
        self._ensure_column(cursor, "sim_runs", "cancel_requested", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "sim_runs", "worker_pid", "INTEGER")
        self._ensure_column(cursor, "sim_runs", "selected_strategy_profile_id", "TEXT")
        self._ensure_column(cursor, "sim_runs", "selected_strategy_profile_name", "TEXT")
        self._ensure_column(cursor, "sim_runs", "selected_strategy_profile_version_id", "INTEGER")
        self._ensure_column(cursor, "sim_runs", "strategy_profile_snapshot_json", "TEXT")
        self._ensure_column(cursor, "sim_run_trades", "signal_id", "INTEGER")
        self._ensure_column(cursor, "sim_run_signals", "source_signal_id", "INTEGER")

        self._backfill_candidate_sources(cursor)
        self._backfill_lot_defaults(cursor)
        self._ensure_sim_account(cursor)
        self._ensure_scheduler_config(cursor)
        self._ensure_default_strategy_profile(cursor)

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

    def delete_candidate(self, stock_code: str) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM candidate_pool WHERE stock_code = ?", (stock_code,))
        row = cursor.fetchone()
        if row is None:
            conn.close()
            return
        candidate_id = int(row["id"])
        cursor.execute("DELETE FROM candidate_sources WHERE candidate_id = ?", (candidate_id,))
        cursor.execute("DELETE FROM candidate_pool WHERE id = ?", (candidate_id,))
        conn.commit()
        conn.close()

    def delete_position(self, stock_code: str) -> bool:
        code = str(stock_code or "").strip()
        if not code:
            return False

        conn = self._connect()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT * FROM sim_positions
                WHERE stock_code = ? AND status = 'holding'
                LIMIT 1
                """,
                (code,),
            )
            position = cursor.fetchone()
            if position is None:
                return False

            quantity = int(position["quantity"] or 0)
            latest_price = float(position["latest_price"] or 0)
            if latest_price <= 0:
                latest_price = float(position["avg_price"] or 0)
            latest_price = round(max(latest_price, 0.0), 4)

            cursor.execute(
                """
                SELECT COALESCE(SUM(remaining_quantity * entry_price), 0) AS remaining_cost
                FROM sim_position_lots
                WHERE stock_code = ? AND remaining_quantity > 0
                """,
                (code,),
            )
            remaining_cost = float(cursor.fetchone()["remaining_cost"] or 0)
            proceeds = round(latest_price * max(quantity, 0), 4)
            realized_pnl = round(proceeds - remaining_cost, 4)
            executed_at_text = self._now()

            if quantity > 0 and latest_price > 0:
                self._set_available_cash(cursor, self._get_available_cash(cursor) + proceeds)
                self._record_trade(
                    cursor,
                    signal_id=0,
                    stock_code=code,
                    stock_name=position["stock_name"],
                    action="sell",
                    price=latest_price,
                    quantity=quantity,
                    amount=proceeds,
                    realized_pnl=realized_pnl,
                    note="手动删除持仓",
                    executed_at=executed_at_text,
                )

            cursor.execute(
                """
                UPDATE sim_position_lots
                SET remaining_quantity = 0, status = 'closed', closed_at = ?
                WHERE stock_code = ? AND remaining_quantity > 0
                """,
                (executed_at_text, code),
            )
            cursor.execute(
                """
                UPDATE sim_positions
                SET quantity = 0, latest_price = ?, market_value = 0,
                    unrealized_pnl = 0, unrealized_pnl_pct = 0,
                    status = 'closed', updated_at = ?
                WHERE stock_code = ?
                """,
                (latest_price, executed_at_text, code),
            )
            cursor.execute(
                """
                UPDATE candidate_pool
                SET status = 'active', updated_at = ?
                WHERE stock_code = ? AND status <> 'active'
                """,
                (executed_at_text, code),
            )
            self._insert_account_snapshot(cursor, "manual_delete_position")
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
                        decision_type = ?, tech_score = ?, context_score = ?, strategy_profile_json = ?,
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
                        self._dumps_metadata(signal.get("strategy_profile")),
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
                tech_score, context_score, strategy_profile_json, status, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                self._dumps_metadata(signal.get("strategy_profile")),
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
        rows = [self._signal_row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_signal(self, signal_id: int) -> Optional[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM strategy_signals WHERE id = ?", (signal_id,))
        row = cursor.fetchone()
        conn.close()
        return self._signal_row_to_dict(row) if row is not None else None

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
        rows = [self._signal_row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def update_signal_state(
        self,
        signal_id: int,
        *,
        action: Optional[str] = None,
        reasoning: Optional[str] = None,
        position_size_pct: Optional[float] = None,
        status: Optional[str] = None,
        execution_note: Optional[str] = None,
    ) -> None:
        updates = []
        params: list[Any] = []

        if action is not None:
            updates.append("action = ?")
            params.append(str(action).upper())
        if reasoning is not None:
            updates.append("reasoning = ?")
            params.append(reasoning)
        if position_size_pct is not None:
            updates.append("position_size_pct = ?")
            params.append(float(position_size_pct))
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if execution_note is not None:
            updates.append("execution_note = ?")
            params.append(execution_note)

        if not updates:
            return

        updates.append("updated_at = ?")
        params.append(self._now())
        params.append(signal_id)

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE strategy_signals SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        conn.close()

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
        rows = [self._signal_row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_trade_history(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM sim_trades ORDER BY executed_at DESC, id DESC LIMIT ?",
            (limit,),
        )
        rows = [self._signal_row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def create_sim_run(
        self,
        *,
        mode: str,
        timeframe: str,
        market: str,
        start_datetime: str,
        end_datetime: str,
        initial_cash: float,
        status: str = "running",
        auto_execute: bool = True,
        handoff_to_live: bool = False,
        progress_current: int = 0,
        progress_total: int = 0,
        status_message: str | None = None,
        selected_strategy_profile_id: str | None = None,
        selected_strategy_profile_name: str | None = None,
        selected_strategy_profile_version_id: int | None = None,
        strategy_profile_snapshot: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sim_runs
            (
                mode, status, timeframe, market, auto_execute, handoff_to_live,
                start_datetime, end_datetime, initial_cash, progress_current, progress_total,
                status_message, selected_strategy_profile_id, selected_strategy_profile_name,
                selected_strategy_profile_version_id, strategy_profile_snapshot_json, metadata_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mode,
                status,
                timeframe,
                market,
                int(auto_execute),
                int(handoff_to_live),
                start_datetime,
                end_datetime,
                float(initial_cash),
                int(progress_current),
                int(progress_total),
                status_message,
                selected_strategy_profile_id,
                selected_strategy_profile_name,
                selected_strategy_profile_version_id,
                self._dumps_metadata(strategy_profile_snapshot),
                json.dumps(metadata or {}, ensure_ascii=False),
                self._now(),
                self._now(),
            ),
        )
        run_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return run_id

    def add_sim_run_checkpoint(
        self,
        run_id: int,
        *,
        checkpoint_at: str,
        candidates_scanned: int,
        positions_checked: int,
        signals_created: int,
        auto_executed: int,
        available_cash: float,
        market_value: float,
        total_equity: float,
        metadata: Optional[dict[str, Any]] = None,
    ) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sim_run_checkpoints
            (
                run_id, checkpoint_at, candidates_scanned, positions_checked, signals_created,
                auto_executed, available_cash, market_value, total_equity, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                checkpoint_at,
                candidates_scanned,
                positions_checked,
                signals_created,
                auto_executed,
                round(available_cash, 4),
                round(market_value, 4),
                round(total_equity, 4),
                json.dumps(metadata or {}, ensure_ascii=False),
                self._now(),
            ),
        )
        cursor.execute(
            """
            UPDATE sim_runs
            SET checkpoint_count = checkpoint_count + 1,
                latest_checkpoint_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (checkpoint_at, self._now(), run_id),
        )
        checkpoint_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return checkpoint_id

    def update_sim_run_progress(
        self,
        run_id: int,
        *,
        status: Optional[str] = None,
        progress_current: Optional[int] = None,
        progress_total: Optional[int] = None,
        latest_checkpoint_at: Optional[str] = None,
        status_message: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        updates: list[str] = []
        params: list[Any] = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if progress_current is not None:
            updates.append("progress_current = ?")
            params.append(int(progress_current))
        if progress_total is not None:
            updates.append("progress_total = ?")
            params.append(int(progress_total))
        if latest_checkpoint_at is not None:
            updates.append("latest_checkpoint_at = ?")
            params.append(latest_checkpoint_at)
        if status_message is not None:
            updates.append("status_message = ?")
            params.append(status_message)

        if metadata is not None:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute("SELECT metadata_json FROM sim_runs WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            merged_metadata = {**self._loads_metadata(row["metadata_json"] if row else None), **metadata}
            updates.append("metadata_json = ?")
            params.append(json.dumps(merged_metadata, ensure_ascii=False))
        else:
            conn = self._connect()
            cursor = conn.cursor()

        if not updates:
            conn.close()
            return

        updates.append("updated_at = ?")
        params.append(self._now())
        params.append(run_id)
        cursor.execute(
            f"UPDATE sim_runs SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        conn.close()

    def append_sim_run_event(self, run_id: int, message: str, *, level: str = "info") -> int:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sim_run_events (run_id, level, message, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, level, message, self._now()),
        )
        event_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return event_id

    def get_sim_run(self, run_id: int) -> Optional[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sim_runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        conn.close()
        return self._signal_row_to_dict(row) if row is not None else None

    def get_active_sim_run(self) -> Optional[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sim_runs
            WHERE status IN ('queued', 'running')
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        conn.close()
        return self._signal_row_to_dict(row) if row is not None else None

    def get_sim_run_events(self, run_id: int, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sim_run_events
            WHERE run_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (run_id, limit),
        )
        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def delete_sim_run(self, run_id: int) -> None:
        run = self.get_sim_run(run_id)
        if run is None:
            return
        if str(run.get("status") or "").lower() in {"queued", "running"}:
            raise ValueError("运行中的回放任务不能直接删除，请先取消并等待进入终态。")

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sim_run_checkpoints WHERE run_id = ?", (run_id,))
        cursor.execute("DELETE FROM sim_run_trades WHERE run_id = ?", (run_id,))
        cursor.execute("DELETE FROM sim_run_snapshots WHERE run_id = ?", (run_id,))
        cursor.execute("DELETE FROM sim_run_positions WHERE run_id = ?", (run_id,))
        cursor.execute("DELETE FROM sim_run_signals WHERE run_id = ?", (run_id,))
        cursor.execute("DELETE FROM sim_run_events WHERE run_id = ?", (run_id,))
        cursor.execute("DELETE FROM sim_runs WHERE id = ?", (run_id,))
        conn.commit()
        conn.close()

    def request_sim_run_cancel(self, run_id: int) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE sim_runs
            SET cancel_requested = 1,
                status_message = ?,
                updated_at = ?
            WHERE id = ?
            """,
            ("已请求取消，正在尽快停止当前回放", self._now(), run_id),
        )
        conn.commit()
        conn.close()

    def set_sim_run_worker_pid(self, run_id: int, worker_pid: int | None) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE sim_runs
            SET worker_pid = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (worker_pid, self._now(), run_id),
        )
        conn.commit()
        conn.close()

    def is_sim_run_cancel_requested(self, run_id: int) -> bool:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT cancel_requested FROM sim_runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        conn.close()
        return bool(row["cancel_requested"]) if row is not None else False

    def replace_sim_run_results(
        self,
        run_id: int,
        *,
        trades: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        signals: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sim_run_trades WHERE run_id = ?", (run_id,))
        cursor.execute("DELETE FROM sim_run_snapshots WHERE run_id = ?", (run_id,))
        cursor.execute("DELETE FROM sim_run_positions WHERE run_id = ?", (run_id,))
        cursor.execute("DELETE FROM sim_run_signals WHERE run_id = ?", (run_id,))

        for snapshot in snapshots:
            cursor.execute(
                """
                INSERT INTO sim_run_snapshots
                (
                    run_id, run_reason, initial_cash, available_cash, market_value,
                    total_equity, realized_pnl, unrealized_pnl, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    snapshot.get("run_reason") or "historical_range",
                    float(snapshot.get("initial_cash") or 0),
                    float(snapshot.get("available_cash") or 0),
                    float(snapshot.get("market_value") or 0),
                    float(snapshot.get("total_equity") or 0),
                    float(snapshot.get("realized_pnl") or 0),
                    float(snapshot.get("unrealized_pnl") or 0),
                    snapshot.get("created_at") or self._now(),
                ),
            )

        for position in positions:
            cursor.execute(
                """
                INSERT INTO sim_run_positions
                (
                    run_id, stock_code, stock_name, quantity, avg_price, latest_price,
                    market_value, unrealized_pnl, sellable_quantity, locked_quantity, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    position.get("stock_code"),
                    position.get("stock_name"),
                    int(position.get("quantity") or 0),
                    float(position.get("avg_price") or 0),
                    float(position.get("latest_price") or 0),
                    float(position.get("market_value") or 0),
                    float(position.get("unrealized_pnl") or 0),
                    int(position.get("sellable_quantity") or 0),
                    int(position.get("locked_quantity") or 0),
                    position.get("status") or "holding",
                    self._now(),
                ),
            )

        persisted_signal_ids_by_source_id = self._upsert_sim_run_signals_with_cursor(cursor, run_id, signals or [])

        for trade in trades:
            source_signal_id = trade.get("signal_id")
            if source_signal_id is None:
                persisted_signal_id = None
            else:
                persisted_signal_id = persisted_signal_ids_by_source_id.get(int(source_signal_id), int(source_signal_id))
            cursor.execute(
                """
                INSERT INTO sim_run_trades
                (
                    run_id, signal_id, stock_code, stock_name, action, price, quantity, amount,
                    realized_pnl, note, executed_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    persisted_signal_id,
                    trade.get("stock_code"),
                    trade.get("stock_name"),
                    str(trade.get("action") or "").upper(),
                    float(trade.get("price") or 0),
                    int(trade.get("quantity") or 0),
                    float(trade.get("amount") or 0),
                    float(trade.get("realized_pnl") or 0),
                    trade.get("note"),
                    trade.get("executed_at") or self._now(),
                    trade.get("created_at") or self._now(),
                ),
            )

        conn.commit()
        conn.close()

    def finalize_sim_run(
        self,
        run_id: int,
        *,
        status: str,
        final_equity: float,
        total_return_pct: float,
        max_drawdown_pct: float,
        win_rate: float,
        trade_count: int,
        status_message: str | None = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT metadata_json, progress_total, progress_current FROM sim_runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        existing_metadata = self._loads_metadata(row["metadata_json"] if row else None)
        merged_metadata = {**existing_metadata, **(metadata or {})}
        progress_total = int(row["progress_total"] or 0) if row is not None else 0
        progress_current = int(row["progress_current"] or 0) if row is not None else 0
        final_progress_current = progress_total if status == "completed" else progress_current
        cursor.execute(
            """
            UPDATE sim_runs
            SET status = ?, final_equity = ?, total_return_pct = ?, max_drawdown_pct = ?,
                win_rate = ?, trade_count = ?, progress_current = ?, status_message = ?,
                worker_pid = NULL, metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                round(final_equity, 4),
                round(total_return_pct, 4),
                round(max_drawdown_pct, 4),
                round(win_rate, 4),
                int(trade_count),
                final_progress_current,
                status_message,
                json.dumps(merged_metadata, ensure_ascii=False),
                self._now(),
                run_id,
            ),
        )
        conn.commit()
        conn.close()

    def get_sim_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sim_runs ORDER BY id DESC LIMIT ?", (limit,))
        rows = [self._signal_row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_sim_run_checkpoints(self, run_id: int) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sim_run_checkpoints
            WHERE run_id = ?
            ORDER BY checkpoint_at ASC, id ASC
            """,
            (run_id,),
        )
        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_sim_run_trades(self, run_id: int) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sim_run_trades
            WHERE run_id = ?
            ORDER BY executed_at DESC, id DESC
            """,
            (run_id,),
        )
        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_sim_run_snapshots(self, run_id: int) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sim_run_snapshots
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (run_id,),
        )
        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_sim_run_positions(self, run_id: int) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sim_run_positions
            WHERE run_id = ?
            ORDER BY stock_code ASC, id ASC
            """,
            (run_id,),
        )
        rows = [self._row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_sim_run_signals(self, run_id: int) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sim_run_signals
            WHERE run_id = ?
            ORDER BY COALESCE(checkpoint_at, created_at) DESC, id DESC
            """,
            (run_id,),
        )
        rows = [self._signal_row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_sim_run_signal(self, signal_id: int) -> Optional[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sim_run_signals WHERE id = ?", (signal_id,))
        row = cursor.fetchone()
        conn.close()
        return self._signal_row_to_dict(row) if row is not None else None

    def get_default_strategy_profile_id(self) -> str:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id
            FROM strategy_profiles
            WHERE is_default = 1
            ORDER BY updated_at DESC, id ASC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        conn.close()
        if row is not None and str(row["id"]).strip():
            return str(row["id"]).strip()
        return DEFAULT_STRATEGY_PROFILE_ID

    def list_strategy_profiles(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        if include_disabled:
            cursor.execute(
                """
                SELECT * FROM strategy_profiles
                ORDER BY is_default DESC, updated_at DESC, id ASC
                """
            )
        else:
            cursor.execute(
                """
                SELECT * FROM strategy_profiles
                WHERE enabled = 1
                ORDER BY is_default DESC, updated_at DESC, id ASC
                """
            )
        rows = [self._strategy_profile_row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_strategy_profile(self, profile_id: str) -> Optional[dict[str, Any]]:
        profile_key = str(profile_id or "").strip()
        if not profile_key:
            return None
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM strategy_profiles WHERE id = ?", (profile_key,))
        row = cursor.fetchone()
        conn.close()
        return self._strategy_profile_row_to_dict(row) if row is not None else None

    def get_latest_strategy_profile_version(self, profile_id: str) -> Optional[dict[str, Any]]:
        profile_key = str(profile_id or "").strip()
        if not profile_key:
            return None
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT *
            FROM strategy_profile_versions
            WHERE profile_id = ?
            ORDER BY version DESC, id DESC
            LIMIT 1
            """,
            (profile_key,),
        )
        row = cursor.fetchone()
        conn.close()
        return self._strategy_profile_version_row_to_dict(row) if row is not None else None

    def list_strategy_profile_versions(self, profile_id: str, limit: int = 20) -> list[dict[str, Any]]:
        profile_key = str(profile_id or "").strip()
        if not profile_key:
            return []
        safe_limit = max(1, min(int(limit or 20), 200))
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT *
            FROM strategy_profile_versions
            WHERE profile_id = ?
            ORDER BY version DESC, id DESC
            LIMIT ?
            """,
            (profile_key, safe_limit),
        )
        rows = [self._strategy_profile_version_row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_strategy_profile_version(self, version_id: int) -> Optional[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM strategy_profile_versions WHERE id = ?", (int(version_id),))
        row = cursor.fetchone()
        conn.close()
        return self._strategy_profile_version_row_to_dict(row) if row is not None else None

    def validate_strategy_profile_config(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = self._validate_and_normalize_strategy_profile_config(config)
        return {
            "schema_version": normalized["schema_version"],
            "base": normalized["base"],
            "profiles": normalized["profiles"],
        }

    def create_strategy_profile(
        self,
        *,
        profile_id: str | None,
        name: str,
        config: dict[str, Any],
        description: str = "",
        enabled: bool = True,
        set_default: bool = False,
        note: str | None = None,
    ) -> dict[str, Any]:
        normalized_profile_id = str(profile_id or "").strip() or f"profile-{uuid.uuid4().hex[:10]}"
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("strategy profile name is required")
        normalized_config = self._validate_and_normalize_strategy_profile_config(config)
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM strategy_profiles WHERE id = ?", (normalized_profile_id,))
        if cursor.fetchone() is not None:
            conn.close()
            raise ValueError(f"strategy profile already exists: {normalized_profile_id}")
        now_text = self._now()
        if set_default:
            cursor.execute("UPDATE strategy_profiles SET is_default = 0, updated_at = ?", (now_text,))
        cursor.execute(
            """
            INSERT INTO strategy_profiles
            (id, name, description, enabled, is_default, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_profile_id,
                normalized_name,
                str(description or "").strip(),
                1 if enabled else 0,
                1 if set_default else 0,
                now_text,
                now_text,
            ),
        )
        version = self._insert_strategy_profile_version(
            cursor,
            profile_id=normalized_profile_id,
            config=normalized_config,
            note=note or "initial",
        )
        conn.commit()
        conn.close()
        return {
            "profile": self.get_strategy_profile(normalized_profile_id),
            "version": version,
        }

    def _upsert_sim_run_signals_with_cursor(
        self,
        cursor: sqlite3.Cursor,
        run_id: int,
        signals: list[dict[str, Any]],
    ) -> dict[int, int]:
        persisted_signal_ids_by_source_id: dict[int, int] = {}
        for signal in signals:
            source_signal_id = self._normalize_optional_int(signal.get("source_signal_id"))
            if source_signal_id is None:
                source_signal_id = self._normalize_optional_int(signal.get("id"))

            checkpoint_at = signal.get("checkpoint_at") or signal.get("executed_at") or signal.get("updated_at") or signal.get("created_at")
            created_at = signal.get("created_at") or self._now()
            payload = (
                run_id,
                source_signal_id,
                signal.get("stock_code"),
                signal.get("stock_name"),
                str(signal.get("action") or "HOLD").upper(),
                int(signal.get("confidence") or 0),
                signal.get("reasoning"),
                float(signal.get("position_size_pct") or 0),
                signal.get("decision_type"),
                float(signal.get("tech_score") or 0),
                float(signal.get("context_score") or 0),
                self._dumps_metadata(signal.get("strategy_profile")),
                checkpoint_at,
                signal.get("status") or signal.get("signal_status") or "observed",
                created_at,
            )

            existing_id: int | None = None
            if source_signal_id is not None:
                cursor.execute(
                    """
                    SELECT id
                    FROM sim_run_signals
                    WHERE run_id = ? AND source_signal_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (run_id, source_signal_id),
                )
                row = cursor.fetchone()
                if row is not None:
                    existing_id = int(row["id"])
            if existing_id is None:
                cursor.execute(
                    """
                    INSERT INTO sim_run_signals
                    (
                        run_id, source_signal_id, stock_code, stock_name, action, confidence, reasoning,
                        position_size_pct, decision_type, tech_score, context_score,
                        strategy_profile_json, checkpoint_at, signal_status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
                persisted_id = int(cursor.lastrowid)
            else:
                cursor.execute(
                    """
                    UPDATE sim_run_signals
                    SET source_signal_id = ?,
                        stock_code = ?,
                        stock_name = ?,
                        action = ?,
                        confidence = ?,
                        reasoning = ?,
                        position_size_pct = ?,
                        decision_type = ?,
                        tech_score = ?,
                        context_score = ?,
                        strategy_profile_json = ?,
                        checkpoint_at = ?,
                        signal_status = ?,
                        created_at = ?
                    WHERE id = ?
                    """,
                    payload[1:] + (existing_id,),
                )
                persisted_id = existing_id

            if source_signal_id is not None:
                persisted_signal_ids_by_source_id[source_signal_id] = persisted_id

        return persisted_signal_ids_by_source_id

    def upsert_sim_run_signals(self, run_id: int, signals: list[dict[str, Any]]) -> dict[int, int]:
        conn = self._connect()
        cursor = conn.cursor()
        persisted = self._upsert_sim_run_signals_with_cursor(cursor, run_id, signals)
        conn.commit()
        conn.close()
        return persisted

    def update_strategy_profile(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        set_default: bool | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        profile_key = str(profile_id or "").strip()
        if not profile_key:
            raise ValueError("strategy profile id is required")
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM strategy_profiles WHERE id = ?", (profile_key,))
        row = cursor.fetchone()
        if row is None:
            conn.close()
            raise ValueError(f"strategy profile not found: {profile_key}")
        updates: list[str] = []
        params: list[Any] = []
        if name is not None:
            normalized_name = str(name).strip()
            if not normalized_name:
                conn.close()
                raise ValueError("strategy profile name is required")
            updates.append("name = ?")
            params.append(normalized_name)
        if description is not None:
            updates.append("description = ?")
            params.append(str(description).strip())
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if bool(enabled) else 0)
        if set_default is True:
            cursor.execute("UPDATE strategy_profiles SET is_default = 0, updated_at = ? WHERE id <> ?", (self._now(), profile_key))
            updates.append("is_default = ?")
            params.append(1)
            cursor.execute("UPDATE sim_scheduler_config SET strategy_profile_id = ? WHERE id = 1", (profile_key,))
        elif set_default is False:
            updates.append("is_default = ?")
            params.append(0)
        if updates:
            updates.append("updated_at = ?")
            params.append(self._now())
            params.append(profile_key)
            cursor.execute(f"UPDATE strategy_profiles SET {', '.join(updates)} WHERE id = ?", params)
        version_payload = None
        if config is not None:
            normalized_config = self._validate_and_normalize_strategy_profile_config(config)
            version_payload = self._insert_strategy_profile_version(
                cursor,
                profile_id=profile_key,
                config=normalized_config,
                note=note or "update",
            )
            cursor.execute("UPDATE strategy_profiles SET updated_at = ? WHERE id = ?", (self._now(), profile_key))
        conn.commit()
        conn.close()
        return {
            "profile": self.get_strategy_profile(profile_key),
            "version": version_payload or self.get_latest_strategy_profile_version(profile_key),
        }

    def clone_strategy_profile(
        self,
        source_profile_id: str,
        *,
        name: str,
        profile_id: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        source_key = str(source_profile_id or "").strip()
        source_profile = self.get_strategy_profile(source_key)
        if source_profile is None:
            raise ValueError(f"strategy profile not found: {source_key}")
        source_version = self.get_latest_strategy_profile_version(source_key)
        if source_version is None:
            raise ValueError(f"strategy profile has no versions: {source_key}")
        return self.create_strategy_profile(
            profile_id=profile_id,
            name=name,
            config=source_version["config"],
            description=(description if description is not None else str(source_profile.get("description") or "").strip()),
            enabled=bool(source_profile.get("enabled", True)),
            set_default=False,
            note=f"cloned_from:{source_key}@v{source_version.get('version')}",
        )

    def set_default_strategy_profile(self, profile_id: str) -> dict[str, Any]:
        profile_key = str(profile_id or "").strip()
        if not profile_key:
            raise ValueError("strategy profile id is required")
        profile = self.get_strategy_profile(profile_key)
        if profile is None:
            raise ValueError(f"strategy profile not found: {profile_key}")
        if not bool(profile.get("enabled", True)):
            raise ValueError("cannot set disabled strategy profile as default")
        conn = self._connect()
        cursor = conn.cursor()
        now_text = self._now()
        cursor.execute("UPDATE strategy_profiles SET is_default = 0, updated_at = ?", (now_text,))
        cursor.execute(
            "UPDATE strategy_profiles SET is_default = 1, updated_at = ? WHERE id = ?",
            (now_text, profile_key),
        )
        cursor.execute(
            "UPDATE sim_scheduler_config SET strategy_profile_id = ?, updated_at = ? WHERE id = 1",
            (profile_key, now_text),
        )
        conn.commit()
        conn.close()
        return self.get_strategy_profile(profile_key) or {}

    def resolve_strategy_profile_binding(self, profile_id: str | None = None) -> dict[str, Any]:
        selected_profile_id = str(profile_id or "").strip() or self.get_default_strategy_profile_id()
        profile = self.get_strategy_profile(selected_profile_id)
        if profile is None:
            raise ValueError(f"strategy profile not found: {selected_profile_id}")
        if not bool(profile.get("enabled", True)):
            raise ValueError(f"strategy profile is disabled: {selected_profile_id}")
        latest_version = self.get_latest_strategy_profile_version(selected_profile_id)
        if latest_version is None:
            raise ValueError(f"strategy profile has no version snapshot: {selected_profile_id}")
        return {
            "profile_id": selected_profile_id,
            "profile_name": str(profile.get("name") or selected_profile_id),
            "version_id": int(latest_version["id"]),
            "version": int(latest_version["version"]),
            "config": latest_version["config"],
        }

    def get_scheduler_config(self) -> dict[str, Any]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sim_scheduler_config WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        return {
            "enabled": bool(row["enabled"]),
            "auto_execute": bool(row["auto_execute"]),
            "interval_minutes": int(row["interval_minutes"]),
            "trading_hours_only": bool(row["trading_hours_only"]),
            "analysis_timeframe": self._normalize_analysis_timeframe(row["analysis_timeframe"]),
            "strategy_mode": self._normalize_strategy_mode(row["strategy_mode"]),
            "strategy_profile_id": str(row["strategy_profile_id"] or "").strip(),
            "ai_dynamic_strategy": self._normalize_ai_dynamic_strategy(row["ai_dynamic_strategy"]),
            "ai_dynamic_strength": self._normalize_ai_dynamic_strength(row["ai_dynamic_strength"]),
            "ai_dynamic_lookback": self._normalize_ai_dynamic_lookback(row["ai_dynamic_lookback"]),
            "start_date": self._normalize_start_date(row["start_date"]),
            "market": row["market"] or "CN",
            "commission_rate": self._normalize_fee_rate(row["commission_rate"], default=DEFAULT_COMMISSION_RATE),
            "sell_tax_rate": self._normalize_fee_rate(row["sell_tax_rate"], default=DEFAULT_SELL_TAX_RATE),
            "last_run_at": row["last_run_at"],
            "updated_at": row["updated_at"],
        }

    def update_scheduler_config(
        self,
        *,
        enabled: Optional[bool] = None,
        auto_execute: Optional[bool] = None,
        interval_minutes: Optional[int] = None,
        trading_hours_only: Optional[bool] = None,
        analysis_timeframe: Optional[str] = None,
        strategy_mode: Optional[str] = None,
        strategy_profile_id: Optional[str] = None,
        ai_dynamic_strategy: Optional[str] = None,
        ai_dynamic_strength: Optional[float] = None,
        ai_dynamic_lookback: Optional[int] = None,
        start_date: Optional[str | date | datetime] = None,
        market: Optional[str] = None,
        commission_rate: Optional[float] = None,
        sell_tax_rate: Optional[float] = None,
        last_run_at: Optional[str] = None,
    ) -> None:
        existing = self.get_scheduler_config()
        payload = {
            "enabled": int(existing["enabled"] if enabled is None else enabled),
            "auto_execute": int(existing["auto_execute"] if auto_execute is None else auto_execute),
            "interval_minutes": int(existing["interval_minutes"] if interval_minutes is None else interval_minutes),
            "trading_hours_only": int(existing["trading_hours_only"] if trading_hours_only is None else trading_hours_only),
            "analysis_timeframe": self._normalize_analysis_timeframe(
                existing["analysis_timeframe"] if analysis_timeframe is None else analysis_timeframe
            ),
            "strategy_mode": self._normalize_strategy_mode(
                existing["strategy_mode"] if strategy_mode is None else strategy_mode
            ),
            "strategy_profile_id": existing["strategy_profile_id"] if strategy_profile_id is None else str(strategy_profile_id or "").strip(),
            "ai_dynamic_strategy": self._normalize_ai_dynamic_strategy(
                existing["ai_dynamic_strategy"] if ai_dynamic_strategy is None else ai_dynamic_strategy
            ),
            "ai_dynamic_strength": self._normalize_ai_dynamic_strength(
                existing["ai_dynamic_strength"] if ai_dynamic_strength is None else ai_dynamic_strength
            ),
            "ai_dynamic_lookback": self._normalize_ai_dynamic_lookback(
                existing["ai_dynamic_lookback"] if ai_dynamic_lookback is None else ai_dynamic_lookback
            ),
            "start_date": self._normalize_start_date(existing["start_date"] if start_date is None else start_date),
            "market": existing["market"] if market is None else str(market),
            "commission_rate": self._normalize_fee_rate(
                existing["commission_rate"] if commission_rate is None else commission_rate,
                default=DEFAULT_COMMISSION_RATE,
            ),
            "sell_tax_rate": self._normalize_fee_rate(
                existing["sell_tax_rate"] if sell_tax_rate is None else sell_tax_rate,
                default=DEFAULT_SELL_TAX_RATE,
            ),
            "last_run_at": existing["last_run_at"] if last_run_at is None else last_run_at,
        }
        if payload["interval_minutes"] <= 0:
            raise ValueError("interval_minutes must be positive")
        selected_profile_id = str(payload["strategy_profile_id"] or "").strip()
        if selected_profile_id and self.get_strategy_profile(selected_profile_id) is None:
            raise ValueError(f"strategy profile not found: {selected_profile_id}")

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE sim_scheduler_config
            SET enabled = ?, auto_execute = ?, interval_minutes = ?, trading_hours_only = ?,
                analysis_timeframe = ?, strategy_mode = ?, strategy_profile_id = ?,
                ai_dynamic_strategy = ?, ai_dynamic_strength = ?, ai_dynamic_lookback = ?,
                start_date = ?, market = ?,
                commission_rate = ?, sell_tax_rate = ?, last_run_at = ?, updated_at = ?
            WHERE id = 1
            """,
            (
                payload["enabled"],
                payload["auto_execute"],
                payload["interval_minutes"],
                payload["trading_hours_only"],
                payload["analysis_timeframe"],
                payload["strategy_mode"],
                payload["strategy_profile_id"],
                payload["ai_dynamic_strategy"],
                payload["ai_dynamic_strength"],
                payload["ai_dynamic_lookback"],
                payload["start_date"],
                payload["market"],
                payload["commission_rate"],
                payload["sell_tax_rate"],
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
        apply_trade_cost: bool = False,
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
                    apply_trade_cost=apply_trade_cost,
                )
            elif action == "sell":
                trade_result = self._apply_sell(
                    cursor=cursor,
                    stock_code=signal["stock_code"],
                    price=price,
                    quantity=quantity,
                    executed_at=executed_dt,
                    apply_trade_cost=apply_trade_cost,
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

    def has_open_position(self, stock_code: str) -> bool:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 1
            FROM sim_positions
            WHERE stock_code = ? AND status = 'holding' AND quantity > 0
            LIMIT 1
            """,
            (stock_code,),
        )
        exists = cursor.fetchone() is not None
        conn.close()
        return exists

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

    def reset_runtime_state(self, *, initial_cash: Optional[float] = None) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM strategy_signals")
        cursor.execute("DELETE FROM sim_position_lots")
        cursor.execute("DELETE FROM sim_positions")
        cursor.execute("DELETE FROM sim_trades")
        cursor.execute("DELETE FROM sim_account_snapshots")
        cursor.execute(
            """
            UPDATE candidate_pool
            SET status = 'active', updated_at = ?
            WHERE status <> 'active'
            """,
            (self._now(),),
        )
        if initial_cash is not None:
            cursor.execute(
                """
                UPDATE sim_account
                SET initial_cash = ?, available_cash = ?, updated_at = ?
                WHERE id = 1
                """,
                (round(initial_cash, 4), round(initial_cash, 4), self._now()),
            )
        else:
            cursor.execute(
                """
                UPDATE sim_account
                SET available_cash = initial_cash, updated_at = ?
                WHERE id = 1
                """,
                (self._now(),),
            )
        conn.commit()
        conn.close()

    def replace_runtime_state(
        self,
        *,
        initial_cash: float,
        available_cash: float,
        positions: list[dict[str, Any]],
        lots: list[dict[str, Any]],
        trades: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
    ) -> None:
        self.reset_runtime_state(initial_cash=initial_cash)

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE sim_account
            SET initial_cash = ?, available_cash = ?, updated_at = ?
            WHERE id = 1
            """,
            (round(initial_cash, 4), round(available_cash, 4), self._now()),
        )

        position_ids: dict[str, int] = {}
        for position in positions:
            cursor.execute(
                """
                INSERT INTO sim_positions
                (
                    stock_code, stock_name, quantity, avg_price, latest_price,
                    market_value, unrealized_pnl, unrealized_pnl_pct, status, opened_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position.get("stock_code"),
                    position.get("stock_name"),
                    int(position.get("quantity") or 0),
                    float(position.get("avg_price") or 0),
                    float(position.get("latest_price") or 0),
                    float(position.get("market_value") or 0),
                    float(position.get("unrealized_pnl") or 0),
                    float(position.get("unrealized_pnl_pct") or 0),
                    position.get("status") or "holding",
                    position.get("opened_at") or self._now(),
                    position.get("updated_at") or self._now(),
                ),
            )
            position_id = int(cursor.lastrowid)
            stock_code = str(position.get("stock_code") or "")
            position_ids[stock_code] = position_id
            cursor.execute(
                """
                UPDATE candidate_pool
                SET status = 'holding', latest_price = ?, updated_at = ?
                WHERE stock_code = ?
                """,
                (float(position.get("latest_price") or 0), self._now(), stock_code),
            )

        for lot in lots:
            stock_code = str(lot.get("stock_code") or "")
            position_id = position_ids.get(stock_code)
            if position_id is None:
                continue
            cursor.execute(
                """
                INSERT INTO sim_position_lots
                (
                    position_id, lot_id, stock_code, quantity, remaining_quantity, entry_price,
                    entry_time, entry_date, unlock_date, status, closed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position_id,
                    lot.get("lot_id"),
                    stock_code,
                    int(lot.get("quantity") or 0),
                    int(lot.get("remaining_quantity") or 0),
                    float(lot.get("entry_price") or 0),
                    lot.get("entry_time") or self._now(),
                    lot.get("entry_date"),
                    lot.get("unlock_date"),
                    lot.get("status") or "available",
                    lot.get("closed_at"),
                ),
            )

        for trade in reversed(trades):
            self._record_trade(
                cursor,
                signal_id=int(trade.get("signal_id") or 0),
                stock_code=str(trade.get("stock_code") or ""),
                stock_name=trade.get("stock_name"),
                action=str(trade.get("action") or "").lower(),
                price=float(trade.get("price") or 0),
                quantity=int(trade.get("quantity") or 0),
                amount=float(trade.get("amount") or 0),
                realized_pnl=float(trade.get("realized_pnl") or 0),
                note=trade.get("note"),
                executed_at=trade.get("executed_at") or self._now(),
            )

        for snapshot in snapshots:
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
                    snapshot.get("run_reason") or "continuous_handoff",
                    float(snapshot.get("initial_cash") or 0),
                    float(snapshot.get("available_cash") or 0),
                    float(snapshot.get("market_value") or 0),
                    float(snapshot.get("total_equity") or 0),
                    float(snapshot.get("realized_pnl") or 0),
                    float(snapshot.get("unrealized_pnl") or 0),
                    snapshot.get("created_at") or self._now(),
                ),
            )

        conn.commit()
        conn.close()

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
        apply_trade_cost: bool = False,
    ) -> dict[str, Any]:
        executed_at_text = self._format_datetime(executed_at)
        gross_amount = round(price * quantity, 4)
        commission_fee = 0.0
        if apply_trade_cost:
            cost_cfg = self._current_trade_cost_config(cursor)
            commission_fee = round(gross_amount * cost_cfg["commission_rate"], 4)
        amount = round(gross_amount + commission_fee, 4)
        available_cash = self._get_available_cash(cursor)
        if amount > available_cash:
            raise ValueError("insufficient available cash")

        cursor.execute("SELECT * FROM sim_positions WHERE stock_code = ?", (stock_code,))
        position = cursor.fetchone()

        if position:
            current_quantity = int(position["quantity"])
            new_quantity = current_quantity + quantity
            total_cost = float(position["avg_price"]) * current_quantity + amount
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
            avg_price = round(amount / quantity, 4)
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
                (stock_code, stock_name, quantity, avg_price, price, market_value, executed_at_text, executed_at_text),
            )
            position_id = int(cursor.lastrowid)

        lot_entry_price = round(amount / quantity, 4)
        unlock_date = self._next_trading_day(executed_at.date()).isoformat()
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
                lot_entry_price,
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
        apply_trade_cost: bool = False,
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
        gross_proceeds = round(price * quantity, 4)
        sell_fee = 0.0
        if apply_trade_cost:
            cost_cfg = self._current_trade_cost_config(cursor)
            sell_fee = round(gross_proceeds * (cost_cfg["commission_rate"] + cost_cfg["sell_tax_rate"]), 4)
        proceeds = round(gross_proceeds - sell_fee, 4)
        realized_pnl = round(realized_pnl - sell_fee, 4)
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
                "realized_pnl": realized_pnl,
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
            "realized_pnl": realized_pnl,
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
                (
                    id, enabled, auto_execute, interval_minutes, trading_hours_only,
                    analysis_timeframe, strategy_mode, strategy_profile_id,
                    ai_dynamic_strategy, ai_dynamic_strength, ai_dynamic_lookback,
                    start_date, market,
                    commission_rate, sell_tax_rate, last_run_at, updated_at
                )
                VALUES (1, 0, 0, 15, 1, ?, ?, ?, ?, ?, ?, ?, 'CN', ?, ?, NULL, ?)
                """,
                (
                    DEFAULT_ANALYSIS_TIMEFRAME,
                    DEFAULT_STRATEGY_MODE,
                    DEFAULT_STRATEGY_PROFILE_ID,
                    DEFAULT_AI_DYNAMIC_STRATEGY,
                    DEFAULT_AI_DYNAMIC_STRENGTH,
                    DEFAULT_AI_DYNAMIC_LOOKBACK,
                    date.today().isoformat(),
                    DEFAULT_COMMISSION_RATE,
                    DEFAULT_SELL_TAX_RATE,
                    self._now(),
                ),
            )
        else:
            cursor.execute(
                """
                UPDATE sim_scheduler_config
                SET analysis_timeframe = COALESCE(NULLIF(analysis_timeframe, ''), ?)
                WHERE id = 1
                """,
                (DEFAULT_ANALYSIS_TIMEFRAME,),
            )
            cursor.execute(
                """
                UPDATE sim_scheduler_config
                SET strategy_mode = COALESCE(NULLIF(strategy_mode, ''), ?)
                WHERE id = 1
                """,
                (DEFAULT_STRATEGY_MODE,),
            )
            cursor.execute(
                """
                UPDATE sim_scheduler_config
                SET strategy_profile_id = COALESCE(NULLIF(strategy_profile_id, ''), ?)
                WHERE id = 1
                """,
                (DEFAULT_STRATEGY_PROFILE_ID,),
            )
            cursor.execute(
                """
                UPDATE sim_scheduler_config
                SET ai_dynamic_strategy = COALESCE(NULLIF(ai_dynamic_strategy, ''), ?)
                WHERE id = 1
                """,
                (DEFAULT_AI_DYNAMIC_STRATEGY,),
            )
            cursor.execute(
                """
                UPDATE sim_scheduler_config
                SET ai_dynamic_strength = COALESCE(ai_dynamic_strength, ?)
                WHERE id = 1
                """,
                (DEFAULT_AI_DYNAMIC_STRENGTH,),
            )
            cursor.execute(
                """
                UPDATE sim_scheduler_config
                SET ai_dynamic_lookback = COALESCE(ai_dynamic_lookback, ?)
                WHERE id = 1
                """,
                (DEFAULT_AI_DYNAMIC_LOOKBACK,),
            )
            cursor.execute(
                """
                UPDATE sim_scheduler_config
                SET start_date = COALESCE(NULLIF(start_date, ''), ?)
                WHERE id = 1
                """,
                (date.today().isoformat(),),
            )
            cursor.execute(
                """
                UPDATE sim_scheduler_config
                SET commission_rate = COALESCE(commission_rate, ?)
                WHERE id = 1
                """,
                (DEFAULT_COMMISSION_RATE,),
            )
            cursor.execute(
                """
                UPDATE sim_scheduler_config
                SET sell_tax_rate = COALESCE(sell_tax_rate, ?)
                WHERE id = 1
                """,
                (DEFAULT_SELL_TAX_RATE,),
            )

    @staticmethod
    def _normalize_analysis_timeframe(value: str | None) -> str:
        normalized = str(value or DEFAULT_ANALYSIS_TIMEFRAME).strip().lower()
        if normalized == "day":
            normalized = "1d"
        if normalized in {"30min", "minute30"}:
            normalized = "30m"
        if normalized not in SUPPORTED_ANALYSIS_TIMEFRAMES:
            raise ValueError(f"Unsupported analysis_timeframe: {value}")
        return normalized

    @staticmethod
    def _normalize_strategy_mode(value: str | None) -> str:
        normalized = str(value or DEFAULT_STRATEGY_MODE).strip().lower()
        if normalized not in SUPPORTED_STRATEGY_MODES:
            raise ValueError(f"Unsupported strategy_mode: {value}")
        return normalized

    @staticmethod
    def _normalize_ai_dynamic_strategy(value: str | None) -> str:
        normalized = str(value or DEFAULT_AI_DYNAMIC_STRATEGY).strip().lower()
        if normalized not in SUPPORTED_AI_DYNAMIC_STRATEGIES:
            raise ValueError(f"Unsupported ai_dynamic_strategy: {value}")
        return normalized

    @staticmethod
    def _normalize_ai_dynamic_strength(value: float | int | str | None) -> float:
        try:
            parsed = float(value if value is not None else DEFAULT_AI_DYNAMIC_STRENGTH)
        except (TypeError, ValueError):
            parsed = DEFAULT_AI_DYNAMIC_STRENGTH
        if parsed < 0:
            parsed = 0.0
        if parsed > 1:
            parsed = 1.0
        return round(parsed, 4)

    @staticmethod
    def _normalize_ai_dynamic_lookback(value: int | float | str | None) -> int:
        try:
            parsed = int(round(float(value if value is not None else DEFAULT_AI_DYNAMIC_LOOKBACK)))
        except (TypeError, ValueError):
            parsed = DEFAULT_AI_DYNAMIC_LOOKBACK
        if parsed < 6:
            parsed = 6
        if parsed > 336:
            parsed = 336
        return parsed

    @staticmethod
    def _normalize_start_date(value: str | date | datetime | None) -> str:
        if value is None or value == "":
            return date.today().isoformat()
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return date.fromisoformat(str(value)).isoformat()

    @staticmethod
    def _normalize_fee_rate(value: Any, *, default: float = 0.0) -> float:
        try:
            parsed = float(default if value in (None, "") else value)
        except (TypeError, ValueError):
            parsed = float(default)
        if parsed < 0:
            parsed = 0.0
        if parsed > 1:
            parsed = parsed / 100.0
        if parsed > 0.2:
            parsed = 0.2
        return round(parsed, 8)

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

    def _current_trade_cost_config(self, cursor: sqlite3.Cursor) -> dict[str, float]:
        cursor.execute(
            """
            SELECT commission_rate, sell_tax_rate
            FROM sim_scheduler_config
            WHERE id = 1
            """
        )
        row = cursor.fetchone()
        commission_rate = self._normalize_fee_rate(
            row["commission_rate"] if row is not None else DEFAULT_COMMISSION_RATE,
            default=DEFAULT_COMMISSION_RATE,
        )
        sell_tax_rate = self._normalize_fee_rate(
            row["sell_tax_rate"] if row is not None else DEFAULT_SELL_TAX_RATE,
            default=DEFAULT_SELL_TAX_RATE,
        )
        return {
            "commission_rate": commission_rate,
            "sell_tax_rate": sell_tax_rate,
        }

    @staticmethod
    def _deep_copy_json(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _build_builtin_strategy_profile_configs(self) -> dict[str, dict[str, Any]]:
        payload = StrategyScoringConfig.default()
        base_config = {
            "schema_version": str(payload.schema_version),
            "base": self._deep_copy_json(payload.base),
            "profiles": self._deep_copy_json(payload.profiles),
        }

        aggressive_config = self._deep_copy_json(base_config)
        aggressive_boll_position_scorer = {
            "algorithm": "piecewise",
            "params": {
                "position_bands": [0.1, 0.25, 0.92, 1.0],
                "position_scores": [-0.6, 0.2, 0.35, -0.2],
            },
            "reason_template": "boll_position={boll_position}",
        }
        aggressive_config["base"]["dual_track"]["mode"] = "hybrid"
        aggressive_config["base"]["dual_track"]["track_weights"] = {"tech": 1.35, "context": 0.65}
        aggressive_config["base"]["dual_track"]["fusion_buy_threshold"] = 0.62
        aggressive_config["base"]["dual_track"]["fusion_sell_threshold"] = -0.24
        aggressive_config["base"]["dual_track"]["sell_precedence_gate"] = -0.58
        aggressive_config["base"]["dual_track"]["min_fusion_confidence"] = 0.42
        aggressive_config["base"]["dual_track"]["min_tech_score_for_buy"] = 0.05
        aggressive_config["base"]["dual_track"]["min_context_score_for_buy"] = -0.02
        aggressive_config["base"]["dual_track"]["min_tech_confidence_for_buy"] = 0.42
        aggressive_config["base"]["dual_track"]["min_context_confidence_for_buy"] = 0.38
        aggressive_config["base"]["dual_track"]["lambda_divergence"] = 0.45
        aggressive_config["base"]["dual_track"]["lambda_sign_conflict"] = 0.25
        aggressive_config["base"]["dual_track"]["sign_conflict_min_abs_score"] = 0.12
        aggressive_config["profiles"]["candidate"]["technical"]["group_weights"] = {
            "trend": 1.60,
            "momentum": 1.35,
            "volume_confirmation": 1.15,
            "volatility_risk": 0.45,
        }
        aggressive_config["profiles"]["candidate"]["technical"]["dimension_weights"] = {
            "trend_direction": 1.40,
            "ma_alignment": 0.95,
            "ma_slope": 1.35,
            "price_vs_ma20": 1.00,
            "macd_level": 1.15,
            "macd_hist_slope": 1.20,
            "rsi_zone": 0.70,
            "kdj_cross": 0.35,
            "volume_ratio": 1.05,
            "obv_trend": 1.35,
            "atr_risk": 0.70,
            "boll_position": 0.40,
        }
        aggressive_config["profiles"]["candidate"]["technical"]["scorers"] = {
            "boll_position": self._deep_copy_json(aggressive_boll_position_scorer),
        }
        aggressive_config["profiles"]["candidate"]["context"]["group_weights"] = {
            "market_structure": 1.25,
            "risk_account": 0.55,
            "tradability_timing": 0.55,
            "source_execution": 0.35,
        }
        aggressive_config["profiles"]["candidate"]["context"]["dimension_weights"] = {
            "trend_regime": 1.15,
            "price_structure": 1.10,
            "momentum": 0.90,
            "risk_balance": 0.90,
            "account_posture": 0.05,
            "liquidity": 0.85,
            "session": 0.35,
            "source_prior": 0.75,
            "execution_feedback": 0.05,
        }
        aggressive_config["profiles"]["candidate"]["dual_track"] = {
            "fusion_buy_threshold": 0.35,
            "fusion_sell_threshold": -0.30,
            "sell_precedence_gate": -0.38,
            "min_fusion_confidence": 0.38,
        }
        aggressive_config["profiles"]["position"]["technical"]["group_weights"] = {
            "trend": 1.35,
            "momentum": 1.20,
            "volume_confirmation": 0.95,
            "volatility_risk": 0.75,
        }
        aggressive_config["profiles"]["position"]["technical"]["dimension_weights"] = {
            "trend_direction": 1.25,
            "ma_alignment": 1.05,
            "ma_slope": 1.20,
            "price_vs_ma20": 1.00,
            "macd_level": 1.10,
            "macd_hist_slope": 1.15,
            "rsi_zone": 0.85,
            "kdj_cross": 0.65,
            "volume_ratio": 1.00,
            "obv_trend": 0.95,
            "atr_risk": 0.85,
            "boll_position": 0.75,
        }
        aggressive_config["profiles"]["position"]["technical"]["scorers"] = {
            "boll_position": self._deep_copy_json(aggressive_boll_position_scorer),
        }
        aggressive_config["profiles"]["position"]["context"]["group_weights"] = {
            "market_structure": 1.20,
            "risk_account": 1.00,
            "tradability_timing": 0.70,
            "source_execution": 0.60,
        }
        aggressive_config["profiles"]["position"]["context"]["dimension_weights"] = {
            "trend_regime": 1.15,
            "price_structure": 1.10,
            "momentum": 0.95,
            "risk_balance": 1.00,
            "account_posture": 0.90,
            "liquidity": 0.90,
            "session": 0.60,
            "source_prior": 0.80,
            "execution_feedback": 0.70,
        }
        aggressive_config["profiles"]["position"]["dual_track"] = {
            "fusion_buy_threshold": 0.50,
            "fusion_sell_threshold": -0.24,
            "sell_precedence_gate": -0.30,
            "min_fusion_confidence": 0.42,
        }

        stable_config = self._deep_copy_json(base_config)
        stable_config["base"]["dual_track"]["mode"] = "hybrid"
        stable_config["base"]["dual_track"]["track_weights"] = {"tech": 1.0, "context": 1.0}
        stable_config["base"]["dual_track"]["fusion_buy_threshold"] = 0.72
        stable_config["base"]["dual_track"]["fusion_sell_threshold"] = -0.17
        stable_config["base"]["dual_track"]["sell_precedence_gate"] = -0.50
        stable_config["base"]["dual_track"]["min_fusion_confidence"] = 0.48
        stable_config["base"]["dual_track"]["min_tech_confidence_for_buy"] = 0.48
        stable_config["base"]["dual_track"]["min_context_confidence_for_buy"] = 0.48
        stable_config["base"]["dual_track"]["lambda_divergence"] = 0.60
        stable_config["base"]["dual_track"]["lambda_sign_conflict"] = 0.35
        stable_config["profiles"]["candidate"]["technical"]["group_weights"] = {
            "trend": 1.30,
            "momentum": 1.15,
            "volume_confirmation": 1.00,
            "volatility_risk": 0.85,
        }
        stable_config["profiles"]["candidate"]["technical"]["dimension_weights"] = {
            "trend_direction": 1.20,
            "ma_alignment": 1.00,
            "ma_slope": 1.10,
            "price_vs_ma20": 0.95,
            "macd_level": 1.05,
            "macd_hist_slope": 1.10,
            "rsi_zone": 0.85,
            "kdj_cross": 0.30,
            "volume_ratio": 1.00,
            "obv_trend": 1.10,
            "atr_risk": 1.05,
            "boll_position": 0.80,
        }
        stable_config["profiles"]["candidate"]["context"]["group_weights"] = {
            "market_structure": 1.20,
            "risk_account": 1.10,
            "tradability_timing": 0.80,
            "source_execution": 0.75,
        }
        stable_config["profiles"]["candidate"]["context"]["dimension_weights"] = {
            "trend_regime": 1.10,
            "price_structure": 1.05,
            "momentum": 0.90,
            "risk_balance": 1.15,
            "account_posture": 0.10,
            "liquidity": 0.95,
            "session": 0.60,
            "source_prior": 0.85,
            "execution_feedback": 0.10,
        }
        stable_config["profiles"]["candidate"]["dual_track"] = {
            "fusion_buy_threshold": 0.43,
            "fusion_sell_threshold": -0.26,
            "sell_precedence_gate": -0.34,
            "min_fusion_confidence": 0.46,
        }
        stable_config["profiles"]["position"]["technical"]["group_weights"] = {
            "trend": 1.10,
            "momentum": 0.90,
            "volume_confirmation": 0.95,
            "volatility_risk": 1.20,
        }
        stable_config["profiles"]["position"]["technical"]["dimension_weights"] = {
            "trend_direction": 1.05,
            "ma_alignment": 0.95,
            "ma_slope": 1.10,
            "price_vs_ma20": 0.90,
            "macd_level": 0.95,
            "macd_hist_slope": 0.95,
            "rsi_zone": 0.80,
            "kdj_cross": 0.55,
            "volume_ratio": 0.90,
            "obv_trend": 0.95,
            "atr_risk": 1.35,
            "boll_position": 1.15,
        }
        stable_config["profiles"]["position"]["context"]["group_weights"] = {
            "market_structure": 1.00,
            "risk_account": 1.40,
            "tradability_timing": 0.70,
            "source_execution": 0.75,
        }
        stable_config["profiles"]["position"]["context"]["dimension_weights"] = {
            "trend_regime": 1.00,
            "price_structure": 1.00,
            "momentum": 0.80,
            "risk_balance": 1.35,
            "account_posture": 1.20,
            "liquidity": 0.85,
            "session": 0.55,
            "source_prior": 0.75,
            "execution_feedback": 0.90,
        }
        stable_config["profiles"]["position"]["dual_track"] = {
            "fusion_buy_threshold": 0.57,
            "fusion_sell_threshold": -0.20,
            "sell_precedence_gate": -0.26,
            "min_fusion_confidence": 0.50,
        }

        conservative_config = self._deep_copy_json(base_config)
        conservative_config["base"]["dual_track"]["mode"] = "hybrid"
        conservative_config["base"]["dual_track"]["track_weights"] = {"tech": 0.90, "context": 1.10}
        conservative_config["base"]["dual_track"]["fusion_buy_threshold"] = 0.80
        conservative_config["base"]["dual_track"]["fusion_sell_threshold"] = -0.10
        conservative_config["base"]["dual_track"]["sell_precedence_gate"] = -0.36
        conservative_config["base"]["dual_track"]["min_fusion_confidence"] = 0.58
        conservative_config["base"]["dual_track"]["min_tech_score_for_buy"] = 0.05
        conservative_config["base"]["dual_track"]["min_context_score_for_buy"] = 0.03
        conservative_config["base"]["dual_track"]["min_tech_confidence_for_buy"] = 0.54
        conservative_config["base"]["dual_track"]["min_context_confidence_for_buy"] = 0.56
        conservative_config["base"]["dual_track"]["lambda_divergence"] = 0.75
        conservative_config["base"]["dual_track"]["lambda_sign_conflict"] = 0.50
        conservative_config["base"]["dual_track"]["sign_conflict_min_abs_score"] = 0.15
        conservative_config["profiles"]["candidate"]["technical"]["group_weights"] = {
            "trend": 1.05,
            "momentum": 0.80,
            "volume_confirmation": 0.90,
            "volatility_risk": 1.35,
        }
        conservative_config["profiles"]["candidate"]["technical"]["dimension_weights"] = {
            "trend_direction": 1.00,
            "ma_alignment": 0.90,
            "ma_slope": 1.00,
            "price_vs_ma20": 0.85,
            "macd_level": 0.80,
            "macd_hist_slope": 0.85,
            "rsi_zone": 0.75,
            "kdj_cross": 0.25,
            "volume_ratio": 0.85,
            "obv_trend": 1.00,
            "atr_risk": 1.55,
            "boll_position": 1.25,
        }
        conservative_config["profiles"]["candidate"]["context"]["group_weights"] = {
            "market_structure": 1.00,
            "risk_account": 1.65,
            "tradability_timing": 0.75,
            "source_execution": 0.60,
        }
        conservative_config["profiles"]["candidate"]["context"]["dimension_weights"] = {
            "trend_regime": 0.95,
            "price_structure": 1.00,
            "momentum": 0.75,
            "risk_balance": 1.50,
            "account_posture": 0.15,
            "liquidity": 0.90,
            "session": 0.55,
            "source_prior": 0.70,
            "execution_feedback": 0.12,
        }
        conservative_config["profiles"]["candidate"]["dual_track"] = {
            "fusion_buy_threshold": 0.48,
            "fusion_sell_threshold": -0.22,
            "sell_precedence_gate": -0.30,
            "min_fusion_confidence": 0.56,
        }
        conservative_config["profiles"]["position"]["technical"]["group_weights"] = {
            "trend": 0.95,
            "momentum": 0.65,
            "volume_confirmation": 0.85,
            "volatility_risk": 1.70,
        }
        conservative_config["profiles"]["position"]["technical"]["dimension_weights"] = {
            "trend_direction": 0.90,
            "ma_alignment": 0.85,
            "ma_slope": 0.95,
            "price_vs_ma20": 0.80,
            "macd_level": 0.70,
            "macd_hist_slope": 0.75,
            "rsi_zone": 0.70,
            "kdj_cross": 0.40,
            "volume_ratio": 0.80,
            "obv_trend": 0.85,
            "atr_risk": 1.65,
            "boll_position": 1.45,
        }
        conservative_config["profiles"]["position"]["context"]["group_weights"] = {
            "market_structure": 0.90,
            "risk_account": 1.80,
            "tradability_timing": 0.65,
            "source_execution": 0.55,
        }
        conservative_config["profiles"]["position"]["context"]["dimension_weights"] = {
            "trend_regime": 0.85,
            "price_structure": 0.90,
            "momentum": 0.70,
            "risk_balance": 1.65,
            "account_posture": 1.45,
            "liquidity": 0.80,
            "session": 0.50,
            "source_prior": 0.65,
            "execution_feedback": 1.10,
        }
        conservative_config["profiles"]["position"]["dual_track"] = {
            "fusion_buy_threshold": 0.58,
            "fusion_sell_threshold": -0.16,
            "sell_precedence_gate": -0.22,
            "min_fusion_confidence": 0.60,
        }

        return {
            "aggressive": aggressive_config,
            "stable": stable_config,
            "conservative": conservative_config,
        }

    def _ensure_default_strategy_profile(self, cursor: sqlite3.Cursor) -> None:
        now_text = self._now()
        builtin_configs = self._build_builtin_strategy_profile_configs()

        for builtin in BUILTIN_STRATEGY_PROFILES:
            profile_id = builtin["id"]
            profile_name = builtin["name"]
            description = builtin["description"]
            variant = builtin["variant"]

            cursor.execute("SELECT id FROM strategy_profiles WHERE id = ?", (profile_id,))
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    INSERT INTO strategy_profiles
                    (id, name, description, enabled, is_default, created_at, updated_at)
                    VALUES (?, ?, ?, 1, 0, ?, ?)
                    """,
                    (profile_id, profile_name, description, now_text, now_text),
                )
            else:
                cursor.execute(
                    """
                    UPDATE strategy_profiles
                    SET name = ?, description = ?, enabled = 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (profile_name, description, now_text, profile_id),
                )

            target_config = self._deep_copy_json(builtin_configs[variant])
            cursor.execute(
                """
                SELECT config_json, note
                FROM strategy_profile_versions
                WHERE profile_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (profile_id,),
            )
            latest_version_row = cursor.fetchone()
            if latest_version_row is None:
                self._insert_strategy_profile_version(
                    cursor,
                    profile_id=profile_id,
                    config=target_config,
                    note=f"bootstrap_{variant}",
                )
            else:
                latest_note = str(latest_version_row["note"] or "").strip().lower()
                latest_config_raw = latest_version_row["config_json"]
                latest_config: dict[str, Any] = {}
                if isinstance(latest_config_raw, str):
                    try:
                        parsed_latest = json.loads(latest_config_raw)
                        if isinstance(parsed_latest, dict):
                            latest_config = parsed_latest
                    except Exception:
                        latest_config = {}
                target_signature = json.dumps(target_config, ensure_ascii=False, sort_keys=True)
                latest_signature = json.dumps(latest_config, ensure_ascii=False, sort_keys=True)
                if (
                    latest_note.startswith("bootstrap_")
                    or latest_note.startswith("builtin_refresh_")
                ) and latest_signature != target_signature:
                    self._insert_strategy_profile_version(
                        cursor,
                        profile_id=profile_id,
                        config=target_config,
                        note=f"builtin_refresh_{variant}",
                    )

        cursor.execute(
            "UPDATE strategy_profiles SET enabled = 0, is_default = 0, updated_at = ? WHERE id = ?",
            (now_text, LEGACY_DEFAULT_STRATEGY_PROFILE_ID),
        )
        cursor.execute(
            """
            SELECT id
            FROM strategy_profiles
            WHERE is_default = 1 AND enabled = 1
            ORDER BY updated_at DESC, id ASC
            LIMIT 1
            """
        )
        current_default = cursor.fetchone()
        current_default_id = str(current_default["id"]).strip() if current_default is not None else ""
        if not current_default_id:
            cursor.execute("UPDATE strategy_profiles SET is_default = 0, updated_at = ?", (now_text,))
            cursor.execute(
                "UPDATE strategy_profiles SET is_default = 1, enabled = 1, updated_at = ? WHERE id = ?",
                (now_text, DEFAULT_STRATEGY_PROFILE_ID),
            )
        cursor.execute(
            """
            UPDATE sim_scheduler_config
            SET strategy_profile_id = CASE
                    WHEN strategy_profile_id IS NULL OR strategy_profile_id = '' OR strategy_profile_id = ?
                    THEN ?
                    ELSE strategy_profile_id
                END,
                updated_at = ?
            WHERE id = 1
            """,
            (LEGACY_DEFAULT_STRATEGY_PROFILE_ID, DEFAULT_STRATEGY_PROFILE_ID, now_text),
        )

    def _validate_and_normalize_strategy_profile_config(self, config: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise ValueError("strategy profile config must be an object")
        schema_version = str(config.get("schema_version") or "quant_explain").strip() or "quant_explain"
        base = config.get("base")
        profiles = config.get("profiles")
        if not isinstance(base, dict) or not isinstance(profiles, dict):
            raise ValueError("strategy profile config requires base and profiles")
        strategy = StrategyScoringConfig(schema_version=schema_version, base=base, profiles=profiles)
        strategy.resolve("candidate")
        strategy.resolve("position")
        return {
            "schema_version": schema_version,
            "base": json.loads(json.dumps(base)),
            "profiles": json.loads(json.dumps(profiles)),
        }

    def _insert_strategy_profile_version(
        self,
        cursor: sqlite3.Cursor,
        *,
        profile_id: str,
        config: dict[str, Any],
        note: str | None = None,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS max_version
            FROM strategy_profile_versions
            WHERE profile_id = ?
            """,
            (profile_id,),
        )
        row = cursor.fetchone()
        next_version = int((row["max_version"] if row is not None else 0) or 0) + 1
        now_text = self._now()
        cursor.execute(
            """
            INSERT INTO strategy_profile_versions
            (profile_id, version, config_json, note, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                next_version,
                json.dumps(config, ensure_ascii=False),
                str(note or "").strip() or None,
                now_text,
            ),
        )
        version_id = int(cursor.lastrowid)
        return {
            "id": version_id,
            "profile_id": profile_id,
            "version": next_version,
            "config": config,
            "note": str(note or "").strip(),
            "created_at": now_text,
        }

    @staticmethod
    def _strategy_profile_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"] or row["id"]),
            "description": str(row["description"] or ""),
            "enabled": bool(row["enabled"]),
            "is_default": bool(row["is_default"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _strategy_profile_version_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        config = self._loads_metadata(row["config_json"])
        return {
            "id": int(row["id"]),
            "profile_id": str(row["profile_id"]),
            "version": int(row["version"]),
            "config": config,
            "note": str(row["note"] or ""),
            "created_at": row["created_at"],
        }

    def _candidate_row_to_dict(self, cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._row_to_dict(row)
        payload["metadata"] = self._loads_metadata(payload.pop("metadata_json", None))
        payload["sources"] = self._get_candidate_sources(cursor, int(row["id"]))
        return payload

    def _signal_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._row_to_dict(row)
        if "metadata_json" in payload:
            payload["metadata"] = self._loads_metadata(payload.get("metadata_json"))
        payload["strategy_profile"] = self._loads_metadata(payload.pop("strategy_profile_json", None))
        if "strategy_profile_snapshot_json" in payload:
            payload["strategy_profile_snapshot"] = self._loads_metadata(payload.pop("strategy_profile_snapshot_json", None))
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
        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO candidate_sources (candidate_id, source, created_at)
                VALUES (?, ?, ?)
                """,
                (candidate_id, source, self._now()),
            )
        except sqlite3.OperationalError:
            # 兼容历史库: candidate_sources 可能没有 created_at 字段
            cursor.execute(
                """
                INSERT OR IGNORE INTO candidate_sources (candidate_id, source)
                VALUES (?, ?)
                """,
                (candidate_id, source),
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
    def _next_trading_day(current_date: date) -> date:
        return TRADING_DAY_CALENDAR.next_trading_day(current_date)

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
    def _dumps_metadata(payload: Optional[dict[str, Any]]) -> Optional[str]:
        if not payload:
            return None
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _normalize_optional_int(value: Any) -> int | None:
        try:
            if value in (None, ""):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

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
