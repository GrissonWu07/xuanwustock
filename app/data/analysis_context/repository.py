"""Read valid stock-analysis context records for trading decisions."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.runtime_paths import default_db_path


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


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

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or default_db_path("stock_analysis.db"))

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
        as_of_dt = _parse_dt(as_of) or datetime.now()
        fallback_start = as_of_dt - timedelta(hours=max(float(ttl_hours), 0.0))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM analysis_records
                WHERE symbol = ?
                  AND datetime(COALESCE(data_as_of, created_at, analysis_date)) <= datetime(?)
                  AND datetime(COALESCE(valid_until, datetime(COALESCE(data_as_of, created_at, analysis_date), '+48 hours'))) >= datetime(?)
                  AND datetime(COALESCE(created_at, analysis_date)) <= datetime(?)
                  AND datetime(COALESCE(created_at, analysis_date)) >= datetime(?)
                ORDER BY datetime(COALESCE(data_as_of, created_at, analysis_date)) DESC, id DESC
                LIMIT 20
                """,
                (
                    code,
                    as_of_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    as_of_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    as_of_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    fallback_start.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()

        replay_mode = str(mode or "").lower() == "replay"
        for row in rows:
            context = _load_json(row["analysis_context_json"] if "analysis_context_json" in row.keys() else None, {})
            if not isinstance(context, dict) or not context:
                continue
            quality = str(row["data_as_of_quality"] if "data_as_of_quality" in row.keys() and row["data_as_of_quality"] else "").strip()
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
                "data_as_of": row["data_as_of"] if "data_as_of" in row.keys() else None,
                "data_as_of_quality": quality or "unknown",
                "valid_until": row["valid_until"] if "valid_until" in row.keys() else None,
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
