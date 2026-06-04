"""SQLite store for market technical artifacts."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from app.db.runtime.legacy_dbapi import legacy_dbapi_connection
from app.quant_sim.market_technical_artifact import (
    ArtifactQuery,
    ArtifactReadResult,
    ArtifactWindowResult,
    ArtifactWriteRequest,
    InvalidArtifactRef,
    DRILL_DOMAIN,
    LIVE_DOMAIN,
    MarketTechnicalArtifact,
    MarketTechnicalArtifactData,
    MarketTechnicalArtifactRef,
    REPLAY_DOMAIN,
    parse_artifact_ref,
)
from app.quant_sim.time_utils import local_now_text

logger = logging.getLogger(__name__)

LIVE_TABLE = "market_technical_artifacts"
RUN_TABLE = "sim_run_market_technical_artifacts"


class MarketTechnicalArtifactStore:
    """Repository for live and run-scoped artifact tables."""

    def __init__(self, db_file: str | Path, *, store_name: str | None = None):
        self.db_file = Path(db_file)
        self.store_name = store_name or self._infer_store_name(self.db_file)

    def ensure_schema(self, *, domain: str | None = LIVE_DOMAIN) -> None:
        target_domain = domain or LIVE_DOMAIN
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            if target_domain == LIVE_DOMAIN:
                self._create_live_schema(conn)
            if target_domain in (REPLAY_DOMAIN, DRILL_DOMAIN):
                self._create_run_schema(conn)
            conn.commit()

    def upsert(self, request: ArtifactWriteRequest) -> MarketTechnicalArtifact:
        artifacts = self.upsert_many([request])
        if not artifacts:
            raise ValueError("empty_artifact_batch")
        return artifacts[0]

    def upsert_many(self, requests: list[ArtifactWriteRequest]) -> list[MarketTechnicalArtifact]:
        if not requests:
            return []
        normalized: list[tuple[ArtifactWriteRequest, str, str, dict[str, Any]]] = []
        domains: set[str] = set()
        for request in requests:
            reason_code = request.ref.validate()
            if reason_code != "ok":
                raise ValueError(reason_code)
            artifact_ref = request.ref.to_ref()
            table = self._table_for_ref(request.ref)
            payload = self._row_payload(request, artifact_ref)
            normalized.append((request, artifact_ref, table, payload))
            domains.add(request.ref.domain)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            if LIVE_DOMAIN in domains:
                self._create_live_schema(conn)
            if domains.intersection({REPLAY_DOMAIN, DRILL_DOMAIN}):
                self._create_run_schema(conn)
            for _, _, table, payload in normalized:
                columns = ", ".join(payload.keys())
                placeholders = ", ".join("?" for _ in payload)
                updates = ", ".join(f"{key}=excluded.{key}" for key in payload if key != "artifact_ref")
                conn.execute(
                    f"""
                    INSERT INTO {table} ({columns})
                    VALUES ({placeholders})
                    ON CONFLICT(artifact_ref) DO UPDATE SET {updates}
                    """,
                    tuple(payload.values()),
                )
            conn.commit()
        artifacts: list[MarketTechnicalArtifact] = []
        for request, artifact_ref, _, _ in normalized:
            logger.debug(
                "market_technical_artifact_upserted",
                extra={
                    "trace_id": request.trace_id,
                    "artifact_domain": request.ref.domain,
                    "run_id": request.ref.run_id,
                    "run_type": request.ref.run_type,
                    "stock_code": request.ref.stock_code,
                    "market": request.ref.market,
                    "checkpoint_at": request.ref.checkpoint_at,
                    "timeframe": request.ref.timeframe,
                    "data_version": request.ref.data_version,
                    "source_status": request.data.source_status,
                    "missing_fields": request.data.missing_fields,
                },
            )
            artifacts.append(MarketTechnicalArtifact(ref=request.ref, artifact_ref=artifact_ref, data=request.data))
        return artifacts

    def get_by_ref(self, artifact_ref: str | None, *, log_missing: bool = True) -> ArtifactReadResult:
        parsed = parse_artifact_ref(artifact_ref)
        if isinstance(parsed, InvalidArtifactRef):
            return ArtifactReadResult(artifact=None, reason_code=parsed.reason_code)
        return self._get_by_ref(parsed, artifact_ref or "", log_missing=log_missing)

    def get_by_query(self, query: ArtifactQuery) -> ArtifactReadResult:
        ref_or_reason = query.to_ref_or_reason()
        if isinstance(ref_or_reason, str):
            return ArtifactReadResult(artifact=None, reason_code=ref_or_reason)
        return self._get_by_ref(ref_or_reason, ref_or_reason.to_ref())

    def future_window_by_ref(
        self,
        artifact_ref: str | None,
        *,
        horizon_checkpoints: int,
        as_of_checkpoint: str | None = None,
    ) -> ArtifactWindowResult:
        parsed = parse_artifact_ref(artifact_ref)
        if isinstance(parsed, InvalidArtifactRef):
            return ArtifactWindowResult(
                source=None,
                window=[],
                reason_code=parsed.reason_code,
                requested_horizon=max(0, int(horizon_checkpoints or 0)),
            )
        source = self._get_by_ref(parsed, artifact_ref or "")
        if source.artifact is None:
            return ArtifactWindowResult(
                source=None,
                window=[],
                reason_code=source.reason_code,
                requested_horizon=max(0, int(horizon_checkpoints or 0)),
            )
        window = self._future_window(
            parsed,
            horizon_checkpoints=max(0, int(horizon_checkpoints or 0)),
            as_of_checkpoint=as_of_checkpoint,
        )
        reason = "ok" if len(window) >= int(horizon_checkpoints or 0) else "horizon_not_mature"
        return ArtifactWindowResult(
            source=source.artifact,
            window=window,
            reason_code=reason,
            requested_horizon=max(0, int(horizon_checkpoints or 0)),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = legacy_dbapi_connection(
            db_path=self.db_file,
            store=self.store_name,
            row_factory=True,
        )
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _infer_store_name(db_file: Path) -> str:
        return "replay" if "replay" in db_file.name.lower() else "primary"

    def _create_table(self, conn: sqlite3.Connection, table: str) -> None:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_ref TEXT NOT NULL UNIQUE,
                artifact_domain TEXT NOT NULL,
                run_id TEXT NOT NULL,
                run_type TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                market TEXT NOT NULL,
                checkpoint_at TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                data_version TEXT NOT NULL,
                provider TEXT,
                indicator_version TEXT,
                source_status TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                computed_at TEXT,
                latest_price REAL,
                close REAL,
                ma20 REAL,
                ma20_slope REAL,
                rsi REAL,
                macd REAL,
                volume_ratio REAL,
                is_suspended INTEGER,
                is_limit_up INTEGER,
                is_limit_down INTEGER,
                liquidity_ready INTEGER,
                market_json TEXT NOT NULL DEFAULT '{{}}',
                indicator_json TEXT NOT NULL DEFAULT '{{}}',
                structure_json TEXT NOT NULL DEFAULT '{{}}',
                quality_json TEXT NOT NULL DEFAULT '{{}}',
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """
        )

    def _create_live_schema(self, conn: sqlite3.Connection) -> None:
        self._create_table(conn, LIVE_TABLE)
        conn.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_{LIVE_TABLE}_identity
            ON {LIVE_TABLE} (
                artifact_domain, stock_code, market, checkpoint_at,
                timeframe, data_version
            )
            """
        )

    def _create_run_schema(self, conn: sqlite3.Connection) -> None:
        self._create_table(conn, RUN_TABLE)
        conn.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_{RUN_TABLE}_identity
            ON {RUN_TABLE} (
                artifact_domain, run_id, run_type, stock_code, market,
                checkpoint_at, timeframe, data_version
            )
            """
        )

    def _table_for_ref(self, ref: MarketTechnicalArtifactRef) -> str:
        return LIVE_TABLE if ref.domain == LIVE_DOMAIN else RUN_TABLE

    def _row_payload(self, request: ArtifactWriteRequest, artifact_ref: str) -> dict[str, Any]:
        data = request.data
        computed_at = data.computed_at or local_now_text()
        return {
            "artifact_ref": artifact_ref,
            "artifact_domain": request.ref.domain,
            "run_id": request.ref.run_id,
            "run_type": request.ref.run_type,
            "stock_code": request.ref.stock_code,
            "market": request.ref.market,
            "checkpoint_at": request.ref.checkpoint_at,
            "timeframe": request.ref.timeframe,
            "data_version": request.ref.data_version,
            "provider": data.provider,
            "indicator_version": data.indicator_version,
            "source_status": data.source_status,
            "reason_code": data.reason_code,
            "computed_at": computed_at,
            "latest_price": data.latest_price,
            "close": data.close,
            "ma20": data.ma20,
            "ma20_slope": data.ma20_slope,
            "rsi": data.rsi,
            "macd": data.macd,
            "volume_ratio": data.volume_ratio,
            "is_suspended": self._bool_to_int(data.is_suspended),
            "is_limit_up": self._bool_to_int(data.is_limit_up),
            "is_limit_down": self._bool_to_int(data.is_limit_down),
            "liquidity_ready": self._bool_to_int(data.liquidity_ready),
            "market_json": self._json(data.market_json),
            "indicator_json": self._json(data.indicator_json),
            "structure_json": self._json(data.structure_json),
            "quality_json": self._json(data.quality_json),
            "updated_at": computed_at,
        }

    def _get_by_ref(
        self,
        ref: MarketTechnicalArtifactRef,
        artifact_ref: str,
        *,
        log_missing: bool = True,
    ) -> ArtifactReadResult:
        table = self._table_for_ref(ref)
        with closing(self._connect()) as conn:
            if not self._table_exists(conn, table):
                row = None
            else:
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE artifact_ref = ?",
                    (artifact_ref,),
                ).fetchone()
        if row is None:
            if not log_missing:
                return ArtifactReadResult(artifact=None, reason_code="missing_artifact")
            logger.warning(
                "market_technical_artifact_missing",
                extra={
                    "trace_id": "NO_TRACE",
                    "artifact_domain": ref.domain,
                    "run_id": ref.run_id,
                    "run_type": ref.run_type,
                    "stock_code": ref.stock_code,
                    "market": ref.market,
                    "checkpoint_at": ref.checkpoint_at,
                    "timeframe": ref.timeframe,
                    "data_version": ref.data_version,
                    "source_status": "missing",
                    "missing_fields": [],
                },
            )
            return ArtifactReadResult(artifact=None, reason_code="missing_artifact")
        artifact = self._artifact_from_row(row)
        return ArtifactReadResult(
            artifact=artifact,
            reason_code=artifact.data.reason_code,
            source_status=artifact.data.source_status,
            missing_fields=artifact.data.missing_fields,
        )

    def _future_window(
        self,
        ref: MarketTechnicalArtifactRef,
        *,
        horizon_checkpoints: int,
        as_of_checkpoint: str | None = None,
    ) -> list[MarketTechnicalArtifact]:
        if horizon_checkpoints <= 0:
            return []
        table = self._table_for_ref(ref)
        with closing(self._connect()) as conn:
            if not self._table_exists(conn, table):
                return []
            as_of_text = str(as_of_checkpoint or "").strip()
            as_of_clause = "AND checkpoint_at <= ?" if as_of_text else ""
            params: list[Any] = [
                ref.domain,
                ref.run_id,
                ref.run_type,
                ref.stock_code,
                ref.market,
                ref.timeframe,
                ref.data_version,
                ref.checkpoint_at,
            ]
            if as_of_text:
                params.append(as_of_text)
            params.append(horizon_checkpoints)
            rows = conn.execute(
                f"""
                SELECT *
                FROM {table}
                WHERE artifact_domain = ?
                  AND run_id = ?
                  AND run_type = ?
                  AND stock_code = ?
                  AND market = ?
                  AND timeframe = ?
                  AND data_version = ?
                  AND checkpoint_at > ?
                  {as_of_clause}
                ORDER BY checkpoint_at ASC, id ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def _table_exists(self, conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def _artifact_from_row(self, row: sqlite3.Row) -> MarketTechnicalArtifact:
        ref = MarketTechnicalArtifactRef(
            domain=row["artifact_domain"],
            run_id=row["run_id"],
            run_type=row["run_type"],
            stock_code=row["stock_code"],
            market=row["market"],
            checkpoint_at=row["checkpoint_at"],
            timeframe=row["timeframe"],
            data_version=row["data_version"],
        )
        quality_json = self._loads(row["quality_json"])
        data = MarketTechnicalArtifactData(
            open=self._loads(row["market_json"]).get("open"),
            high=self._loads(row["market_json"]).get("high"),
            low=self._loads(row["market_json"]).get("low"),
            close=row["close"],
            latest_price=row["latest_price"],
            prev_close=self._loads(row["market_json"]).get("prev_close"),
            volume=self._loads(row["market_json"]).get("volume"),
            amount=self._loads(row["market_json"]).get("amount"),
            turnover_rate=self._loads(row["market_json"]).get("turnover_rate"),
            volume_ratio=row["volume_ratio"],
            ma5=self._loads(row["indicator_json"]).get("ma5"),
            ma10=self._loads(row["indicator_json"]).get("ma10"),
            ma20=row["ma20"],
            ma60=self._loads(row["indicator_json"]).get("ma60"),
            ma20_slope=row["ma20_slope"],
            rsi=row["rsi"],
            macd=row["macd"],
            macd_signal=self._loads(row["indicator_json"]).get("macd_signal"),
            macd_histogram=self._loads(row["indicator_json"]).get("macd_histogram"),
            trend=self._loads(row["structure_json"]).get("trend"),
            price_vs_ma20=self._loads(row["structure_json"]).get("price_vs_ma20"),
            price_vs_ma60=self._loads(row["structure_json"]).get("price_vs_ma60"),
            ma_stack=self._loads(row["structure_json"]).get("ma_stack"),
            above_ma20_checkpoints=self._loads(row["structure_json"]).get("above_ma20_checkpoints"),
            retest_confirmed=self._loads(row["structure_json"]).get("retest_confirmed"),
            is_suspended=self._int_to_bool(row["is_suspended"]),
            is_limit_up=self._int_to_bool(row["is_limit_up"]),
            is_limit_down=self._int_to_bool(row["is_limit_down"]),
            liquidity_ready=self._int_to_bool(row["liquidity_ready"]),
            provider=row["provider"],
            indicator_version=row["indicator_version"],
            source_status=row["source_status"],
            reason_code=row["reason_code"],
            missing_fields=quality_json.get("missing_fields", []),
            computed_at=row["computed_at"],
            market_json=self._loads(row["market_json"]),
            indicator_json=self._loads(row["indicator_json"]),
            structure_json=self._loads(row["structure_json"]),
            quality_json=quality_json,
            provider_diagnostics=quality_json.get("provider_diagnostics", {}),
        )
        return MarketTechnicalArtifact(ref=ref, artifact_ref=row["artifact_ref"], data=data)

    def _json(self, value: dict[str, Any]) -> str:
        return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)

    def _loads(self, value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}

    def _bool_to_int(self, value: bool | None) -> int | None:
        if value is None:
            return None
        return 1 if value else 0

    def _int_to_bool(self, value: int | None) -> bool | None:
        if value is None:
            return None
        return bool(value)
