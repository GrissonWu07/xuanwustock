"""Read valid stock-analysis context records for trading decisions."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.db.runtime.legacy_dbapi import legacy_dbapi_connection
from app.db.runtime.legacy_sqlite import resolve_legacy_sqlite_db_path
from app.db.runtime.registry import DatabaseRuntime
from app.runtime_paths import default_db_path


def _parse_persisted_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value).strip()
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            elif "T" not in text and " " in text:
                text = text.replace(" ", "T", 1)
            parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo or timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0)
    except (TypeError, ValueError):
        return None


def _row_value(row: sqlite3.Row, key: str) -> Any:
    return row[key] if key in row.keys() else None


def _load_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


class StockAnalysisContextRepository:
    """Select stock-analysis context under realtime/replay as-of rules."""

    REPLAY_ALLOWED_QUALITY = {"exact", "asof_precomputed"}

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        db_runtime: DatabaseRuntime | None = None,
    ):
        self.db_path = resolve_legacy_sqlite_db_path(
            db_path=db_path,
            db_runtime=db_runtime,
            store="primary",
            fallback=default_db_path("xuanwu_stock.db"),
        )
        self.db_runtime = db_runtime

    def get_latest_valid(
        self,
        symbol: str,
        *,
        as_of: datetime | str | None = None,
        mode: str = "realtime",
        ttl_hours: float = 48.0,
        min_confidence: float = 0.0,
    ) -> dict[str, Any] | None:
        code = str(symbol or "").strip()
        if not code:
            return None
        as_of_dt = _parse_persisted_dt(as_of) or _parse_persisted_dt(datetime.now()) or datetime.now(timezone.utc).replace(microsecond=0)
        fallback_start = as_of_dt - timedelta(hours=max(float(ttl_hours), 0.0))
        conn = legacy_dbapi_connection(
            db_path=self.db_path,
            db_runtime=self.db_runtime,
            access_mode="readonly",
            row_factory=True,
        )
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM analysis_records
                WHERE symbol = ?
                ORDER BY id DESC
                """,
                (code,),
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()

        replay_mode = str(mode or "").lower() == "replay"
        candidates: list[tuple[datetime, int, sqlite3.Row, dict[str, Any], str]] = []
        for row in rows:
            data_as_of_dt = (
                _parse_persisted_dt(_row_value(row, "data_as_of"))
                or _parse_persisted_dt(_row_value(row, "created_at"))
                or _parse_persisted_dt(_row_value(row, "analysis_date"))
            )
            created_at_dt = _parse_persisted_dt(_row_value(row, "created_at")) or _parse_persisted_dt(_row_value(row, "analysis_date"))
            if data_as_of_dt is None or created_at_dt is None:
                continue
            valid_until_dt = _parse_persisted_dt(_row_value(row, "valid_until")) or (data_as_of_dt + timedelta(hours=48))
            if data_as_of_dt > as_of_dt:
                continue
            if valid_until_dt < as_of_dt:
                continue
            if created_at_dt > as_of_dt or created_at_dt < fallback_start:
                continue
            context = _load_json(_row_value(row, "analysis_context_json"), {})
            if not isinstance(context, dict) or not context:
                continue
            quality = str(_row_value(row, "data_as_of_quality") or "").strip()
            candidates.append((data_as_of_dt, int(row["id"]), row, context, quality))

        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for _, _, row, context, quality in candidates[:20]:
            if replay_mode and quality not in self.REPLAY_ALLOWED_QUALITY:
                continue
            confidence = self._to_float(context.get("confidence"), 0.0)
            if confidence < float(min_confidence):
                continue
            score = self._to_float(context.get("score"), 0.0)
            effective_score = self._to_float(context.get("effective_score"), score * confidence)
            return {
                "used": True,
                "record_id": int(row["id"]),
                "symbol": row["symbol"],
                "stock_name": row["stock_name"],
                "score": round(score, 6),
                "effective_score": round(effective_score, 6),
                "confidence": round(confidence, 6),
                "summary": str(context.get("summary") or ""),
                "data_as_of": _row_value(row, "data_as_of"),
                "data_as_of_quality": quality or "unknown",
                "valid_until": _row_value(row, "valid_until"),
                "generated_at": row["created_at"],
                "normalizer_version": context.get("normalizer_version"),
            }
        return None

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
            if parsed != parsed:
                return default
            return parsed
        except (TypeError, ValueError):
            return default
