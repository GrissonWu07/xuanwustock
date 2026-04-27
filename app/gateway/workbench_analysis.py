from __future__ import annotations

from app.gateway.deps import *
from app.gateway.context import UIApiContext
from app.gateway.workbench import (
    action_workbench_analysis_batch as _gateway_action_workbench_analysis_batch,
    build_workbench_snapshot as _gateway_build_workbench_snapshot,
    snapshot_workbench as _gateway_snapshot_workbench,
)

_WORKBENCH_DEFAULT_ANALYSTS = ["technical", "fundamental", "fund_flow", "risk"]
_WORKBENCH_MARKDOWN_NOISE = [
    "以下是基于",
    "核心结论先看",
    "我会重点围绕",
    "如果你愿意",
    "先说明",
    "会议纪要",
    "模拟对话",
    "会议主持人",
    "投资决策团队",
]
_WORKBENCH_MODEL_FAILURE_TOKENS = [
    "api调用失败",
    "authentication fails",
    "auth fail",
    "governor",
    "鉴权",
]


def _normalize_workbench_selected(selected: Any) -> list[str]:
    if isinstance(selected, list):
        values = [str(item).strip() for item in selected if str(item).strip()]
        if values:
            return values
    return list(_WORKBENCH_DEFAULT_ANALYSTS)


def _analysis_options(selected: list[str] | None = None) -> list[dict[str, Any]]:
    return _workbench_analysis_options(_normalize_workbench_selected(selected))


def _clean_workbench_text(value: Any, *, limit: int = 0) -> str:
    text = _txt(value)
    if not text:
        return ""
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = text.replace("***", " ").replace("**", " ").replace("__", " ").replace("`", " ")
    text = text.replace("---", " ").replace("|", " ")
    for noise in _WORKBENCH_MARKDOWN_NOISE:
        text = text.replace(noise, " ")
    text = re.sub(r"\s+", " ", text).strip()
    if limit > 0 and len(text) > limit:
        text = f"{text[:limit].rstrip()}…"
    return text


def _contains_workbench_model_failure(*values: Any) -> bool:
    merged = " ".join(_txt(item).lower() for item in values if _txt(item))
    if not merged:
        return False
    return any(token in merged for token in _WORKBENCH_MODEL_FAILURE_TOKENS)


def _record_is_more_complete(record: dict[str, Any]) -> tuple[int, int]:
    indicators = record.get("indicators") if isinstance(record.get("indicators"), dict) else {}
    historical = record.get("historical_data") if isinstance(record.get("historical_data"), list) else []
    agents = record.get("agents_results") if isinstance(record.get("agents_results"), dict) else {}
    final_decision = record.get("final_decision") if isinstance(record.get("final_decision"), dict) else {}
    score = 0
    if indicators:
        score += 4
    if historical:
        score += 4
    score += min(len(agents), 4)
    if _txt(final_decision.get("operation_advice") or final_decision.get("decision_text") or final_decision.get("rating")):
        score += 2
    return score, _int(record.get("id"), 0) or 0


def _pick_best_cached_record(context: UIApiContext, symbol: str) -> dict[str, Any] | None:
    records = context.stock_analysis_db().get_recent_records_by_symbol(symbol, limit=10)
    if not records:
        return None
    ranked = sorted(records, key=_record_is_more_complete, reverse=True)
    return ranked[0] if ranked else None


def _history_points_from_dataframe(stock_data: Any) -> list[dict[str, Any]]:
    if stock_data is None or not hasattr(stock_data, "iterrows"):
        return []
    points: list[dict[str, Any]] = []
    try:
        for index, row in stock_data.tail(180).iterrows():
            close_value = row.get("Close") if hasattr(row, "get") else None
            if close_value in (None, "") and hasattr(row, "get"):
                close_value = row.get("收盘")
            if close_value in (None, ""):
                continue
            label = _txt(index)
            if hasattr(index, "strftime"):
                try:
                    label = index.strftime("%Y-%m-%d")
                except Exception:
                    label = _txt(index)
            points.append({"date": label, "close": float(close_value)})
    except Exception:
        return []
    return points


def _normalize_workbench_payload(
    *,
    payload: dict[str, Any],
    indicators: dict[str, Any],
    discussion_result: Any,
    final_decision: dict[str, Any],
    agents_results: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(payload)
    indicator_explanations = stock_analysis_service.build_indicator_explanations(
        indicators if isinstance(indicators, dict) else {},
        current_price=None,
    )
    indicator_summary = _txt(
        stock_analysis_service.build_indicator_summary(indicator_explanations),
        "关键指标显示当前趋势信号仍在，建议结合仓位控制继续跟踪。",
    )
    discussion_summary = _txt(discussion_result.get("summary")) if isinstance(discussion_result, dict) else ""
    summary_text = _clean_workbench_text(discussion_summary or _txt(discussion_result), limit=110)
    if not summary_text:
        summary_text = _clean_workbench_text(indicator_summary, limit=110)

    analyst_views: list[dict[str, Any]] = []
    analyst_names: list[str] = []
    model_failure = _contains_workbench_model_failure(summary_text, _txt(final_decision), _txt(discussion_result))
    for _, agent_result in (agents_results or {}).items():
        if not isinstance(agent_result, dict):
            continue
        agent_name = _txt(agent_result.get("agent_name"), "分析师")
        analyst_names.append(agent_name)
        body = _clean_workbench_text(
            _txt(agent_result.get("summary") or agent_result.get("analysis") or agent_result.get("decision_text") or agent_result.get("result")),
            limit=170,
        )
        if _contains_workbench_model_failure(body):
            model_failure = True
        if not body:
            continue
        analyst_views.append({"title": agent_name, "body": body})

    rating = _txt(_first_non_empty(final_decision, ["rating", "decision", "verdict"]))
    position_size = _txt(final_decision.get("position_size"))
    target_price = _txt(final_decision.get("target_price"))
    operation_advice = _clean_workbench_text(
        _txt(final_decision.get("operation_advice") or final_decision.get("decision_text") or final_decision.get("reasoning")),
        limit=170,
    )

    decision_parts: list[str] = []
    if rating:
        decision_parts.append(f"当前评级：{rating}")
    if position_size:
        decision_parts.append(f"建议仓位：{position_size}")
    if target_price:
        decision_parts.append(f"目标价：{target_price}")
    decision_text = "；".join(decision_parts)
    if operation_advice:
        decision_text = f"{decision_text}。{operation_advice}" if decision_text else operation_advice
    if not decision_text and analyst_views:
        view_hint = "；".join(item.get("body", "") for item in analyst_views[:2] if _txt(item.get("body")))
        decision_text = _clean_workbench_text(view_hint, limit=170)
    if not decision_text:
        decision_text = summary_text or _clean_workbench_text(indicator_summary, limit=170)
    if decision_text and ("建议" not in decision_text and "更适合" not in decision_text):
        decision_text = f"建议继续观察，{decision_text}"
    if not decision_text:
        decision_text = "综合决策暂不可用，请先查看分析师观点与关键指标。"

    insights: list[dict[str, Any]] = []
    risk_warning = _clean_workbench_text(_txt(final_decision.get("risk_warning")), limit=120)
    if model_failure:
        model_state = "模型调用暂不可用（疑似鉴权或额度异常），已自动降级为指标与历史结论。"
        analyst_hint = "、".join(analyst_names) if analyst_names else "当前分析师"
        normalized["summaryBody"] = _clean_workbench_text(indicator_summary, limit=110)
        normalized["decision"] = _clean_workbench_text(indicator_summary, limit=170) or "综合决策暂不可用，请先查看关键指标。"
        normalized["finalDecisionText"] = normalized["decision"]
        normalized["analystViews"] = []
        insights.append(_insight("模型状态", model_state, "warning"))
        insights.append(_insight("分析师观点", f"{analyst_hint}观点暂不可用，建议稍后重试。", "neutral"))
        insights.append(_insight("操作建议", normalized["decision"], "accent"))
    else:
        merged_summary = summary_text
        if decision_text and _clean_workbench_text(decision_text, limit=80) not in merged_summary:
            merged_summary = _clean_workbench_text(f"{decision_text} {summary_text}", limit=110)
        normalized["summaryBody"] = merged_summary
        normalized["decision"] = _clean_workbench_text(decision_text, limit=170)
        normalized["finalDecisionText"] = normalized["decision"]
        normalized["analystViews"] = analyst_views
        insights.append(_insight("操作建议", normalized["decision"], "accent"))
        if risk_warning:
            insights.append(_insight("风险提示", risk_warning, "warning"))
    normalized["insights"] = insights
    return normalized


def _run_single_workbench_analysis(
    context: UIApiContext,
    job_id: str,
    *,
    code: str,
    selected: list[str] | None,
    cycle: str,
    mode: str,
) -> dict[str, Any]:
    symbol = normalize_stock_code(code)
    if not symbol:
        raise HTTPException(status_code=400, detail="Missing stock code")

    selected_values = _normalize_workbench_selected(selected)
    analyze_config = _workbench_analysis_config(selected_values)
    try:
        try:
            result = stock_analysis_service.analyze_single_stock_for_batch(
                symbol,
                cycle,
                enabled_analysts_config=analyze_config,
                selected_model=None,
                progress_callback=None,
                analysis_db=context.stock_analysis_db(),
            )
        except TypeError as exc:
            if "analysis_db" not in str(exc):
                raise
            result = stock_analysis_service.analyze_single_stock_for_batch(
                symbol,
                cycle,
                enabled_analysts_config=analyze_config,
                selected_model=None,
                progress_callback=None,
            )
    except Exception as exc:
        result = {"success": False, "error": str(exc), "symbol": symbol}

    if not isinstance(result, dict) or not result.get("success"):
        hydrated_name = _hydrate_cached_workbench_analysis(
            context,
            code=symbol,
            selected=selected_values,
            cycle=cycle,
            mode=mode,
        )
        if not hydrated_name:
            fallback = {
                "symbol": symbol,
                "stockName": symbol,
                "analysts": _analysis_options(selected_values),
                "mode": mode,
                "cycle": cycle,
                "inputHint": "例如 600519 / 300390 / AAPL",
                "summaryTitle": f"{symbol} 分析摘要",
                "summaryBody": "分析未返回有效结果，请稍后重试。",
                "generatedAt": _now(),
                "indicators": [],
                "decision": "综合决策暂不可用，请先查看关键指标与分析师观点。",
                "finalDecisionText": "综合决策暂不可用，请先查看关键指标与分析师观点。",
                "insights": [
                    _insight("模型状态", "模型调用暂不可用（疑似鉴权或额度异常），请检查配置后重试。", "warning"),
                ],
                "analystViews": [],
                "curve": [],
            }
            context.set_workbench_analysis(fallback)
        failure_message = _txt(result.get("error"), "分析失败")
        if hydrated_name:
            failure_message = f"{failure_message}；已保留上一次成功分析。"
        context.set_workbench_analysis_job(
            {
                "id": job_id,
                "status": "failed",
                "title": "刷新失败（已回退到最近有效结果）",
                "message": failure_message,
                "stage": "failed",
                "progress": 100,
                "symbol": symbol,
                "startedAt": _now(),
                "updatedAt": _now(),
            }
        )
        return context.get_workbench_analysis() or {}

    stock_info = result.get("stock_info") if isinstance(result.get("stock_info"), dict) else {}
    stock_name = _txt(stock_info.get("name"), symbol)
    indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
    discussion_result = result.get("discussion_result")
    final_decision = result.get("final_decision") if isinstance(result.get("final_decision"), dict) else {}
    agents_results = result.get("agents_results") if isinstance(result.get("agents_results"), dict) else {}
    historical_data = result.get("historical_data") if isinstance(result.get("historical_data"), list) else []

    payload = _build_workbench_analysis_payload(
        code=symbol,
        stock_name=stock_name,
        selected=selected_values,
        mode=mode,
        cycle=cycle,
        generated_at=_txt(result.get("generated_at"), _now()),
        stock_info=stock_info,
        indicators=indicators,
        discussion_result=discussion_result,
        final_decision=final_decision,
        agents_results=agents_results,
        historical_data=historical_data,
    )
    payload = _normalize_workbench_payload(
        payload=payload,
        indicators=indicators,
        discussion_result=discussion_result,
        final_decision=final_decision,
        agents_results=agents_results,
    )
    context.set_workbench_analysis(payload)
    context.set_workbench_analysis_job(
        {
            "id": job_id,
            "status": "completed",
            "title": "分析已完成",
            "message": f"{symbol} 分析完成",
            "stage": "completed",
            "progress": 100,
            "symbol": symbol,
            "startedAt": _now(),
            "updatedAt": _now(),
        }
    )
    return payload


def _build_cached_workbench_analysis_payload(
    context: UIApiContext,
    *,
    code: str,
    selected: list[str] | None,
    cycle: str,
    mode: str,
    allow_backfill: bool = True,
) -> dict[str, Any] | None:
    symbol = normalize_stock_code(code)
    if not symbol:
        return None
    record = _pick_best_cached_record(context, symbol)
    if not record:
        return None
    stock_info = record.get("stock_info") if isinstance(record.get("stock_info"), dict) else {}
    indicators = record.get("indicators") if isinstance(record.get("indicators"), dict) else {}
    historical_data = record.get("historical_data") if isinstance(record.get("historical_data"), list) else []
    if allow_backfill and (not indicators or not historical_data):
        try:
            rt_stock_info, rt_data, rt_indicators = stock_analysis_service.get_stock_data(symbol, cycle)
            if isinstance(rt_stock_info, dict):
                stock_info = rt_stock_info
            if isinstance(rt_indicators, dict) and rt_indicators:
                indicators = rt_indicators
            if not historical_data:
                historical_data = _history_points_from_dataframe(rt_data)
        except Exception:
            pass
    stock_name = _txt(record.get("stock_name"), _txt(stock_info.get("name"), symbol))
    payload = _build_workbench_analysis_payload(
        code=symbol,
        stock_name=stock_name,
        selected=_normalize_workbench_selected(selected),
        mode=mode,
        cycle=cycle,
        generated_at=_txt(record.get("analysis_date") or record.get("created_at"), _now()),
        stock_info=stock_info,
        indicators=indicators,
        discussion_result=record.get("discussion_result"),
        final_decision=record.get("final_decision") if isinstance(record.get("final_decision"), dict) else {},
        agents_results=record.get("agents_results") if isinstance(record.get("agents_results"), dict) else {},
        historical_data=historical_data,
    )
    payload["summaryBody"] = payload.get("summaryBody", "").replace("最近一次有效分析时间", "").strip()
    return payload


def _hydrate_cached_workbench_analysis(
    context: UIApiContext,
    *,
    code: str,
    selected: list[str] | None,
    cycle: str,
    mode: str,
) -> str:
    payload = _build_cached_workbench_analysis_payload(
        context,
        code=code,
        selected=selected,
        cycle=cycle,
        mode=mode,
        allow_backfill=True,
    )
    if not payload:
        return ""
    context.set_workbench_analysis(payload)
    return _txt(payload.get("stockName"), normalize_stock_code(code))


def _workbench_analysis_needs_refresh(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    summary_body = _txt(payload.get("summaryBody"))
    if "最近一次有效分析时间" in summary_body:
        return True
    indicators = payload.get("indicators") if isinstance(payload.get("indicators"), list) else []
    if any(_txt(item.get("value")) in {"暂无数据", "暂无判断"} for item in indicators if isinstance(item, dict)):
        return True
    curve = payload.get("curve") if isinstance(payload.get("curve"), list) else []
    return len(curve) == 0


def _snapshot_workbench(context: UIApiContext, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    analysis = context.get_workbench_analysis()
    analysis_job = context.get_workbench_analysis_job()
    if analysis and _workbench_analysis_needs_refresh(analysis):
        _hydrate_cached_workbench_analysis(
            context,
            code=_txt(analysis.get("symbol")),
            selected=[item.get("value") for item in analysis.get("analysts", []) if isinstance(item, dict) and item.get("selected")] if isinstance(analysis.get("analysts"), list) else None,
            cycle=_txt(analysis.get("cycle"), "1y"),
            mode=_txt(analysis.get("mode"), "单个分析"),
        )
        analysis = context.get_workbench_analysis()
    if isinstance(analysis_job, dict) and _txt(analysis_job.get("status")) in {"running", "queued"} and isinstance(analysis, dict):
        normalized_job = {
            **analysis_job,
            "status": "completed",
            "title": "分析已完成",
            "message": _txt(analysis_job.get("message"), "分析结果已可查看"),
            "stage": "completed",
            "progress": 100,
            "updatedAt": _now(),
        }
        context.set_workbench_analysis_job(normalized_job)
        analysis_job = normalized_job
    if isinstance(analysis, dict) or isinstance(analysis_job, dict):
        return _gateway_build_workbench_snapshot(context, analysis=analysis, analysis_job=analysis_job, table_query=table_query)
    return _gateway_snapshot_workbench(context, table_query=table_query)


def action_workbench_analysis_batch_compat(context: UIApiContext, payload: Any) -> dict[str, Any]:
    snapshot = _gateway_action_workbench_analysis_batch(context, payload)
    body = _payload_dict(payload)
    raw_codes = body.get("stockCodes") if isinstance(body, dict) else None
    codes = [normalize_stock_code(item) for item in (raw_codes or []) if normalize_stock_code(item)]
    count = len(codes)
    if isinstance(snapshot.get("analysis"), dict):
        analysis = dict(snapshot["analysis"])
        mode = _txt(body.get("mode"), "批量分析")
        if count > 0:
            analysis["mode"] = mode
            analysis["summaryTitle"] = f"{mode}任务已提交"
            analysis["summaryBody"] = f"已提交 {count} 只股票进入批量分析队列，结果会按股票逐条更新。"
        snapshot["analysis"] = analysis
    return snapshot
