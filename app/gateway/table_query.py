from __future__ import annotations

from app.gateway.deps import *
from app.gateway.constants import REPLAY_TABLE_PAGE_SIZE

def _normalize_replay_table_page(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _normalize_replay_table_page_size(value: Any, default: int = REPLAY_TABLE_PAGE_SIZE) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, 100))


def _replay_actions_for_filter(value: Any) -> list[str] | None:
    normalized = str(value or "").strip().upper()
    if not normalized or normalized == "ALL":
        return None
    if normalized == "TRADE":
        return ["BUY", "SELL"]
    if normalized in {"BUY", "SELL", "HOLD"}:
        return [normalized]
    return None


def _replay_table_pagination(page: int, page_size: int, total: int) -> dict[str, int]:
    pages = max(1, (max(0, total) + page_size - 1) // page_size)
    current_page = min(max(1, page), pages)
    return {"page": current_page, "pageSize": page_size, "totalRows": max(0, total), "totalPages": pages}


def _replay_table_query_from_request(request: Request | None) -> dict[str, Any]:
    if request is None:
        return {}
    params = request.query_params
    page_size = _normalize_replay_table_page_size(params.get("pageSize") or params.get("page_size"))
    trade_page_size = _normalize_replay_table_page_size(
        params.get("tradePageSize") or params.get("trade_page_size") or page_size,
        default=page_size,
    )
    signal_page_size = _normalize_replay_table_page_size(
        params.get("signalPageSize") or params.get("signal_page_size") or page_size,
        default=page_size,
    )
    return {
        "search": params.get("search") or "",
        "page": _normalize_replay_table_page(params.get("page")),
        "pageSize": page_size,
        "page_size": page_size,
        "trade_page": _normalize_replay_table_page(params.get("tradePage") or params.get("trade_page")),
        "trade_page_size": trade_page_size,
        "trade_action": params.get("tradeAction") or params.get("trade_action") or "ALL",
        "trade_stock": params.get("tradeStock") or params.get("trade_stock") or "",
        "signal_page": _normalize_replay_table_page(params.get("signalPage") or params.get("signal_page")),
        "signal_page_size": signal_page_size,
        "signal_action": params.get("signalAction") or params.get("signal_action") or "ALL",
        "signal_stock": params.get("signalStock") or params.get("signal_stock") or "",
        "run_id": params.get("runId") or params.get("run_id") or "",
        "checkpoint_at": params.get("checkpointAt") or params.get("checkpoint_at") or "",
        "checkpoint_page": _normalize_replay_table_page(params.get("checkpointPage") or params.get("checkpoint_page")),
        "checkpoint_page_size": _normalize_replay_table_page_size(params.get("checkpointPageSize") or params.get("checkpoint_page_size"), default=50),
        "checkpoint_search": params.get("checkpointSearch") or params.get("checkpoint_search") or "",
    }
