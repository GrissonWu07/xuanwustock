"""AI scanner strategy adapter for discovery."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.discover.ai_stock_scanner import AIStockScanner, AIStockScannerConfig
from app.discover.lifecycle_scoring import normalize_discovery_lifecycle_row
from app.gateway.common import first_non_empty as _first_non_empty
from app.gateway.common import int_value as _int
from app.gateway.common import num as _num
from app.gateway.common import txt as _txt
from app.i18n import t
from app.watchlist_selector_integration import normalize_stock_code


def run_ai_scanner_strategy(
    payload: dict[str, Any],
    *,
    top_n: int,
    scanner_cls: Any = AIStockScanner,
    config_cls: Any = AIStockScannerConfig,
) -> pd.DataFrame:
    """Run AI scanner and map its rows to discovery lifecycle rows."""

    top_k_sectors = max(_int(payload.get("topKSectors"), 5) or 5, 1)
    max_stocks = max(_int(payload.get("maxStocks"), top_n) or top_n, 1)
    lookback_days = max(_int(payload.get("lookbackDays"), 180) or 180, 1)
    max_candidates_per_sector = max(_int(payload.get("maxCandidatesPerSector"), 5) or 5, 1)

    config = config_cls(
        top_k_sectors=top_k_sectors,
        max_stocks=max_stocks,
        max_candidates_per_sector=max_candidates_per_sector,
        lookback_days=lookback_days,
    )
    scanner_df = scanner_cls(config).scan()

    if scanner_df is None or getattr(scanner_df, "empty", False):
        raise RuntimeError(t("AI scanner returned no selected stocks"))

    rows: list[dict[str, Any]] = []
    try:
        selected_stocks = scanner_df.to_dict(orient="records")
    except Exception:
        selected_stocks = []
    for item in selected_stocks:
        if not isinstance(item, dict):
            continue
        code = _discover_code(item.get("股票代码") or item.get("code") or item.get("symbol"))
        if not code:
            continue
        reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
        reason_text = _txt(item.get("reason")) or "；".join(_txt(reason) for reason in reasons if _txt(reason))
        score_raw = item.get("scanner_score")
        reason_parts: list[str] = []
        if score_raw not in (None, ""):
            reason_parts.append(t("Scanner score: {score}", score=_num(score_raw)))
        if reason_text:
            reason_parts.append(reason_text)
        if not reason_parts:
            reason_parts.append(t("AI scanner selected candidate"))

        normalized = dict(item)
        normalized.update(
            {
                "股票代码": code,
                "股票简称": _txt(item.get("股票简称") or item.get("name"), code),
                "所属行业": _txt(item.get("所属行业") or item.get("sector")),
                "最新价": _first_non_empty(item, ["最新价", "latest_price", "current_price", "price"]),
                "总市值": _first_non_empty(item, ["总市值", "market_cap", "total_market_value", "marketCap"]),
                "市盈率": _first_non_empty(item, ["市盈率", "pe", "pe_ratio", "pe_ttm"]),
                "市净率": _first_non_empty(item, ["市净率", "pb", "pb_ratio"]),
                "reason": " | ".join(reason_parts),
            }
        )
        rows.append(
            normalize_discovery_lifecycle_row(
                normalized,
                strategy_key="ai_scanner",
                strategy_name=t("AI stock selection"),
                rank=len(rows) + 1,
                total=len(selected_stocks),
            )
        )

    if not rows:
        raise RuntimeError(t("AI scanner returned no selected stocks"))

    return pd.DataFrame(rows)


def _discover_code(value: Any) -> str:
    code = normalize_stock_code(value)
    if not code:
        return ""
    if code.isdigit() and len(code) < 6:
        try:
            return f"{int(code):06d}"
        except (TypeError, ValueError):
            return code
    return code


__all__ = ["run_ai_scanner_strategy"]
