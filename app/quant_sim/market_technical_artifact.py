"""Market technical artifact identity and data objects.

The artifact stores checkpoint facts. ``checkpoint_at`` is the market fact
time, while ``computed_at`` is when this system wrote the artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote


ARTIFACT_REF_PREFIX = "mta:v1"
LIVE_DOMAIN = "live"
REPLAY_DOMAIN = "replay"
DRILL_DOMAIN = "drill"
LIVE_RUN_SCOPE = "live"
DEFAULT_DATA_VERSION = "mta_v1"

VALID_DOMAINS = {LIVE_DOMAIN, REPLAY_DOMAIN, DRILL_DOMAIN}
VALID_RUN_TYPES = {LIVE_RUN_SCOPE, "historical_replay", "live_quant_drill"}
VALID_SOURCE_STATUSES = {"ready", "partial", "missing", "source_failed", "stale", "invalid"}
VALID_REASON_CODES = {
    "ok",
    "missing_artifact",
    "missing_artifact_reference",
    "incomplete_artifact",
    "source_failed",
    "run_scope_required",
    "invalid_artifact_ref",
    "stale_artifact",
    "field_missing",
    "source_status_not_ready",
}
FORBIDDEN_SOURCE_KEYS = {"source_score", "source_confidence", "multi_source_bonus"}


def _encode(value: str) -> str:
    return quote(str(value), safe="")


def _decode(value: str) -> str:
    return unquote(value)


def _scrub_forbidden_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _scrub_forbidden_keys(item)
            for key, item in value.items()
            if key not in FORBIDDEN_SOURCE_KEYS
        }
    if isinstance(value, list):
        return [_scrub_forbidden_keys(item) for item in value]
    return value


def _sorted_strings(values: list[str] | None) -> list[str]:
    return sorted(str(value) for value in (values or []))


@dataclass(frozen=True)
class InvalidArtifactRef:
    """Parse result for invalid refs without raising at API boundaries."""

    raw_ref: str
    reason_code: str = "invalid_artifact_ref"


@dataclass(frozen=True)
class MarketTechnicalArtifactRef:
    """Stable external identity for a checkpoint market technical artifact."""

    domain: str
    run_id: str
    run_type: str
    stock_code: str
    market: str
    checkpoint_at: str
    timeframe: str
    data_version: str = DEFAULT_DATA_VERSION

    @classmethod
    def live(
        cls,
        *,
        stock_code: str,
        market: str,
        checkpoint_at: str,
        timeframe: str,
        data_version: str = DEFAULT_DATA_VERSION,
    ) -> "MarketTechnicalArtifactRef":
        return cls(
            domain=LIVE_DOMAIN,
            run_id=LIVE_RUN_SCOPE,
            run_type=LIVE_RUN_SCOPE,
            stock_code=stock_code,
            market=market,
            checkpoint_at=checkpoint_at,
            timeframe=timeframe,
            data_version=data_version,
        )

    def validate(self) -> str:
        if self.domain not in VALID_DOMAINS:
            return "invalid_artifact_ref"
        if self.domain == LIVE_DOMAIN and (
            self.run_id != LIVE_RUN_SCOPE or self.run_type != LIVE_RUN_SCOPE
        ):
            return "run_scope_required"
        if self.domain in {REPLAY_DOMAIN, DRILL_DOMAIN} and (
            not self.run_id or not self.run_type or self.run_type == LIVE_RUN_SCOPE
        ):
            return "run_scope_required"
        if self.run_type not in VALID_RUN_TYPES:
            return "invalid_artifact_ref"
        required = [
            self.stock_code,
            self.market,
            self.checkpoint_at,
            self.timeframe,
            self.data_version,
        ]
        if any(not value for value in required):
            return "invalid_artifact_ref"
        return "ok"

    def to_ref(self) -> str:
        parts = {
            "domain": self.domain,
            "run_id": self.run_id,
            "run_type": self.run_type,
            "market": self.market,
            "stock_code": self.stock_code,
            "checkpoint_at": self.checkpoint_at,
            "timeframe": self.timeframe,
            "data_version": self.data_version,
        }
        serialized = "|".join(f"{key}={_encode(value)}" for key, value in parts.items())
        return f"{ARTIFACT_REF_PREFIX}|{serialized}"


def parse_artifact_ref(ref: str | None) -> MarketTechnicalArtifactRef | InvalidArtifactRef:
    if not ref or not ref.startswith(f"{ARTIFACT_REF_PREFIX}|"):
        return InvalidArtifactRef(raw_ref=str(ref or ""))
    try:
        pairs = ref.split("|")[1:]
        values = {}
        for pair in pairs:
            key, raw_value = pair.split("=", 1)
            values[key] = _decode(raw_value)
        artifact_ref = MarketTechnicalArtifactRef(
            domain=values["domain"],
            run_id=values["run_id"],
            run_type=values["run_type"],
            stock_code=values["stock_code"],
            market=values["market"],
            checkpoint_at=values["checkpoint_at"],
            timeframe=values["timeframe"],
            data_version=values["data_version"],
        )
    except (KeyError, ValueError):
        return InvalidArtifactRef(raw_ref=ref)
    reason_code = artifact_ref.validate()
    if reason_code != "ok":
        return InvalidArtifactRef(raw_ref=ref, reason_code=reason_code)
    return artifact_ref


@dataclass
class MarketTechnicalArtifactData:
    """Market, indicator, structure, tradability, and quality facts."""

    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    latest_price: float | None = None
    prev_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    ma20_slope: float | None = None
    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    trend: str | None = None
    price_vs_ma20: float | None = None
    price_vs_ma60: float | None = None
    ma_stack: str | None = None
    above_ma20_checkpoints: int | None = None
    retest_confirmed: bool | None = None
    is_suspended: bool | None = None
    is_limit_up: bool | None = None
    is_limit_down: bool | None = None
    liquidity_ready: bool | None = None
    provider: str | None = None
    indicator_version: str | None = None
    source_status: str = "missing"
    reason_code: str = "missing_artifact"
    missing_fields: list[str] = field(default_factory=list)
    computed_at: str | None = None
    market_json: dict[str, Any] = field(default_factory=dict)
    indicator_json: dict[str, Any] = field(default_factory=dict)
    structure_json: dict[str, Any] = field(default_factory=dict)
    quality_json: dict[str, Any] = field(default_factory=dict)
    provider_diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.missing_fields = _sorted_strings(self.missing_fields)
        self.source_status = (
            self.source_status if self.source_status in VALID_SOURCE_STATUSES else "invalid"
        )
        self.reason_code = self.reason_code if self.reason_code in VALID_REASON_CODES else "invalid_artifact_ref"
        self.market_json = _scrub_forbidden_keys(
            {
                **self.market_json,
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "prev_close": self.prev_close,
                "volume": self.volume,
                "amount": self.amount,
                "turnover_rate": self.turnover_rate,
            }
        )
        self.indicator_json = _scrub_forbidden_keys(
            {
                **self.indicator_json,
                "ma5": self.ma5,
                "ma10": self.ma10,
                "ma60": self.ma60,
                "macd_signal": self.macd_signal,
                "macd_histogram": self.macd_histogram,
            }
        )
        self.structure_json = _scrub_forbidden_keys(
            {
                **self.structure_json,
                "trend": self.trend,
                "price_vs_ma20": self.price_vs_ma20,
                "price_vs_ma60": self.price_vs_ma60,
                "ma_stack": self.ma_stack,
                "above_ma20_checkpoints": self.above_ma20_checkpoints,
                "retest_confirmed": self.retest_confirmed,
            }
        )
        self.quality_json = _scrub_forbidden_keys(
            {
                **self.quality_json,
                "missing_fields": self.missing_fields,
                "provider_diagnostics": _scrub_forbidden_keys(self.provider_diagnostics),
            }
        )


@dataclass(frozen=True)
class ArtifactWriteRequest:
    ref: MarketTechnicalArtifactRef
    data: MarketTechnicalArtifactData
    trace_id: str = "NO_TRACE"


@dataclass(frozen=True)
class ArtifactQuery:
    domain: str
    stock_code: str
    market: str
    checkpoint_at: str
    timeframe: str
    data_version: str = DEFAULT_DATA_VERSION
    run_id: str | None = None
    run_type: str | None = None

    def to_ref_or_reason(self) -> MarketTechnicalArtifactRef | str:
        if self.domain == LIVE_DOMAIN:
            if self.run_id or self.run_type:
                return "run_scope_required"
            return MarketTechnicalArtifactRef.live(
                stock_code=self.stock_code,
                market=self.market,
                checkpoint_at=self.checkpoint_at,
                timeframe=self.timeframe,
                data_version=self.data_version,
            )
        if self.domain in {REPLAY_DOMAIN, DRILL_DOMAIN}:
            if not self.run_id or not self.run_type:
                return "run_scope_required"
            ref = MarketTechnicalArtifactRef(
                domain=self.domain,
                run_id=self.run_id,
                run_type=self.run_type,
                stock_code=self.stock_code,
                market=self.market,
                checkpoint_at=self.checkpoint_at,
                timeframe=self.timeframe,
                data_version=self.data_version,
            )
            reason_code = ref.validate()
            return ref if reason_code == "ok" else reason_code
        return "invalid_artifact_ref"


@dataclass(frozen=True)
class MarketTechnicalArtifact:
    ref: MarketTechnicalArtifactRef
    artifact_ref: str
    data: MarketTechnicalArtifactData

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_ref": self.artifact_ref,
            "domain": self.ref.domain,
            "run_id": self.ref.run_id,
            "run_type": self.ref.run_type,
            "stock_code": self.ref.stock_code,
            "market": self.ref.market,
            "checkpoint_at": self.ref.checkpoint_at,
            "timeframe": self.ref.timeframe,
            "data_version": self.ref.data_version,
            "indicator_version": self.data.indicator_version,
            "source_status": self.data.source_status,
            "reason_code": self.data.reason_code,
            "missing_fields": self.data.missing_fields,
            "open": self.data.open,
            "high": self.data.high,
            "low": self.data.low,
            "close": self.data.close,
            "latest_price": self.data.latest_price,
            "prev_close": self.data.prev_close,
            "volume": self.data.volume,
            "amount": self.data.amount,
            "turnover_rate": self.data.turnover_rate,
            "volume_ratio": self.data.volume_ratio,
            "ma5": self.data.ma5,
            "ma10": self.data.ma10,
            "ma20": self.data.ma20,
            "ma60": self.data.ma60,
            "ma20_slope": self.data.ma20_slope,
            "rsi": self.data.rsi,
            "macd": self.data.macd,
            "macd_signal": self.data.macd_signal,
            "macd_histogram": self.data.macd_histogram,
            "trend": self.data.trend,
            "price_vs_ma20": self.data.price_vs_ma20,
            "price_vs_ma60": self.data.price_vs_ma60,
            "ma_stack": self.data.ma_stack,
            "above_ma20_checkpoints": self.data.above_ma20_checkpoints,
            "retest_confirmed": self.data.retest_confirmed,
            "is_suspended": self.data.is_suspended,
            "is_limit_up": self.data.is_limit_up,
            "is_limit_down": self.data.is_limit_down,
            "liquidity_ready": self.data.liquidity_ready,
            "provider": self.data.provider,
            "computed_at": self.data.computed_at,
            "market_json": self.data.market_json,
            "indicator_json": self.data.indicator_json,
            "structure_json": self.data.structure_json,
            "quality_json": self.data.quality_json,
        }


@dataclass(frozen=True)
class ArtifactReadResult:
    artifact: MarketTechnicalArtifact | None
    reason_code: str
    source_status: str = "missing"
    missing_fields: list[str] = field(default_factory=list)
