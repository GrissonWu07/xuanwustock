from __future__ import annotations

from app.gateway.deps import *
from app.gateway.context import UIApiContext
from app.gateway.table_query import _normalize_replay_table_page, _normalize_replay_table_page_size, _replay_table_pagination
from app.gateway.workbench_analysis import _build_cached_workbench_analysis_payload

def _candidate_rows(
    context: "UIApiContext",
    status: str | None = None,
    *,
    include_actions: bool = False,
    limit: int | None = None,
    offset: int = 0,
    search: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in context.candidate_pool().list_candidates(status=status, limit=limit, offset=offset, search=search):
        code = normalize_stock_code(item.get("stock_code"))
        actions = []
        if include_actions:
            actions = [
                {"label": "分析候选股", "icon": "🔎", "tone": "accent", "action": "analyze-candidate"},
                {"label": "删除候选股", "icon": "🗑", "tone": "danger", "action": "delete-candidate"},
            ]
        rows.append(
            {
                "id": code,
                "cells": [code, _txt(item.get("stock_name") or code), _txt(item.get("source") or "watchlist"), _num(item.get("latest_price"))],
                "actions": actions,
                "code": code,
                "name": _txt(item.get("stock_name") or code),
                "source": _txt(item.get("source") or "watchlist"),
                "latestPrice": _num(item.get("latest_price")),
            }
        )
    return rows


def _indicator_alias_value(indicators: dict[str, Any], aliases: list[str]) -> Any:
    for alias in aliases:
        if alias in indicators:
            return indicators.get(alias)
    lowered = {str(key).lower(): value for key, value in indicators.items()}
    for alias in aliases:
        alias_key = str(alias).lower()
        if alias_key in lowered:
            return lowered.get(alias_key)
    return None


def _build_portfolio_indicator_cards(
    indicators: dict[str, Any] | None,
    explanations: dict[str, dict[str, str]] | None,
) -> list[dict[str, Any]]:
    indicators = indicators if isinstance(indicators, dict) else {}
    explanations = explanations if isinstance(explanations, dict) else {}
    specs = [
        ("Price", ["price", "close", "Close"], "Latest traded price."),
        ("Volume", ["volume", "Volume"], "Latest traded volume."),
        ("Volume MA5", ["volume_ma5", "Volume_MA5"], "5-period average volume."),
        ("MA5", ["ma5", "MA5"], "5-day moving average."),
        ("MA10", ["ma10", "MA10"], "10-day moving average."),
        ("MA20", ["ma20", "MA20"], "20-day moving average."),
        ("MA60", ["ma60", "MA60"], "60-day moving average."),
        ("RSI", ["rsi", "RSI"], "Relative strength index."),
        ("MACD", ["macd", "MACD"], "Trend momentum indicator."),
        ("Signal line", ["macd_signal", "MACD_signal"], "MACD signal line."),
        ("Bollinger upper", ["bb_upper", "BB_upper"], "Upper volatility band."),
        ("Bollinger middle", ["bb_middle", "BB_middle"], "Middle volatility band."),
        ("Bollinger lower", ["bb_lower", "BB_lower"], "Lower volatility band."),
        ("K value", ["k_value", "K"], "KDJ fast line."),
        ("D value", ["d_value", "D"], "KDJ slow line."),
        ("Volume ratio", ["volume_ratio", "Volume_ratio", "量比"], "Relative activity vs average volume."),
    ]
    cards: list[dict[str, Any]] = []
    for label, aliases, default_hint in specs:
        value = _indicator_alias_value(indicators, aliases)
        detail = explanations.get(label) if isinstance(explanations.get(label), dict) else None
        hint = _txt(detail.get("summary"), default_hint) if detail else default_hint
        cards.append(
            {
                "label": label,
                "value": _num(value) if isinstance(value, (int, float)) else _txt(value, "--"),
                "hint": hint,
            }
        )
    return cards


def _build_portfolio_kline(stock_data: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    if stock_data is None or not hasattr(stock_data, "tail"):
        return points
    def _row_number(row: Any, aliases: list[str]) -> float | None:
        if not hasattr(row, "get"):
            return None
        for alias in aliases:
            value = row.get(alias)
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None
    try:
        tail = stock_data.tail(160)
        for index, row in tail.iterrows():
            close_number = _row_number(row, ["Close", "收盘", "close"])
            if close_number is None:
                continue
            open_number = _row_number(row, ["Open", "开盘", "open"])
            high_number = _row_number(row, ["High", "最高", "high"])
            low_number = _row_number(row, ["Low", "最低", "low"])
            volume_number = _row_number(row, ["Volume", "成交量", "volume", "vol"])
            if open_number is None:
                open_number = close_number
            if high_number is None:
                high_number = max(open_number, close_number)
            if low_number is None:
                low_number = min(open_number, close_number)
            label = _txt(index)
            if hasattr(index, "strftime"):
                try:
                    label = index.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    label = _txt(index)
            item: dict[str, Any] = {
                "label": label,
                "value": close_number,
                "open": open_number,
                "high": high_number,
                "low": low_number,
                "close": close_number,
            }
            if volume_number is not None:
                item["volume"] = volume_number
            points.append(item)
    except Exception:
        return []
    return points


def _portfolio_technical_snapshot(symbol: str, cycle: str = "1y", *, force_refresh: bool = False) -> dict[str, Any]:
    if not symbol:
        return {"symbol": "", "stockName": "", "sector": "", "kline": [], "indicators": []}
    if force_refresh and hasattr(stock_analysis_service.get_stock_data, "cache_clear"):
        stock_analysis_service.get_stock_data.cache_clear()
    stock_info, stock_data, indicators = stock_analysis_service.get_stock_data(symbol, cycle)
    info = stock_info if isinstance(stock_info, dict) else {}
    indicator_map = indicators if isinstance(indicators, dict) else {}
    indicator_explanations = stock_analysis_service.build_indicator_explanations(
        indicator_map,
        current_price=info.get("current_price"),
    )
    return {
        "symbol": symbol,
        "stockName": _txt(info.get("name"), symbol),
        "sector": _txt(info.get("sector") or info.get("industry") or info.get("board") or info.get("所属行业")),
        "kline": _build_portfolio_kline(stock_data),
        "indicators": _build_portfolio_indicator_cards(indicator_map, indicator_explanations),
    }


_INVALID_STOCK_INFO_TEXTS = {"", "-", "--", "N/A", "NA", "UNKNOWN", "NONE", "NULL", "未知"}


def _stock_info_text(value: Any) -> str:
    text = _txt(value)
    if not text:
        return ""
    if text.strip().upper() in _INVALID_STOCK_INFO_TEXTS or text.strip() in _INVALID_STOCK_INFO_TEXTS:
        return ""
    return text


def _first_stock_info(*values: Any, default: str = "") -> str:
    for value in values:
        text = _stock_info_text(value)
        if text:
            return text
    return default


def _refresh_watchlist_detail_item(context: "UIApiContext", symbol: str) -> dict[str, Any] | None:
    if not symbol:
        return None
    # Detail first paint must stay cache-only; background jobs/manual refresh own remote fetches.
    return context.watchlist().get_watch(symbol)


def _watchlist_sector(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return ""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return _first_stock_info(
        metadata.get("industry"),
        metadata.get("sector"),
        metadata.get("board"),
        metadata.get("所属行业"),
        item.get("source_summary"),
    )


def _market_snapshot_from_watchlist(
    *,
    symbol: str,
    stock_name: str,
    sector: str,
    watch_item: dict[str, Any] | None,
) -> dict[str, Any]:
    watch = watch_item if isinstance(watch_item, dict) else {}
    sources = watch.get("sources") if isinstance(watch.get("sources"), list) else []
    source = _txt(watch.get("source_summary"), _txt(sources[0] if sources else "", "--"))
    latest_price = _float(watch.get("latest_price")) if watch else None
    return {
        "code": symbol,
        "name": stock_name,
        "sector": sector,
        "latestPrice": _num(latest_price, default="--") if latest_price is not None and latest_price > 0 else "--",
        "latestSignal": _txt(watch.get("latest_signal"), "--") if watch else "--",
        "source": source,
        "updatedAt": _system_time_text(watch.get("updated_at"), "--") if watch else "--",
        "inQuantPool": bool(watch.get("in_quant_pool")) if watch else False,
    }


def _technical_snapshot_latest_price(technical: dict[str, Any]) -> float | None:
    kline = technical.get("kline") if isinstance(technical.get("kline"), list) else []
    for point in reversed(kline):
        if not isinstance(point, dict):
            continue
        for key in ("close", "value"):
            price = _float(point.get(key))
            if price is not None and price > 0:
                return price
    indicators = technical.get("indicators") if isinstance(technical.get("indicators"), list) else []
    for item in indicators:
        if not isinstance(item, dict):
            continue
        label = _txt(item.get("label")).lower()
        if label not in {"price", "current price", "latest price", "当前价", "最新价"}:
            continue
        price = _float(item.get("value"))
        if price is not None and price > 0:
            return price
    return None


def _persist_watchlist_snapshot_from_technical(context: "UIApiContext", symbol: str, technical: dict[str, Any]) -> None:
    if not symbol or not isinstance(technical, dict):
        return
    stock_name = _stock_info_text(technical.get("stockName"))
    sector = _stock_info_text(technical.get("sector"))
    latest_price = _technical_snapshot_latest_price(technical)
    metadata: dict[str, Any] = {}
    if sector:
        metadata["industry"] = sector
        metadata["sector"] = sector
    if not stock_name or stock_name == symbol:
        stock_name = None
    if latest_price is None and not stock_name and not metadata:
        return
    try:
        context.watchlist().update_watch_snapshot(
            symbol,
            latest_price=latest_price,
            stock_name=stock_name,
            metadata=metadata or None,
        )
    except Exception:
        pass


def _portfolio_pending_signal_rows(context: "UIApiContext", symbol: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, item in enumerate(context.quant_db().get_pending_signals()):
        code = normalize_stock_code(item.get("stock_code"))
        if symbol and code != symbol:
            continue
        rows.append(
            {
                "id": _txt(item.get("id"), f"pending-{i}"),
                "cells": [
                    _system_time_text(item.get("created_at") or item.get("updated_at"), "--"),
                    code,
                    _txt(item.get("action"), "HOLD").upper(),
                    _txt(item.get("strategy_mode") or item.get("decision_type"), "--"),
                    _txt(item.get("status"), "pending"),
                    _txt(item.get("reasoning") or item.get("execution_note"), "--"),
                ],
                "code": code,
                "name": _txt(item.get("stock_name"), code),
            }
        )
    return rows


def _payload_codes(payload: Any) -> list[str]:
    body = _payload_dict(payload)
    values = body.get("symbols") if isinstance(body.get("symbols"), list) else []
    if not values:
        raw_codes = body.get("codes")
        if isinstance(raw_codes, list):
            values = raw_codes
        elif isinstance(raw_codes, str):
            values = re.split(r"[\s,;，；]+", raw_codes)
    normalized = [normalize_stock_code(_txt(code)) for code in values if _txt(code)]
    return [code for code in normalized if code]


def _load_market_focus_news(context: "UIApiContext", limit: int = 8) -> list[dict[str, Any]]:
    try:
        from app.sector_strategy_db import SectorStrategyDatabase

        db = SectorStrategyDatabase(db_runtime=context.db_runtime)
        payload = db.get_latest_news_data(within_hours=24)
        content = payload.get("data_content") if isinstance(payload, dict) else []
        items: list[dict[str, Any]] = []
        for idx, item in enumerate(content[:limit]):
            if not isinstance(item, dict):
                continue
            title = _txt(item.get("title"), f"市场新闻 {idx + 1}")
            body = _txt(item.get("content")) or _txt(item.get("summary"))
            if len(body) > 180:
                body = f"{body[:180]}..."
            items.append(
                {
                    "title": title,
                    "body": body or "暂无摘要",
                    "source": _txt(item.get("source"), "market"),
                    "time": _system_time_text(item.get("news_date"), "--"),
                    "url": _txt(item.get("url")),
                }
            )
        return items
    except Exception:
        return []


def _build_portfolio_adjustment_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "action": "保持",
            "targetExposurePct": "0%",
            "summary": "当前无持仓，建议先控制仓位并等待有效信号。",
            "bullishCount": 0,
            "neutralCount": 0,
            "bearishCount": 0,
            "score": 0.0,
            "reasons": ["暂无持仓股票数据"],
        }

    bullish = 0
    bearish = 0
    neutral = 0
    weighted_score = 0.0
    total_weight = 0.0
    reasons: list[str] = []
    for item in rows:
        rating = _txt(item.get("rating"), "").upper()
        quantity = _float(item.get("quantity")) or 0.0
        price = _float(item.get("current_price")) or _float(item.get("cost_price")) or 0.0
        weight = max(quantity * price, 1.0)
        confidence = min(max((_float(item.get("confidence")) or 5.0) / 10.0, 0.0), 1.0)

        vote = 0.0
        if ("买" in rating) or ("BUY" in rating):
            bullish += 1
            vote = 1.0
        elif ("卖" in rating) or ("SELL" in rating):
            bearish += 1
            vote = -1.0
        else:
            neutral += 1
            vote = 0.0

        weighted_score += vote * confidence * weight
        total_weight += weight

    normalized_score = weighted_score / total_weight if total_weight > 0 else 0.0
    if normalized_score >= 0.35:
        action = "加仓"
        target_exposure = "70%"
    elif normalized_score <= -0.35:
        action = "降仓"
        target_exposure = "35%"
    else:
        action = "保持"
        target_exposure = "50%"

    reasons.append(f"看多 {bullish} / 中性 {neutral} / 看空 {bearish}")
    reasons.append(f"综合得分 {normalized_score:+.2f}（按仓位和置信度加权）")
    summary = f"组合仓位建议：{action}，建议目标仓位约 {target_exposure}。"
    return {
        "action": action,
        "targetExposurePct": target_exposure,
        "summary": summary,
        "bullishCount": bullish,
        "neutralCount": neutral,
        "bearishCount": bearish,
        "score": round(normalized_score, 4),
        "reasons": reasons,
    }
def _snapshot_portfolio(
    context: UIApiContext,
    *,
    selected_symbol: str | None = None,
    indicator_overrides: dict[str, dict[str, Any]] | None = None,
    analysis_job: dict[str, Any] | None = None,
    table_query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manager = context.portfolio_manager()
    latest_rows = manager.get_all_latest_analysis()
    page_size = _normalize_replay_table_page_size((table_query or {}).get("pageSize"), default=50)
    page = _normalize_replay_table_page((table_query or {}).get("page"))
    search = _txt((table_query or {}).get("search"))
    if hasattr(manager, "count_latest_analysis") and hasattr(manager, "get_latest_analysis_page"):
        page_total = manager.count_latest_analysis(search=search)
        page_pagination = _replay_table_pagination(page, page_size, page_total)
        page_latest_rows = manager.get_latest_analysis_page(
            search=search,
            limit=page_size,
            offset=(page_pagination["page"] - 1) * page_size,
        )
    else:
        search_lower = search.lower()
        fallback_rows = latest_rows
        if search_lower:
            fallback_rows = [
                item
                for item in latest_rows
                if search_lower
                in " ".join(
                    [
                        _txt(item.get("code") or item.get("symbol")),
                        _txt(item.get("name") or item.get("stock_name")),
                        _txt(item.get("sector") or item.get("industry")),
                        _txt(item.get("rating")),
                    ]
                ).lower()
            ]
        page_pagination = _replay_table_pagination(page, page_size, len(fallback_rows))
        page_latest_rows = fallback_rows[(page_pagination["page"] - 1) * page_size : page_pagination["page"] * page_size]
    summary = context.portfolio().get_account_summary()
    runtime_entries = load_stock_runtime_entries(base_dir=context.selector_result_dir)

    latest_by_symbol: dict[str, dict[str, Any]] = {}

    def enrich_latest_item(item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        code = normalize_stock_code(item.get("code") or item.get("symbol"))
        if not code:
            return "", {}
        runtime = runtime_entries.get(code) if isinstance(runtime_entries, dict) else None
        item_payload = dict(item)
        runtime_name = _txt(runtime.get("stock_name")) if isinstance(runtime, dict) else ""
        runtime_sector = _txt(runtime.get("sector")) if isinstance(runtime, dict) else ""
        runtime_price = _float(runtime.get("latest_price")) if isinstance(runtime, dict) else None
        if runtime_name:
            item_payload["name"] = runtime_name
            item_payload["stock_name"] = runtime_name
        if runtime_sector:
            item_payload["sector"] = runtime_sector
            item_payload["industry"] = runtime_sector
        if runtime_price is not None:
            item_payload["current_price"] = runtime_price

        return code, item_payload

    for item in latest_rows:
        code, item_payload = enrich_latest_item(item)
        if code:
            latest_by_symbol[code] = item_payload

    rows: list[dict[str, Any]] = []
    for item in page_latest_rows:
        code, item_payload = enrich_latest_item(item)
        if not code:
            continue
        name = _txt(item_payload.get("name") or item_payload.get("stock_name"), code)
        sector = _txt(item_payload.get("sector") or item_payload.get("industry") or item_payload.get("board") or item_payload.get("所属行业"), "-")
        quantity = _int(item_payload.get("quantity"), 0) or 0
        cost_price = _float(item_payload.get("cost_price"))
        current_price = _float(item_payload.get("current_price"))
        pnl_pct = None
        if current_price is not None and cost_price not in (None, 0):
            pnl_pct = ((current_price - cost_price) / cost_price) * 100
        confidence = _float(item_payload.get("confidence"))
        score = min(max(confidence * 10.0, 0.0), 100.0) if confidence is not None else None
        rows.append(
            {
                "id": code,
                "cells": [
                    code,
                    name,
                    sector,
                    _txt(quantity),
                    _num(cost_price),
                    _num((item_payload.get("take_profit") if item_payload.get("take_profit") is not None else item_payload.get("analysis_take_profit")), default="--"),
                    _num((item_payload.get("stop_loss") if item_payload.get("stop_loss") is not None else item_payload.get("analysis_stop_loss")), default="--"),
                    _num(current_price),
                    _pct(pnl_pct),
                    _num(score, digits=0, default="--"),
                ],
                "actions": [{"label": "详情", "icon": "🔎", "tone": "accent", "action": "view-detail"}],
                "code": code,
                "name": name,
                "industry": sector,
            }
        )

    selected = normalize_stock_code(selected_symbol)
    if not selected and rows:
        selected = _txt(rows[0].get("code"))
    selected_item = latest_by_symbol.get(selected) if selected else None
    watch_item = _refresh_watchlist_detail_item(context, selected) if selected else None

    technical = {}
    if selected:
        if indicator_overrides and isinstance(indicator_overrides.get(selected), dict):
            technical = indicator_overrides[selected]

    history = None
    if selected_item:
        stock_id = _int(selected_item.get("id"))
        if stock_id is not None:
            history = manager.get_latest_analysis(stock_id)

    selected_item_name = (selected_item or {}).get("name") or (selected_item or {}).get("stock_name")
    selected_item_sector = (
        (selected_item or {}).get("sector")
        or (selected_item or {}).get("industry")
        or (selected_item or {}).get("board")
        or (selected_item or {}).get("所属行业")
    )
    watch_name = (watch_item or {}).get("stock_name")
    watch_sector = _watchlist_sector(watch_item)
    detail_stock_name = _first_stock_info(
        selected_item_name,
        watch_name,
        technical.get("stockName"),
        default=selected,
    )
    detail_sector = _first_stock_info(
        selected_item_sector,
        watch_sector,
        technical.get("sector"),
        default="-",
    )

    detail = {
        "symbol": selected,
        "stockName": detail_stock_name,
        "sector": detail_sector,
        "kline": technical.get("kline") if isinstance(technical.get("kline"), list) else [],
        "indicators": technical.get("indicators") if isinstance(technical.get("indicators"), list) else [],
        "pendingSignals": _table(
            ["时间", "代码", "动作", "策略", "状态", "依据"],
            _portfolio_pending_signal_rows(context, selected) if selected else [],
            "暂无待执行信号",
        ),
        "decision": {
            "rating": _txt(
                (selected_item or {}).get("rating"),
                "持有",
            ),
            "summary": _txt((history or {}).get("summary"), "可点击“实时分析”获取最新结论。"),
            "updatedAt": _txt((selected_item or {}).get("analysis_time"), "--"),
        },
        "marketSnapshot": _market_snapshot_from_watchlist(
            symbol=selected,
            stock_name=detail_stock_name,
            sector=detail_sector,
            watch_item=watch_item,
        ),
        "stockAnalysis": _build_cached_workbench_analysis_payload(
            context,
            code=selected,
            selected=None,
            cycle="1y",
            mode="单个分析",
            allow_backfill=False,
        )
        if selected
        else None,
        "positionForm": {
            "quantity": _txt((selected_item or {}).get("quantity"), "0"),
            "costPrice": _num((selected_item or {}).get("cost_price")),
            "takeProfit": _num((selected_item or {}).get("take_profit") if (selected_item or {}).get("take_profit") is not None else (selected_item or {}).get("analysis_take_profit")),
            "stopLoss": _num((selected_item or {}).get("stop_loss") if (selected_item or {}).get("stop_loss") is not None else (selected_item or {}).get("analysis_stop_loss")),
            "note": _txt((selected_item or {}).get("note")),
        },
    }
    portfolio_decision = _build_portfolio_adjustment_summary(latest_rows if isinstance(latest_rows, list) else [])
    market_news = _load_market_focus_news(context, limit=8)

    return {
        "updatedAt": _now(),
        "metrics": [
            _metric("当前持仓", len(rows)),
            _metric("组合收益", _pct(summary.get("total_return_pct"))),
            _metric("最大回撤", _pct(summary.get("max_drawdown_pct"))),
            _metric("可用现金", _num(summary.get("available_cash"))),
        ],
        "holdings": {
            **_table(["代码", "名称", "板块", "持仓数量", "成本", "止盈价", "止损价", "现价", "浮盈亏", "分数"], rows, "暂无持仓"),
            "pagination": page_pagination,
        },
        "selectedSymbol": selected,
        "detail": detail,
        "attribution": [],
        "curve": detail["kline"],
        "actions": ["实时分析仓位", "刷新技术指标", "更新持仓信息"],
        "portfolioDecision": portfolio_decision,
        "marketNews": market_news,
        "portfolioAnalysisJob": portfolio_rebalance_task_manager.job_view(
            analysis_job or portfolio_rebalance_task_manager.latest_task(),
            txt=_txt,
            int_fn=_int,
        ),
    }
def _action_portfolio_analyze(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    code = _code_from_payload(body)
    manager = context.portfolio_manager()
    if code:
        manager.analyze_single_stock(code)
        return _snapshot_portfolio(context, selected_symbol=code)

    mode = _txt(body.get("mode"), "parallel")
    max_workers = _int(body.get("maxWorkers"), 3) or 3
    period = _txt(body.get("cycle"), "1y")
    task_id = portfolio_rebalance_task_manager.create_task(
        mode=mode,
        cycle=period,
        max_workers=max_workers,
        now=_now,
    )
    portfolio_rebalance_task_manager.start_background(
        task_id=task_id,
        target=portfolio_rebalance_task_manager.run_task,
        kwargs={
            "task_id": task_id,
            "context": context,
            "now": _now,
            "txt": _txt,
        },
        name_prefix="portfolio-rebalance",
    )
    rows = manager.get_all_latest_analysis()
    default_symbol = normalize_stock_code((rows[0].get("code") or rows[0].get("symbol")) if rows else "")
    snapshot = _snapshot_portfolio(
        context,
        selected_symbol=default_symbol,
        analysis_job=portfolio_rebalance_task_manager.get_task(task_id),
    )
    snapshot["taskId"] = task_id
    return snapshot


def _action_portfolio_refresh(context: UIApiContext, payload: Any) -> dict[str, Any]:
    context.portfolio_scheduler().run_analysis_now()
    return _snapshot_portfolio(context)


def _action_portfolio_schedule_save(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    kwargs = {
        "schedule_time": body.get("scheduleTime") if "scheduleTime" in body else body.get("schedule_time"),
        "analysis_mode": body.get("analysisMode") if "analysisMode" in body else body.get("analysis_mode"),
        "max_workers": body.get("maxWorkers") if "maxWorkers" in body else body.get("max_workers"),
        "auto_sync_monitor": body.get("autoSyncMonitor") if "autoSyncMonitor" in body else body.get("auto_sync_monitor"),
        "send_notification": body.get("sendNotification") if "sendNotification" in body else body.get("send_notification"),
    }
    context.portfolio_scheduler().update_config(**{key: value for key, value in kwargs.items() if value is not None})
    return _snapshot_portfolio(context)


def _action_portfolio_schedule_start(context: UIApiContext, payload: Any) -> dict[str, Any]:
    context.portfolio_scheduler().start_scheduler()
    return _snapshot_portfolio(context)


def _action_portfolio_schedule_stop(context: UIApiContext, payload: Any) -> dict[str, Any]:
    context.portfolio_scheduler().stop_scheduler()
    return _snapshot_portfolio(context)


def _action_portfolio_refresh_indicators(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    selected_symbol = normalize_stock_code(body.get("selectedSymbol") or body.get("selected_symbol"))
    symbols = _payload_codes(body)
    if not symbols:
        if selected_symbol:
            symbols = [selected_symbol]
        else:
            symbols = [
                normalize_stock_code(item.get("code") or item.get("symbol"))
                for item in context.portfolio_manager().get_all_latest_analysis()
                if normalize_stock_code(item.get("code") or item.get("symbol"))
            ][:50]
    overrides: dict[str, dict[str, Any]] = {}
    manager = context.portfolio_manager()
    for symbol in symbols:
        overrides[symbol] = _portfolio_technical_snapshot(symbol, cycle=_txt(body.get("cycle"), "1y"), force_refresh=True)
        _persist_watchlist_snapshot_from_technical(context, symbol, overrides[symbol])
        sector = _txt(overrides[symbol].get("sector"))
        if sector:
            existing = manager.db.get_stock_by_code(symbol)
            if existing and _txt(existing.get("sector")) != sector:
                manager.update_stock(_int(existing.get("id"), 0) or 0, sector=sector)
    snapshot = _snapshot_portfolio(
        context,
        selected_symbol=selected_symbol or (symbols[0] if symbols else ""),
        indicator_overrides=overrides,
    )
    snapshot["indicatorRefresh"] = {
        "updatedAt": _now(),
        "scope": "indicators_only",
        "symbols": symbols,
        "watchlistRefresh": None,
    }
    return snapshot


def _action_portfolio_update_position(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    code = normalize_stock_code(_txt(body.get("code") or body.get("symbol")))
    if not code:
        raise HTTPException(status_code=400, detail="Missing portfolio stock code")
    manager = context.portfolio_manager()
    stock = manager.db.get_stock_by_code(code)
    if not stock:
        raise HTTPException(status_code=404, detail=f"Portfolio stock not found: {code}")
    manager.db.update_stock(
        int(stock["id"]),
        cost_price=_float(body.get("costPrice") if "costPrice" in body else body.get("cost_price")),
        quantity=_int(body.get("quantity")),
        take_profit=_float(body.get("takeProfit") if "takeProfit" in body else body.get("take_profit")),
        stop_loss=_float(body.get("stopLoss") if "stopLoss" in body else body.get("stop_loss")),
        note=_txt(body.get("note")) if "note" in body else None,
    )
    return _snapshot_portfolio(context, selected_symbol=code)


def _action_portfolio_delete_position(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    code = normalize_stock_code(_txt(body.get("code") or body.get("symbol") or _code_from_payload(body)))
    if not code:
        raise HTTPException(status_code=400, detail="Missing portfolio stock code")
    manager = context.portfolio_manager()
    stock = manager.db.get_stock_by_code(code)
    if not stock:
        raise HTTPException(status_code=404, detail=f"Portfolio stock not found: {code}")
    ok, message = manager.delete_stock(_int(stock.get("id"), 0) or 0)
    if not ok:
        raise HTTPException(status_code=500, detail=message or f"Failed to delete portfolio stock: {code}")
    return _snapshot_portfolio(context)
