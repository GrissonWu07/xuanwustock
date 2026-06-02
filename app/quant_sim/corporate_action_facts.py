"""Local-first stock corporate-action facts and scoped accounting application."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import logging
import sqlite3
from typing import Any, Protocol

from app.quant_sim.db import CorporateActionApplicationInput, QuantSimDB
from app.quant_sim.time_utils import format_local_time, parse_system_datetime

logger = logging.getLogger(__name__)

CORPORATE_ACTION_DATA_VERSION = "ca_v1"
CORPORATE_ACTION_PROVIDER = "akshare"
PROVIDER_FAILED_RETRY_MINUTES = 30
SUPPORTED_ACTION_TYPES = {
    "cash_dividend",
    "bonus_share",
    "share_transfer",
    "mixed_dividend_share",
}
TERMINAL_COVERAGE_STATUSES = {"remote_fetched", "empty_range", "local_hit"}


class CorporateActionProvider(Protocol):
    def get_actions(self, stock_code: str, start_datetime: datetime, end_datetime: datetime) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class CorporateActionFact:
    stock_code: str
    market: str
    action_type: str
    ex_date: str
    record_date: str = ""
    bonus_share_ratio: float = 0.0
    cash_dividend_per_share: float = 0.0
    description: str = ""
    provider: str = CORPORATE_ACTION_PROVIDER
    source_status: str = "ready"
    reason_code: str = "ok"
    data_version: str = CORPORATE_ACTION_DATA_VERSION
    raw: dict[str, Any] = field(default_factory=dict)
    fetched_at: str | None = None
    action_ref: str | None = None

    def normalized_ref(self) -> str:
        return self.action_ref or build_action_ref(
            data_version=self.data_version,
            market=self.market,
            stock_code=self.stock_code,
            action_type=self.action_type,
            ex_date=self.ex_date,
            record_date=self.record_date,
            bonus_share_ratio=self.bonus_share_ratio,
            cash_dividend_per_share=self.cash_dividend_per_share,
        )

    @property
    def is_supported(self) -> bool:
        return self.action_type in SUPPORTED_ACTION_TYPES and self.source_status not in {"unsupported", "raw_only"}


@dataclass(frozen=True)
class CorporateActionCoverage:
    stock_code: str
    market: str
    start_date: str
    end_date: str
    provider: str
    source_status: str
    reason_code: str = "ok"
    facts_count: int = 0
    checked_at: str | None = None
    retry_after: str | None = None
    valid_until: str | None = None


@dataclass(frozen=True)
class CorporateActionQuery:
    stock_code: str
    market: str
    start_datetime: datetime
    end_datetime: datetime
    provider: str = CORPORATE_ACTION_PROVIDER
    trace_id: str | None = None


@dataclass(frozen=True)
class CorporateActionScope:
    scope_type: str
    scope_id: str


@dataclass(frozen=True)
class CorporateActionApplicationCommand:
    account_db: QuantSimDB
    fact_service: "CorporateActionFactService"
    scope: CorporateActionScope
    checkpoint: datetime
    market: str = "CN"
    trace_id: str | None = None


@dataclass(frozen=True)
class CorporateActionQueryResult:
    facts: list[CorporateActionFact]
    summary: dict[str, int]
    reason_code: str = "ok"


@dataclass(frozen=True)
class CorporateActionApplicationResult:
    applied_count: int
    skipped_count: int
    summary: dict[str, int]
    applied_refs: list[str] = field(default_factory=list)


def normalize_action_type(bonus_share_ratio: float, cash_dividend_per_share: float, raw_type: str | None = None) -> str:
    normalized = str(raw_type or "").strip()
    if normalized in SUPPORTED_ACTION_TYPES or normalized in {"unsupported", "raw_only"}:
        return normalized
    has_bonus = float(bonus_share_ratio or 0.0) > 0
    has_cash = float(cash_dividend_per_share or 0.0) > 0
    if has_bonus and has_cash:
        return "mixed_dividend_share"
    if has_bonus:
        return "share_transfer"
    if has_cash:
        return "cash_dividend"
    return "unsupported"


def build_action_ref(
    *,
    data_version: str,
    market: str,
    stock_code: str,
    action_type: str,
    ex_date: str,
    record_date: str,
    bonus_share_ratio: float,
    cash_dividend_per_share: float,
) -> str:
    parts = [
        "ca",
        _clean(data_version),
        _clean(market).upper(),
        _clean(stock_code).upper(),
        _clean(action_type),
        _clean(ex_date),
        _clean(record_date),
        _decimal_text(bonus_share_ratio),
        _decimal_text(cash_dividend_per_share),
    ]
    return ":".join(parts)


def fact_from_provider_action(action: dict[str, Any], *, market: str = "CN", provider: str = CORPORATE_ACTION_PROVIDER) -> CorporateActionFact:
    stock_code = _clean(action.get("stock_code")).upper()
    ex_date = _date_text(action.get("ex_date"))
    record_date = _date_text(action.get("record_date"))
    bonus = _float(action.get("bonus_share_ratio"))
    cash = _float(action.get("cash_dividend_per_share"))
    action_type = normalize_action_type(bonus, cash, str(action.get("action_type") or ""))
    source_status = "ready" if action_type in SUPPORTED_ACTION_TYPES else "unsupported"
    reason_code = "ok" if source_status == "ready" else "unsupported_action_type"
    return CorporateActionFact(
        stock_code=stock_code,
        market=_clean(action.get("market") or market).upper() or "CN",
        action_type=action_type,
        ex_date=ex_date,
        record_date=record_date,
        bonus_share_ratio=bonus,
        cash_dividend_per_share=cash,
        description=str(action.get("description") or ""),
        provider=provider,
        source_status=source_status,
        reason_code=reason_code,
        raw=dict(action),
        fetched_at=format_local_time(),
    )


class CorporateActionFactStore:
    """Repository for stock-level corporate action facts and coverage."""

    def __init__(self, db: QuantSimDB):
        self.db = db

    def upsert_facts(self, facts: list[CorporateActionFact]) -> list[CorporateActionFact]:
        if not facts:
            return []
        conn = self.db._connect()
        cursor = conn.cursor()
        now = format_local_time()
        stored: list[CorporateActionFact] = []
        try:
            for fact in facts:
                action_ref = fact.normalized_ref()
                payload = (
                    action_ref,
                    fact.stock_code,
                    fact.market,
                    fact.action_type,
                    fact.ex_date,
                    fact.record_date or "",
                    float(fact.bonus_share_ratio or 0.0),
                    float(fact.cash_dividend_per_share or 0.0),
                    fact.description,
                    fact.provider,
                    fact.source_status,
                    fact.reason_code,
                    fact.data_version,
                    json.dumps(fact.raw or {}, ensure_ascii=False),
                    fact.fetched_at or now,
                    now,
                )
                cursor.execute("SELECT id FROM corporate_action_facts WHERE action_ref = ?", (action_ref,))
                existing = cursor.fetchone()
                if existing:
                    cursor.execute(
                        """
                        UPDATE corporate_action_facts
                        SET stock_code = ?, market = ?, action_type = ?, ex_date = ?, record_date = ?,
                            bonus_share_ratio = ?, cash_dividend_per_share = ?, description = ?,
                            provider = ?, source_status = ?, reason_code = ?, data_version = ?,
                            raw_json = ?, fetched_at = ?, updated_at = ?
                        WHERE action_ref = ?
                        """,
                        payload[1:] + (action_ref,),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO corporate_action_facts
                        (
                            action_ref, stock_code, market, action_type, ex_date, record_date,
                            bonus_share_ratio, cash_dividend_per_share, description, provider,
                            source_status, reason_code, data_version, raw_json, fetched_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        payload,
                    )
                stored.append(CorporateActionFact(**{**fact.__dict__, "action_ref": action_ref}))
            conn.commit()
        finally:
            conn.close()
        return stored

    def list_facts(self, query: CorporateActionQuery) -> list[CorporateActionFact]:
        conn = self.db._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM corporate_action_facts
            WHERE stock_code = ? AND market = ? AND ex_date >= ? AND ex_date <= ?
            ORDER BY ex_date ASC, action_ref ASC
            """,
            (
                _clean(query.stock_code).upper(),
                _clean(query.market).upper() or "CN",
                query.start_datetime.date().isoformat(),
                query.end_datetime.date().isoformat(),
            ),
        )
        rows = [self._fact_from_row(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def list_coverage(self, query: CorporateActionQuery) -> list[CorporateActionCoverage]:
        conn = self.db._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM corporate_action_coverage
            WHERE stock_code = ? AND market = ? AND provider = ?
              AND end_date >= ? AND start_date <= ?
            ORDER BY start_date ASC, end_date ASC, id ASC
            """,
            (
                _clean(query.stock_code).upper(),
                _clean(query.market).upper() or "CN",
                query.provider,
                query.start_datetime.date().isoformat(),
                query.end_datetime.date().isoformat(),
            ),
        )
        rows = [self._coverage_from_row(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def upsert_coverage(self, coverage: CorporateActionCoverage) -> None:
        conn = self.db._connect()
        cursor = conn.cursor()
        now = format_local_time()
        key = (
            coverage.stock_code,
            coverage.market,
            coverage.start_date,
            coverage.end_date,
            coverage.provider,
        )
        cursor.execute(
            """
            SELECT id FROM corporate_action_coverage
            WHERE stock_code = ? AND market = ? AND start_date = ? AND end_date = ? AND provider = ?
            """,
            key,
        )
        existing = cursor.fetchone()
        payload = (
            coverage.source_status,
            coverage.reason_code,
            int(coverage.facts_count or 0),
            coverage.checked_at or now,
            coverage.retry_after,
            coverage.valid_until,
            now,
        )
        if existing:
            cursor.execute(
                """
                UPDATE corporate_action_coverage
                SET source_status = ?, reason_code = ?, facts_count = ?, checked_at = ?,
                    retry_after = ?, valid_until = ?, updated_at = ?
                WHERE stock_code = ? AND market = ? AND start_date = ? AND end_date = ? AND provider = ?
                """,
                payload + key,
            )
        else:
            cursor.execute(
                """
                INSERT INTO corporate_action_coverage
                (
                    stock_code, market, start_date, end_date, provider, source_status,
                    reason_code, facts_count, checked_at, retry_after, valid_until, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                key + payload,
            )
        conn.commit()
        conn.close()

    @staticmethod
    def _fact_from_row(row: sqlite3.Row) -> CorporateActionFact:
        raw_json = row["raw_json"] or "{}"
        try:
            raw = json.loads(raw_json)
        except json.JSONDecodeError:
            raw = {}
        return CorporateActionFact(
            action_ref=row["action_ref"],
            stock_code=row["stock_code"],
            market=row["market"],
            action_type=row["action_type"],
            ex_date=row["ex_date"],
            record_date=row["record_date"] or "",
            bonus_share_ratio=float(row["bonus_share_ratio"] or 0.0),
            cash_dividend_per_share=float(row["cash_dividend_per_share"] or 0.0),
            description=row["description"] or "",
            provider=row["provider"] or CORPORATE_ACTION_PROVIDER,
            source_status=row["source_status"] or "ready",
            reason_code=row["reason_code"] or "ok",
            data_version=row["data_version"] or CORPORATE_ACTION_DATA_VERSION,
            raw=raw,
            fetched_at=row["fetched_at"],
        )

    @staticmethod
    def _coverage_from_row(row: sqlite3.Row) -> CorporateActionCoverage:
        return CorporateActionCoverage(
            stock_code=row["stock_code"],
            market=row["market"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            provider=row["provider"],
            source_status=row["source_status"],
            reason_code=row["reason_code"] or "ok",
            facts_count=int(row["facts_count"] or 0),
            checked_at=row["checked_at"],
            retry_after=row["retry_after"],
            valid_until=row["valid_until"],
        )


class CorporateActionFactService:
    """Local-first corporate action lookup with stable coverage diagnostics."""

    def __init__(
        self,
        store: CorporateActionFactStore,
        provider: CorporateActionProvider | None = None,
        *,
        provider_name: str = CORPORATE_ACTION_PROVIDER,
        retry_minutes: int = PROVIDER_FAILED_RETRY_MINUTES,
    ):
        self.store = store
        self.provider = provider
        self.provider_name = provider_name
        self.retry_minutes = retry_minutes

    def get_actions(self, query: CorporateActionQuery) -> CorporateActionQueryResult:
        normalized = self._normalize_query(query)
        facts = self.store.list_facts(normalized)
        coverage = self.store.list_coverage(normalized)
        summary = _empty_summary()
        if _coverage_covers(coverage, normalized, statuses=TERMINAL_COVERAGE_STATUSES):
            summary["local_hit"] += 1
            return CorporateActionQueryResult(facts=facts, summary=summary)

        active_failure = _active_provider_failure(coverage)
        if active_failure is not None:
            summary["provider_failed"] += 1
            return CorporateActionQueryResult(facts=facts, summary=summary, reason_code=active_failure.reason_code)

        uncovered = _uncovered_ranges(coverage, normalized)
        if facts:
            summary["partial_missing"] += 1
        fetched_facts: list[CorporateActionFact] = []
        for start_date, end_date in uncovered:
            fetched_facts.extend(self._fetch_and_store(normalized, start_date, end_date, summary))
        all_facts = self.store.list_facts(normalized) if fetched_facts else facts
        return CorporateActionQueryResult(facts=all_facts, summary=summary)

    def _fetch_and_store(
        self,
        query: CorporateActionQuery,
        start_date: date,
        end_date: date,
        summary: dict[str, int],
    ) -> list[CorporateActionFact]:
        if self.provider is None:
            self._record_failure(query, start_date, end_date, "provider_unavailable")
            summary["provider_failed"] += 1
            return []
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time()).replace(microsecond=0)
        try:
            raw_actions = self.provider.get_actions(query.stock_code, start_dt, end_dt)
        except Exception as exc:
            self._record_failure(query, start_date, end_date, "provider_exception")
            summary["provider_failed"] += 1
            logger.warning(
                "corporate_action_provider_failed",
                extra={
                    "trace_id": query.trace_id,
                    "stock_code": query.stock_code,
                    "market": query.market,
                    "provider": self.provider_name,
                    "reason_code": "provider_exception",
                    "error_type": type(exc).__name__,
                },
            )
            return []
        facts = [
            fact_from_provider_action(action, market=query.market, provider=self.provider_name)
            for action in raw_actions
        ]
        facts = [fact for fact in facts if fact.ex_date and start_date <= _parse_date(fact.ex_date) <= end_date]
        stored = self.store.upsert_facts(facts)
        status = "remote_fetched" if stored else "empty_range"
        summary[status] += 1
        self.store.upsert_coverage(
            CorporateActionCoverage(
                stock_code=query.stock_code,
                market=query.market,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                provider=self.provider_name,
                source_status=status,
                reason_code="ok",
                facts_count=len(stored),
                checked_at=format_local_time(),
            )
        )
        logger.debug(
            "corporate_action_remote_fetch",
            extra={
                "trace_id": query.trace_id,
                "stock_code": query.stock_code,
                "market": query.market,
                "provider": self.provider_name,
                "source_status": status,
                "facts_count": len(stored),
            },
        )
        return stored

    def _record_failure(self, query: CorporateActionQuery, start_date: date, end_date: date, reason_code: str) -> None:
        now_dt = datetime.now().replace(microsecond=0)
        retry_at = now_dt + timedelta(minutes=max(1, int(self.retry_minutes or PROVIDER_FAILED_RETRY_MINUTES)))
        self.store.upsert_coverage(
            CorporateActionCoverage(
                stock_code=query.stock_code,
                market=query.market,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                provider=self.provider_name,
                source_status="provider_failed",
                reason_code=reason_code,
                facts_count=0,
                checked_at=format_local_time(now_dt),
                retry_after=format_local_time(retry_at),
                valid_until=format_local_time(retry_at),
            )
        )

    def _normalize_query(self, query: CorporateActionQuery) -> CorporateActionQuery:
        return CorporateActionQuery(
            stock_code=_clean(query.stock_code).upper(),
            market=_clean(query.market).upper() or "CN",
            start_datetime=query.start_datetime,
            end_datetime=query.end_datetime,
            provider=query.provider or self.provider_name,
            trace_id=query.trace_id,
        )


class CorporateActionApplicationService:
    """Apply due corporate actions before checkpoint valuation and decisions."""

    def apply_due_actions(self, command: CorporateActionApplicationCommand) -> CorporateActionApplicationResult:
        positions = command.account_db.get_positions(as_of=command.checkpoint)
        if not positions:
            return CorporateActionApplicationResult(applied_count=0, skipped_count=0, summary=_empty_summary())
        summary = _empty_summary()
        applied_refs: list[str] = []
        skipped = 0
        checkpoint_date = command.checkpoint.date()
        for position in positions:
            stock_code = _clean(position.get("stock_code")).upper()
            if not stock_code:
                continue
            lots = command.account_db.get_position_lots(stock_code, as_of=command.checkpoint)
            start_date = _earliest_lot_date(lots) or checkpoint_date
            query = CorporateActionQuery(
                stock_code=stock_code,
                market=command.market,
                start_datetime=datetime.combine(start_date, datetime.min.time()),
                end_datetime=datetime.combine(checkpoint_date, datetime.max.time()).replace(microsecond=0),
                trace_id=command.trace_id,
            )
            result = command.fact_service.get_actions(query)
            _merge_summary(summary, result.summary)
            for fact in sorted(result.facts, key=lambda item: (item.ex_date, item.normalized_ref())):
                if _parse_date(fact.ex_date) > checkpoint_date:
                    continue
                if not fact.is_supported:
                    skipped += 1
                    continue
                did_apply = command.account_db.apply_corporate_action(
                    stock_code=fact.stock_code,
                    ex_date=fact.ex_date,
                    record_date=fact.record_date or None,
                    bonus_share_ratio=fact.bonus_share_ratio,
                    cash_dividend_per_share=fact.cash_dividend_per_share,
                    description=fact.description,
                    applied_at=command.checkpoint,
                    scope_type=command.scope.scope_type,
                    scope_id=command.scope.scope_id,
                    market=fact.market,
                    action_ref=fact.normalized_ref(),
                    action_type=fact.action_type,
                )
                if did_apply:
                    applied_refs.append(fact.normalized_ref())
                    logger.info(
                        "corporate_action_due_applied",
                        extra={
                            "trace_id": command.trace_id,
                            "scope_type": command.scope.scope_type,
                            "scope_id": command.scope.scope_id,
                            "stock_code": fact.stock_code,
                            "market": fact.market,
                            "action_ref": fact.normalized_ref(),
                            "ex_date": fact.ex_date,
                        },
                    )
                else:
                    skipped += 1
        return CorporateActionApplicationResult(
            applied_count=len(applied_refs),
            skipped_count=skipped,
            summary=summary,
            applied_refs=applied_refs,
        )


def _empty_summary() -> dict[str, int]:
    return {
        "local_hit": 0,
        "remote_fetched": 0,
        "empty_range": 0,
        "provider_failed": 0,
        "partial_missing": 0,
    }


def _merge_summary(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = int(target.get(key, 0)) + int(value or 0)


def _coverage_covers(
    coverage: list[CorporateActionCoverage],
    query: CorporateActionQuery,
    *,
    statuses: set[str],
) -> bool:
    start = query.start_datetime.date()
    end = query.end_datetime.date()
    return any(
        item.source_status in statuses
        and _parse_date(item.start_date) <= start
        and _parse_date(item.end_date) >= end
        for item in coverage
    )


def _active_provider_failure(coverage: list[CorporateActionCoverage]) -> CorporateActionCoverage | None:
    now = datetime.now().replace(microsecond=0)
    for item in coverage:
        if item.source_status != "provider_failed":
            continue
        valid_until = _parse_datetime(item.valid_until or item.retry_after)
        if valid_until and valid_until > now:
            return item
    return None


def _uncovered_ranges(coverage: list[CorporateActionCoverage], query: CorporateActionQuery) -> list[tuple[date, date]]:
    start = query.start_datetime.date()
    end = query.end_datetime.date()
    covered = sorted(
        (
            max(start, _parse_date(item.start_date)),
            min(end, _parse_date(item.end_date)),
        )
        for item in coverage
        if item.source_status in TERMINAL_COVERAGE_STATUSES and _parse_date(item.end_date) >= start and _parse_date(item.start_date) <= end
    )
    ranges: list[tuple[date, date]] = []
    cursor = start
    for covered_start, covered_end in covered:
        if covered_start > cursor:
            ranges.append((cursor, covered_start - timedelta(days=1)))
        if covered_end >= cursor:
            cursor = covered_end + timedelta(days=1)
    if cursor <= end:
        ranges.append((cursor, end))
    return ranges


def _earliest_lot_date(lots: list[dict[str, Any]]) -> date | None:
    dates: list[date] = []
    for lot in lots:
        text = str(lot.get("entry_date") or str(lot.get("entry_time") or "")[:10]).strip()
        if text:
            dates.append(_parse_date(text))
    return min(dates) if dates else None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _date_text(value: Any) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = _clean(value)
    if not text:
        return ""
    return _parse_date(text).isoformat()


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return parse_system_datetime(str(value)[:19]).date()


def _parse_datetime(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return parse_system_datetime(text)
    except Exception:
        return None


def _decimal_text(value: float) -> str:
    try:
        decimal = Decimal(str(value or 0)).normalize()
    except (InvalidOperation, ValueError):
        decimal = Decimal("0")
    text = format(decimal, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
