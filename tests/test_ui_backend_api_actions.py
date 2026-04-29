from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

import pytest
import pandas as pd
from fastapi.testclient import TestClient

import app.gateway_api as gateway_api
from app.gateway_api import UIApiContext, create_app
from app.selector_result_store import save_latest_result


def _make_context(tmp_path: Path) -> UIApiContext:
    selector_dir = tmp_path / "selector_results"
    selector_dir.mkdir(parents=True, exist_ok=True)
    return UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=selector_dir,
        watchlist_db_file=tmp_path / "watchlist.db",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        portfolio_db_file=tmp_path / "portfolio.db",
        monitor_db_file=tmp_path / "monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
        stock_analysis_db_file=tmp_path / "analysis.db",
        main_force_batch_db_file=tmp_path / "main_force_batch.db",
        stock_name_resolver=lambda code: {"600519": "贵州茅台", "000001": "平安银行", "300750": "宁德时代"}.get(code, code),
        quote_fetcher=lambda code, market=None: {
            "stock_code": code,
            "stock_name": {"600519": "贵州茅台", "000001": "平安银行", "300750": "宁德时代"}.get(code, code),
            "latest_price": {"600519": 1453.96, "000001": 10.12, "300750": 198.35}.get(code, 1.0),
        },
    )


def _seed_discover_result(base_dir: Path) -> None:
    save_latest_result(
        "main_force",
        {
            "result": {
                "success": True,
                "final_recommendations": [
                    {
                        "symbol": "600519.SH",
                        "name": "贵州茅台",
                        "highlights": "主力资金流入",
                        "stock_data": {
                            "股票代码": "600519",
                            "股票简称": "贵州茅台",
                            "最新价": "1453.96",
                            "所属同花顺行业": "食品饮料-白酒",
                            "总市值[20260410]": 18200.0,
                            "市盈率(pe)[20260410]": 26.1,
                            "市净率(pb)[20260410]": 9.8,
                        },
                    }
                ],
            },
            "selected_at": "2026-04-13 12:00:00",
        },
        base_dir=base_dir,
    )


def _seed_simple_selector_result(base_dir: Path, strategy_key: str, rows: list[dict[str, object]], selected_at: str) -> None:
    save_latest_result(
        strategy_key,
        {
            "stocks_df": pd.DataFrame(rows),
            "selected_at": selected_at,
        },
        base_dir=base_dir,
    )


class FakeQuantScheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.running = False
        self.status = {
            "running": False,
            "enabled": False,
            "auto_execute": True,
            "interval_minutes": 15,
            "trading_hours_only": True,
            "analysis_timeframe": "30m",
            "strategy_mode": "auto",
            "start_date": "2026-04-01",
            "market": "CN",
            "last_run_at": "2026-04-13 12:00:00",
            "next_run": None,
        }

    def update_config(self, **kwargs):
        self.calls.append(("update_config", kwargs))
        self.status.update(kwargs)
        if "enabled" in kwargs:
            self.status["enabled"] = kwargs["enabled"]

    def get_status(self):
        return dict(self.status, running=self.running)

    def start(self):
        self.calls.append(("start", None))
        self.running = True
        self.status["enabled"] = True
        self.status["next_run"] = "2026-04-13 12:05:00"
        return True

    def stop(self):
        self.calls.append(("stop", None))
        self.running = False
        self.status["enabled"] = False
        self.status["next_run"] = None
        return True

    def run_once(self, run_reason="ui_manual_run"):
        self.calls.append(("run_once", run_reason))
        self.status["last_run_at"] = "2026-04-13 12:03:00"
        return {"candidates_scanned": 2, "signals_created": 1, "positions_checked": 0, "auto_executed": 0, "snapshot_id": 1}


class FakeReplayService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def enqueue_historical_range(self, **kwargs):
        self.calls.append(("historical", kwargs))
        return 101

    def enqueue_past_to_live(self, **kwargs):
        self.calls.append(("past_to_live", kwargs))
        return 102


class FakePortfolioScheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def get_status(self):
        return {"running": True, "schedule_times": ["09:30"], "analysis_mode": "sequential"}

    def update_config(self, **kwargs):
        self.calls.append(("update", kwargs))

    def start_scheduler(self):
        self.calls.append(("start", None))
        return True

    def stop_scheduler(self):
        self.calls.append(("stop", None))
        return True

    def run_analysis_now(self):
        self.calls.append(("run_now", None))
        return True


class FakePortfolioManager:
    def __init__(self) -> None:
        self.analyzed: list[str] = []

    def analyze_single_stock(self, stock_code: str, period="1y", selected_agents=None):
        self.analyzed.append(stock_code)
        return {"success": True, "stock_code": stock_code}

    def get_all_latest_analysis(self):
        return [
            {
                "code": "600519",
                "name": "贵州茅台",
                "quantity": 100,
                "rating": "继续持有",
                "current_price": 1453.96,
                "target_price": 1600.0,
            }
        ]


class FakeSmartMonitorEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def start_monitor(self, stock_code: str, **kwargs):
        self.calls.append(("start", stock_code))

    def stop_monitor(self, stock_code: str):
        self.calls.append(("stop", stock_code))

    def analyze_stock(self, stock_code: str, **kwargs):
        self.calls.append(("analyze", stock_code))
        return {"success": True}


class FakeRealMonitorScheduler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start_scheduler(self):
        self.calls.append("start")

    def stop_scheduler(self):
        self.calls.append("stop")

    def get_status(self):
        return {"scheduler_running": bool(self.calls and self.calls[-1] == "start"), "scheduler_enabled": True}


def test_workbench_analysis_actions_return_real_analysis(tmp_path, monkeypatch):
    import app.stock_analysis_service as app_module

    context = _make_context(tmp_path)
    context.watchlist().add_manual_stock("600519")

    monkeypatch.setattr(
        app_module,
        "analyze_single_stock_for_batch",
        lambda symbol, period, enabled_analysts_config=None, selected_model=None, progress_callback=None: {
            "success": True,
            "symbol": symbol,
            "stock_info": {"name": "贵州茅台", "current_price": 1453.96},
            "indicators": {"RSI": 53.79, "MA20": 1441.86, "量比": 1.13, "MACD": 6.2792},
            "final_decision": {"decision_text": "偏多看待，等待回踩再介入"},
                "discussion_result": "多位分析师认为趋势与资金面偏强，但不建议追高。",
                "agents_results": {
                    "technical": {"agent_name": "技术分析师", "summary": "趋势向上，均线多头。"},
                    "fundamental": {"agent_name": "基本面分析师", "summary": "基本面稳定，估值仍可接受。"},
                },
            "historical_data": [
                {"date": "2026-04-11", "close": 1430.0},
                {"date": "2026-04-12", "close": 1453.96},
            ],
        },
    )
    monkeypatch.setattr(
        app_module,
        "build_indicator_explanations",
        lambda indicators, current_price=None: [
            {"label": "RSI", "value": "53.79"},
            {"label": "MA20", "value": "1441.86"},
            {"label": "量比", "value": "1.13"},
            {"label": "MACD", "value": "6.2792"},
        ],
    )
    monkeypatch.setattr(app_module, "build_indicator_summary", lambda explanations: "技术面偏强，但不宜追高。")

    gateway_api._run_single_workbench_analysis(
        context,
        "job-1",
        code="600519",
        selected=["technical", "fundamental"],
        cycle="1y",
        mode="单个分析",
    )
    analysis = context.get_workbench_analysis()
    assert analysis["symbol"] == "600519"
    assert "贵州茅台" in analysis["summaryTitle"]
    assert "偏多看待" in analysis["summaryBody"]
    assert analysis["indicators"]
    assert "偏多" in analysis["decision"]
    assert analysis["finalDecisionText"] == analysis["decision"]
    assert any(item["title"] == "技术分析师" for item in analysis["analystViews"])
    assert any(item["title"] == "基本面分析师" for item in analysis["analystViews"])
    insight_titles = {item["title"] for item in analysis["insights"]}
    assert "操作建议" in insight_titles
    assert "technical" not in insight_titles
    assert "fundamental" not in insight_titles

    gateway_api._run_single_workbench_analysis(
        context,
        "job-2",
        code="600519",
        selected=[],
        cycle="1y",
        mode="单个分析",
    )
    fallback_analysis = context.get_workbench_analysis()
    fallback_selected = [item["value"] for item in fallback_analysis["analysts"] if item.get("selected")]
    assert fallback_selected == ["technical", "fundamental", "fund_flow", "risk"]

    client = TestClient(create_app(context=context))
    batch = client.post(
        "/api/v1/workbench/actions/analysis-batch",
        json={"stockCodes": ["600519", "600519"], "analysts": ["technical"], "cycle": "1y", "mode": "批量分析"},
    )
    assert batch.status_code == 200
    batch_analysis = batch.json()["analysis"]
    assert batch_analysis["mode"] == "批量分析"
    assert "批量" in batch_analysis["summaryTitle"]
    assert "2" in batch_analysis["summaryBody"] or "两" in batch_analysis["summaryBody"]


def test_workbench_analysis_masks_provider_failure_with_readable_fallback(tmp_path, monkeypatch):
    import app.stock_analysis_service as app_module

    context = _make_context(tmp_path)

    monkeypatch.setattr(
        app_module,
        "analyze_single_stock_for_batch",
        lambda symbol, period, enabled_analysts_config=None, selected_model=None, progress_callback=None: {
            "success": True,
            "symbol": symbol,
            "stock_info": {"name": "沪电股份", "current_price": 89.99},
            "indicators": {"RSI": 71.32, "MA20": 82.99, "量比": 1.22, "MACD": 2.118},
            "final_decision": {"decision_text": "API调用失败: Authentication Fails (governor)"},
            "discussion_result": "API调用失败: Authentication Fails (governor)",
            "agents_results": {
                "technical": {"agent_name": "技术分析师", "analysis": "API调用失败: Authentication Fails (governor)"},
            },
            "historical_data": [
                {"date": "2026-04-11", "close": 87.5},
                {"date": "2026-04-12", "close": 89.99},
            ],
        },
    )
    monkeypatch.setattr(
        app_module,
        "build_indicator_explanations",
        lambda indicators, current_price=None: [
            {"label": "RSI", "value": "71.32"},
            {"label": "MA20", "value": "82.99"},
        ],
    )
    monkeypatch.setattr(app_module, "build_indicator_summary", lambda explanations: "关键指标显示短线偏强，但需要警惕追高风险。")

    gateway_api._run_single_workbench_analysis(
        context,
        "job-1",
        code="002463",
        selected=[],
        cycle="1y",
        mode="单个分析",
    )
    analysis = context.get_workbench_analysis()
    assert "Authentication Fails" not in analysis["decision"]
    assert "API调用失败" not in analysis["decision"]
    assert "Authentication Fails" not in analysis["summaryBody"]
    assert any(item["title"] == "模型状态" for item in analysis["insights"])
    assert any("关键指标" in item["body"] for item in analysis["insights"])
    assert "团队观点" not in analysis["decision"]
    assert analysis["finalDecisionText"] == analysis["decision"]
    analyst_insight = next((item for item in analysis["insights"] if item["title"] == "分析师观点"), None)
    assert analyst_insight is not None
    assert "暂不可用" in analyst_insight["body"]
    assert "技术分析师" in analyst_insight["body"]
    assert analysis["analystViews"] == []
    model_state = next((item for item in analysis["insights"] if item["title"] == "模型状态"), None)
    assert model_state is not None
    assert "鉴权" in model_state["body"]


def test_workbench_analysis_action_returns_job_immediately_and_completes_in_background(tmp_path, monkeypatch):
    import app.stock_analysis_service as app_module

    context = _make_context(tmp_path)
    context.watchlist().add_manual_stock("002463")
    started = threading.Event()
    release = threading.Event()

    def fake_analyze(symbol, period, enabled_analysts_config=None, selected_model=None, progress_callback=None):
        started.set()
        if progress_callback:
            progress_callback("fetch", "正在获取行情与财务数据")
        release.wait(timeout=5)
        if progress_callback:
            progress_callback("decision", "正在生成最终决策")
        return {
            "success": True,
            "symbol": symbol,
            "stock_info": {"name": "沪电股份", "current_price": 89.99},
            "indicators": {"RSI": 71.32, "MA20": 82.99, "量比": 1.22, "MACD": 2.118},
            "final_decision": {"decision_text": "建议继续观察，等待更舒适的参与位置。", "reasoning": "趋势仍在，但更适合等待回踩。"},
            "discussion_result": {"summary": "团队判断趋势仍在，但不建议追高。"},
            "agents_results": {
                "technical": {"agent_name": "技术分析师", "summary": "趋势向上，但不适合追高。"},
            },
            "historical_data": [
                {"date": "2026-04-11", "close": 87.5},
                {"date": "2026-04-12", "close": 89.99},
            ],
        }

    monkeypatch.setattr(app_module, "analyze_single_stock_for_batch", fake_analyze)
    monkeypatch.setattr(app_module, "build_indicator_explanations", lambda indicators, current_price=None: [{"label": "RSI", "value": "71.32"}])
    monkeypatch.setattr(app_module, "build_indicator_summary", lambda explanations: "关键指标显示趋势仍在，但不适合追高。")

    client = TestClient(create_app(context=context))

    start = time.monotonic()
    response = client.post("/api/v1/workbench/actions/analysis", json={"stockCode": "002463"})
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    snapshot = response.json()
    assert elapsed < 1.0
    assert snapshot["analysisJob"]["status"] in {"queued", "running"}
    assert snapshot["analysisJob"]["stage"] in {"queued", "fetch"}
    assert snapshot["analysisJob"]["symbol"] == "002463"
    assert started.wait(timeout=1)

    running = client.get("/api/v1/workbench")
    assert running.status_code == 200
    assert running.json()["analysisJob"]["status"] in {"queued", "running"}
    assert running.json()["analysisJob"]["stage"] in {"fetch", "decision", "running", "queued"}

    release.set()
    completed_snapshot = None
    deadline = time.time() + 5
    while time.time() < deadline:
        current = client.get("/api/v1/workbench")
        assert current.status_code == 200
        payload = current.json()
        if payload.get("analysisJob", {}).get("status") == "completed":
            completed_snapshot = payload
            break
        time.sleep(0.05)

    assert completed_snapshot is not None
    assert completed_snapshot["analysis"]["symbol"] == "002463"
    assert "沪电股份" in completed_snapshot["analysis"]["summaryTitle"]
    assert completed_snapshot["analysisJob"]["stage"] == "completed"
    assert completed_snapshot["analysisJob"]["progress"] == 100


def test_workbench_watchlist_page_size_is_capped_at_twenty(tmp_path):
    context = _make_context(tmp_path)
    for index in range(25):
        context.watchlist().add_manual_stock(f"60{index:04d}")

    client = TestClient(create_app(context=context))
    response = client.get("/api/v1/workbench?pageSize=50&page=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["watchlist"]["pagination"]["pageSize"] == 20
    assert payload["watchlist"]["pagination"]["totalRows"] == 25
    assert payload["watchlist"]["pagination"]["totalPages"] == 2
    assert len(payload["watchlist"]["rows"]) == 20


def test_workbench_watchlist_uses_decision_table_columns(tmp_path):
    context = _make_context(tmp_path)
    context.watchlist().add_stock(
        stock_code="600519",
        stock_name="贵州茅台",
        source="main_force",
        latest_price=1453.96,
        notes="主力资金流入",
        metadata={"industry": "白酒", "change_pct": 1.23},
    )
    context.watchlist().mark_in_quant_pool("600519", True)
    context.watchlist().update_watch_snapshot("600519", latest_signal="BUY")
    context.stock_analysis_db().save_analysis(
        "600519",
        "贵州茅台",
        "1y",
        stock_info={},
        agents_results={},
        discussion_result={},
        final_decision={"rating": "买入"},
        indicators={},
        historical_data=[],
    )

    client = TestClient(create_app(context=context))
    response = client.get("/api/v1/workbench")

    assert response.status_code == 200
    payload = response.json()
    assert payload["watchlist"]["columns"] == ["代码", "名称", "行情", "板块", "分析", "信号", "工作流", "更新"]
    row = payload["watchlist"]["rows"][0]
    assert row["cells"][2] == "1453.96 +1.23%"
    assert "今日已分析" in row["cells"][4]
    assert "买入" in row["cells"][4]
    assert row["cells"][5] == "BUY"
    assert "量化池" in row["cells"][6]
    assert row["analysisStatus"] == row["cells"][4]
    assert row["signalStatus"] == "BUY"
    assert "量化池" in row["workflowBadges"]
    assert row["actions"] == []


def test_workbench_delete_accepts_batch_codes(tmp_path):
    context = _make_context(tmp_path)
    context.watchlist().add_manual_stock("600519")
    context.watchlist().add_manual_stock("000001")
    context.watchlist().add_manual_stock("300750")

    client = TestClient(create_app(context=context))
    response = client.post("/api/v1/workbench/actions/delete-watchlist", json={"codes": ["600519", "000001"]})

    assert response.status_code == 200
    remaining = {row["id"] for row in response.json()["watchlist"]["rows"]}
    assert "600519" not in remaining
    assert "000001" not in remaining
    assert "300750" in remaining


def test_workbench_batch_analysis_snapshot_keeps_pending_symbols_visible(tmp_path):
    from app.gateway_workbench import build_workbench_snapshot

    context = _make_context(tmp_path)
    context.watchlist().add_manual_stock("600519")
    context.watchlist().add_manual_stock("000001")
    finished_result = {
        "symbol": "600519",
        "stockName": "贵州茅台",
        "analysts": [],
        "mode": "批量分析",
        "cycle": "1y",
        "inputHint": "600519",
        "summaryTitle": "贵州茅台分析完成",
        "summaryBody": "第一只股票已经完成。",
        "generatedAt": "2026-04-25 10:00:00",
        "indicators": [],
        "decision": "持有",
        "insights": [],
        "curve": [],
    }
    snapshot = build_workbench_snapshot(
        context,
        analysis_job={
            "id": "analysis-test",
            "status": "running",
            "title": "股票分析任务",
            "message": "正在分析 000001",
            "stage": "fetch",
            "progress": 50,
            "symbol": "000001",
            "codes": ["600519", "000001"],
            "selected": ["technical"],
            "cycle": "1y",
            "mode": "批量分析",
            "results": [finished_result],
            "errors": [],
        },
    )

    symbols = [item["symbol"] for item in snapshot["analysis"]["results"]]
    assert symbols == ["600519", "000001"]
    pending = snapshot["analysis"]["results"][1]
    assert pending["stockName"] == "000001"
    assert "分析" in pending["summaryTitle"]
    assert "排队" in pending["summaryBody"] or "等待" in pending["summaryBody"]


def test_workbench_analysis_condenses_raw_markdown_into_readable_summaries(tmp_path, monkeypatch):
    import app.stock_analysis_service as app_module

    context = _make_context(tmp_path)

    monkeypatch.setattr(
        app_module,
        "analyze_single_stock_for_batch",
        lambda symbol, period, enabled_analysts_config=None, selected_model=None, progress_callback=None: {
            "success": True,
            "symbol": symbol,
            "stock_info": {"name": "沪电股份", "current_price": 89.99},
            "indicators": {"RSI": 71.32, "MA20": 82.99, "量比": 1.22, "MACD": 2.118},
            "final_decision": {"decision_text": "建议继续观察，等待更舒适的参与位置。"},
            "discussion_result": (
                "***投资决策团队会议纪要（模拟对话）***\n"
                "### 会议主持人\n"
                "今天围绕 002463 做综合讨论。技术面偏强，但短线略热；资金面显示主力仍在，但也存在高位换手。"
                "综合来看，不建议追高，更适合等待回踩确认。"
            ),
            "agents_results": {
                "fundamental": {
                    "agent_name": "基本面分析师",
                    "analysis": (
                        "### 基本面分析师\n"
                        "**公司很好，但价格未必便宜。** 从近 8 期财务数据看，收入和利润持续上行，研发投入持续提升，"
                        "财务结构健康，ROE 和 ROA 也处于较好水平。问题在于，市场已经提前交易高增长预期，"
                        "因此更适合把它理解为好公司，而不是低位捡漏标的。"
                    ),
                },
                "fund_flow": {
                    "agent_name": "资金面分析师",
                    "analysis": (
                        "### 资金面分析师\n"
                        "**主力资金仍在推动，但过程并不舒服。** 近期净流入并非持续匀速，而是大额流入与明显流出交替出现，"
                        "说明高位分歧较大。若后续继续放量创新高但主力净流出增加，就要提高警惕。"
                    ),
                },
                "risk": {
                    "agent_name": "风险管理师",
                    "analysis": (
                        "如果你愿意，我可以进一步把仓位、止损和分批止盈计划拆给你。"
                        " 当前核心风险不是公司本身，而是位置偏热、追高容易被动。"
                    ),
                },
            },
            "historical_data": [
                {"date": "2026-04-11", "close": 87.5},
                {"date": "2026-04-12", "close": 89.99},
            ],
        },
    )
    monkeypatch.setattr(
        app_module,
        "build_indicator_explanations",
        lambda indicators, current_price=None: [
            {"label": "RSI", "value": "71.32"},
            {"label": "MA20", "value": "82.99"},
        ],
    )
    monkeypatch.setattr(app_module, "build_indicator_summary", lambda explanations: "关键指标显示短线偏强，但需要警惕追高风险。")

    gateway_api._run_single_workbench_analysis(
        context,
        "job-compact",
        code="002463",
        selected=["fundamental", "fund_flow"],
        cycle="1y",
        mode="单个分析",
    )
    analysis = context.get_workbench_analysis()
    assert analysis is not None
    assert "会议纪要" not in analysis["summaryBody"]
    assert "###" not in analysis["summaryBody"]
    assert len(analysis["summaryBody"]) < 120
    fundamental = next((item for item in analysis["analystViews"] if item["title"] == "基本面分析师"), None)
    assert fundamental is not None
    assert "###" not in fundamental["body"]
    assert "报告" not in fundamental["body"]
    assert "以下分析" not in fundamental["body"]
    assert "先说明" not in fundamental["body"]
    assert len(fundamental["body"]) < 180
    fund_flow = next((item for item in analysis["analystViews"] if item["title"] == "资金面分析师"), None)
    assert fund_flow is not None
    assert "###" not in fund_flow["body"]
    assert "报告" not in fund_flow["body"]
    assert "核心结论先看" not in fund_flow["body"]
    assert "以下是基于" not in fund_flow["body"]
    assert "我会重点围绕" not in fund_flow["body"]
    assert len(fund_flow["body"]) < 180
    risk = next((item for item in analysis["analystViews"] if item["title"] == "风险管理师"), None)
    assert risk is not None
    assert "如果你愿意" not in risk["body"]
    assert "仓位" in risk["body"] or "止损" in risk["body"]
    assert len(risk["body"]) < 180


def test_workbench_analysis_maps_structured_final_decision_into_readable_decision(tmp_path, monkeypatch):
    import app.stock_analysis_service as app_module

    context = _make_context(tmp_path)

    monkeypatch.setattr(
        app_module,
        "analyze_single_stock_for_batch",
        lambda symbol, period, enabled_analysts_config=None, selected_model=None, progress_callback=None: {
            "success": True,
            "symbol": symbol,
            "stock_info": {"name": "沪电股份", "current_price": 97.54},
            "indicators": {"RSI": 71.32, "MA20": 82.99, "量比": 1.22, "MACD": 2.118},
            "final_decision": {
                "rating": "持有",
                "target_price": "105.00",
                "operation_advice": "当前位置不建议追高，已有仓位可继续持有，等待回踩后再考虑加仓。",
                "position_size": "轻仓",
                "risk_warning": "短线过热，注意高位震荡风险。",
            },
            "discussion_result": "技术面偏强，但短线过热，适合持有观察。",
            "agents_results": {
                "technical": {"agent_name": "技术分析师", "analysis": "趋势保持偏强，但不适合无条件追高。"},
                "fundamental": {"agent_name": "基本面分析师", "analysis": "公司质地较好，但当前位置估值不算便宜。"},
            },
            "historical_data": [
                {"date": "2026-04-11", "close": 87.5},
                {"date": "2026-04-12", "close": 97.54},
            ],
        },
    )
    monkeypatch.setattr(
        app_module,
        "build_indicator_explanations",
        lambda indicators, current_price=None: [
            {"label": "RSI", "value": "71.32"},
            {"label": "MA20", "value": "82.99"},
        ],
    )
    monkeypatch.setattr(app_module, "build_indicator_summary", lambda explanations: "关键指标显示趋势偏强，但短线已经偏热。")

    gateway_api._run_single_workbench_analysis(
        context,
        "job-structured",
        code="002463",
        selected=["technical", "fundamental"],
        cycle="1y",
        mode="单个分析",
    )
    analysis = context.get_workbench_analysis()
    assert analysis is not None
    assert "综合决策暂不可用" not in analysis["decision"]
    assert "持有" in analysis["decision"]
    assert "轻仓" in analysis["decision"]
    assert "不建议追高" in analysis["finalDecisionText"]
    assert any(item["title"] == "操作建议" and "不建议追高" in item["body"] for item in analysis["insights"])
    assert any(item["title"] == "技术分析师" for item in analysis["analystViews"])
    assert any(item["title"] == "基本面分析师" for item in analysis["analystViews"])


def test_workbench_analysis_failure_preserves_prior_successful_cached_analysis(tmp_path, monkeypatch):
    import app.stock_analysis_service as app_module

    context = _make_context(tmp_path)
    context.stock_analysis_db().save_analysis(
        symbol="002463",
        stock_name="沪电股份",
        period="1y",
        stock_info={"symbol": "002463", "name": "沪电股份", "current_price": 89.99},
        agents_results={
            "technical": {"agent_name": "技术分析师", "summary": "趋势仍在，但更适合等待回踩。"},
            "fundamental": {"agent_name": "基本面分析师", "summary": "基本面稳定，估值不算便宜。"},
        },
        discussion_result="综合来看，当前更适合持有观察。",
        final_decision={"decision_text": "建议继续跟踪，等待更舒适的参与位置。"},
        indicators={"rsi": 71.32, "ma20": 82.99, "volume_ratio": 1.22, "macd": 2.118},
        historical_data=[
            {"date": "2026-04-11", "close": 87.5},
            {"date": "2026-04-12", "close": 89.99},
        ],
    )

    monkeypatch.setattr(
        app_module,
        "analyze_single_stock_for_batch",
        lambda *args, **kwargs: {"success": False, "error": "API调用失败: Authentication Fails (governor)", "symbol": "002463"},
    )
    monkeypatch.setattr(
        app_module,
        "build_indicator_explanations",
        lambda indicators, current_price=None: [
            {"label": "RSI", "value": "71.32"},
            {"label": "MA20", "value": "82.99"},
            {"label": "量比", "value": "1.22"},
            {"label": "MACD", "value": "2.118"},
        ],
    )
    monkeypatch.setattr(app_module, "build_indicator_summary", lambda explanations: "关键指标显示短线偏强，但需要警惕追高风险。")

    gateway_api._run_single_workbench_analysis(
        context,
        "job-fail-preserve",
        code="002463",
        selected=["technical", "fundamental"],
        cycle="1y",
        mode="单个分析",
    )

    client = TestClient(create_app(context=context))
    payload = client.get("/api/v1/workbench").json()
    analysis = payload["analysis"]
    assert analysis["symbol"] == "002463"
    assert "综合决策暂不可用" not in analysis["decision"]
    assert "建议继续跟踪" in analysis["decision"]
    assert len(analysis["indicators"]) >= 4
    assert any(item["title"] == "技术分析师" for item in analysis["analystViews"])
    assert any(item["title"] == "基本面分析师" for item in analysis["analystViews"])
    assert payload["analysisJob"]["status"] == "failed"
    assert "刷新失败" in payload["analysisJob"]["title"]
    assert "已保留上一次成功分析" in payload["analysisJob"]["message"]


def test_workbench_analysis_generates_readable_fallback_when_agent_views_exist(tmp_path, monkeypatch):
    import app.stock_analysis_service as app_module

    context = _make_context(tmp_path)

    monkeypatch.setattr(
        app_module,
        "analyze_single_stock_for_batch",
        lambda *args, **kwargs: {
            "success": True,
            "symbol": "002463",
            "stock_info": {"name": "沪电股份", "current_price": 89.99},
            "indicators": {"RSI": 71.32, "MA20": 82.99, "量比": 1.22, "MACD": 2.118},
            "final_decision": {},
            "discussion_result": "",
            "agents_results": {
                "technical": {"agent_name": "技术分析师", "summary": "趋势偏强，但当前位置不适合追高，更适合等回踩后再看。"},
                "fundamental": {"agent_name": "基本面分析师", "summary": "公司基本面稳定，但估值不算便宜，参与时要接受波动。"},
            },
            "historical_data": [
                {"date": "2026-04-11", "close": 87.5},
                {"date": "2026-04-12", "close": 89.99},
            ],
        },
    )
    monkeypatch.setattr(
        app_module,
        "build_indicator_explanations",
        lambda indicators, current_price=None: {
            "RSI": {"state": "偏热", "summary": "RSI 高于 70，短线偏热，继续追高要更谨慎。"},
            "MA20": {"state": "强于中期趋势", "summary": "当前价高于 MA20，中期趋势仍偏强。"},
            "量比": {"state": "正常成交", "summary": "量比接近 1，成交活跃度没有明显异常。"},
            "MACD": {"state": "多头动能", "summary": "MACD 大于 0，价格动能偏强。"},
        },
    )
    monkeypatch.setattr(
        app_module,
        "build_indicator_summary",
        lambda explanations: "技术面偏强，但短线已经偏热，不适合无条件追高。",
    )

    gateway_api._run_single_workbench_analysis(
        context,
        "job-readable-fallback",
        code="002463",
        selected=["technical", "fundamental"],
        cycle="1y",
        mode="单个分析",
    )

    analysis = context.get_workbench_analysis()
    assert analysis is not None
    assert "综合决策暂不可用" not in analysis["decision"]
    assert "更适合" in analysis["decision"] or "建议" in analysis["decision"]
    assert any(item["title"] == "操作建议" for item in analysis["insights"])
    assert any(item["title"] == "技术分析师" for item in analysis["analystViews"])
    assert any(item["title"] == "基本面分析师" for item in analysis["analystViews"])


def test_workbench_stale_running_job_is_normalized_to_completed_when_analysis_exists(tmp_path):
    context = _make_context(tmp_path)
    context.set_workbench_analysis(
        {
            "symbol": "002463",
            "analysts": gateway_api._analysis_options(),
            "mode": "单个分析",
            "cycle": "1y",
            "inputHint": "例如 600519 / 300390 / AAPL",
            "summaryTitle": "沪电股份 分析摘要",
            "summaryBody": "当前处于强趋势但高波动阶段，建议先轻仓观察，不宜在当前位置追高。",
            "indicators": [{"label": "RSI", "value": "71.32"}],
            "decision": "当前评级：持有；建议仓位：轻仓；目标价：108.00。",
            "finalDecisionText": "当前评级：持有；建议仓位：轻仓；目标价：108.00。",
            "insights": [{"title": "操作建议", "body": "已有仓位可继续持有，等待回踩确认。"}],
            "analystViews": [{"title": "技术分析师", "body": "趋势保持偏强，但当前位置不适合追高。"}],
            "curve": [{"date": "2026-04-11", "close": 87.5}, {"date": "2026-04-12", "close": 97.54}],
        }
    )
    context.set_workbench_analysis_job(
        {
            "id": "stale-job",
            "status": "running",
            "title": "分析进行中",
            "message": "正在保存分析结果",
            "symbol": "002463",
            "startedAt": "2026-04-14 23:44:55",
            "updatedAt": "2026-04-14 23:44:55",
        }
    )

    client = TestClient(create_app(context=context))
    payload = client.get("/api/v1/workbench").json()
    assert payload["analysisJob"]["status"] == "completed"
    assert "分析已完成" in payload["analysisJob"]["title"]

    rerun = client.post("/api/v1/workbench/actions/analysis", json={"stockCode": "002463"})
    assert rerun.status_code == 200
    assert rerun.json()["analysisJob"]["status"] in {"queued", "running"}


def test_hydrate_cached_workbench_analysis_keeps_generated_time_indicators_and_curve(tmp_path):
    context = _make_context(tmp_path)
    context.stock_analysis_db().save_analysis(
        symbol="600519",
        stock_name="贵州茅台",
        period="1y",
        stock_info={"symbol": "600519", "name": "贵州茅台", "current_price": 1453.96},
        agents_results={
            "technical": {"agent_name": "技术分析师", "summary": "趋势稳健，回踩后更适合继续跟踪。"},
            "fundamental": {"agent_name": "基本面分析师", "summary": "盈利质量稳定，但估值不算便宜。"},
        },
        discussion_result="综合来看，适合继续跟踪，但当前位置不建议追高。",
        final_decision={"decision_text": "建议继续跟踪，等待更好的买入时机。"},
        indicators={"rsi": 53.79, "ma20": 1441.86, "volume_ratio": 1.13, "macd": 6.2792},
        historical_data=[
            {"date": "2026-04-11", "close": 1430.0},
            {"date": "2026-04-12", "close": 1453.96},
        ],
    )

    stock_name = gateway_api._hydrate_cached_workbench_analysis(
        context,
        code="600519",
        selected=["technical", "fundamental"],
        cycle="1y",
        mode="单个分析",
    )

    analysis = context.get_workbench_analysis()
    assert stock_name == "贵州茅台"
    assert analysis["generatedAt"]
    assert any(item["label"] == "RSI" and item["value"] != "--" for item in analysis["indicators"])
    assert len(analysis["curve"]) == 2
    assert "最近一次有效分析时间" not in analysis["summaryBody"]


def test_hydrate_cached_workbench_analysis_backfills_legacy_records(tmp_path, monkeypatch):
    import app.stock_analysis_service as app_module

    context = _make_context(tmp_path)
    context.stock_analysis_db().save_analysis(
        symbol="002463",
        stock_name="沪电股份",
        period="1y",
        stock_info={"symbol": "002463", "name": "沪电股份", "current_price": 89.99},
        agents_results={"technical": {"agent_name": "技术分析师", "summary": "趋势偏强，但不建议追高。"}},
        discussion_result="趋势偏强，但更适合等回踩。",
        final_decision={"decision_text": "建议观察。"},
    )

    stock_data = pd.DataFrame(
        [{"Close": 87.5}, {"Close": 89.99}],
        index=pd.to_datetime(["2026-04-11", "2026-04-12"]),
    )
    indicators = {"rsi": 71.32, "ma20": 82.99, "volume_ratio": 1.22, "macd": 2.118}

    monkeypatch.setattr(
        app_module,
        "get_stock_data",
        lambda symbol, period: (
            {"symbol": symbol, "name": "沪电股份", "current_price": 89.99},
            stock_data,
            indicators,
        ),
    )

    gateway_api._hydrate_cached_workbench_analysis(
        context,
        code="002463",
        selected=["technical"],
        cycle="1y",
        mode="单个分析",
    )

    analysis = context.get_workbench_analysis()
    assert any(item["label"] == "RSI" and item["value"] != "--" for item in analysis["indicators"])
    assert len(analysis["curve"]) == 2


def test_workbench_snapshot_rebuilds_stale_in_memory_analysis_from_cached_record(tmp_path):
    context = _make_context(tmp_path)
    context.stock_analysis_db().save_analysis(
        symbol="002463",
        stock_name="沪电股份",
        period="1y",
        stock_info={"symbol": "002463", "name": "沪电股份", "current_price": 97.54},
        agents_results={
            "technical": {"agent_name": "技术分析师", "summary": "趋势仍偏强，但当前位置不建议追高。"},
            "fundamental": {"agent_name": "基本面分析师", "summary": "公司基本面扎实，但当前估值不便宜。"},
        },
        discussion_result="整体更适合持有观察，不建议在当前位置盲目追高。",
        final_decision={
            "rating": "持有",
            "position_size": "轻仓",
            "target_price": "108.00",
            "operation_advice": "当前不建议重仓追高，已有仓位可继续持有，等待回踩后再考虑加仓。",
        },
        indicators={"rsi": 71.32, "ma20": 82.99, "volume_ratio": 1.22, "macd": 2.118},
        historical_data=[
            {"date": "2026-04-11", "close": 87.5},
            {"date": "2026-04-12", "close": 97.54},
        ],
    )
    context.set_workbench_analysis(
        {
            "symbol": "002463",
            "analysts": gateway_api._analysis_options(["technical", "fundamental"]),
            "mode": "单个分析",
            "cycle": "1y",
            "inputHint": "例如 600519 / 300390 / AAPL",
            "summaryTitle": "002463 分析摘要",
            "summaryBody": "当前价较高，先观察。 最近一次有效分析时间：2026-04-15T07:58:44.770859。",
            "indicators": [
                {"label": "RSI", "value": "暂无数据"},
                {"label": "MA20", "value": "暂无判断"},
            ],
            "decision": "暂无明确结论",
            "finalDecisionText": "",
            "insights": [{"title": "操作建议", "body": "当前先观察。"}],
            "analystViews": [],
            "curve": [],
        }
    )

    snapshot = gateway_api._snapshot_workbench(context)
    analysis = snapshot["analysis"]
    assert analysis["generatedAt"]
    assert "最近一次有效分析时间" not in analysis["summaryBody"]
    assert "不建议重仓追高" in analysis["finalDecisionText"]
    assert any(item["title"] == "技术分析师" for item in analysis["analystViews"])
    assert any(item["label"] == "RSI" and item["value"] != "暂无数据" for item in analysis["indicators"])
    assert len(analysis["curve"]) == 2


def test_workbench_snapshot_prefers_latest_complete_cached_record_over_newer_incomplete_one(tmp_path):
    context = _make_context(tmp_path)
    context.stock_analysis_db().save_analysis(
        symbol="002463",
        stock_name="沪电股份",
        period="1y",
        stock_info={"symbol": "002463", "name": "沪电股份", "current_price": 97.54},
        agents_results={
            "technical": {"agent_name": "技术分析师", "summary": "趋势仍偏强，但当前位置不建议追高。"},
            "fundamental": {"agent_name": "基本面分析师", "summary": "公司基本面扎实，但当前估值不便宜。"},
        },
        discussion_result="整体更适合持有观察，不建议在当前位置盲目追高。",
        final_decision={
            "rating": "持有",
            "position_size": "轻仓",
            "target_price": "108.00",
            "operation_advice": "当前不建议重仓追高，已有仓位可继续持有，等待回踩后再考虑加仓。",
        },
        indicators={"rsi": 71.32, "ma20": 82.99, "volume_ratio": 1.22, "macd": 2.118},
        historical_data=[
            {"date": "2026-04-11", "close": 87.5},
            {"date": "2026-04-12", "close": 97.54},
        ],
    )
    context.stock_analysis_db().save_analysis(
        symbol="002463",
        stock_name="沪电股份",
        period="1y",
        stock_info={"symbol": "002463", "name": "沪电股份", "current_price": 89.99},
        agents_results={
            "technical": {"agent_name": "技术分析师", "summary": "价格冲高后分歧加大。"},
        },
        discussion_result="团队讨论未形成完整结论。",
        final_decision={"decision_text": "建议继续观察。"},
    )
    context.set_workbench_analysis(
        {
            "symbol": "002463",
            "analysts": gateway_api._analysis_options(["technical", "fundamental"]),
            "mode": "单个分析",
            "cycle": "1y",
            "inputHint": "例如 600519 / 300390 / AAPL",
            "summaryTitle": "002463 分析摘要",
            "summaryBody": "当前价较高，先观察。 最近一次有效分析时间：2026-04-15T08:12:46.151251。",
            "indicators": [
                {"label": "RSI", "value": "暂无数据"},
                {"label": "MA20", "value": "暂无判断"},
            ],
            "decision": "暂无明确结论",
            "finalDecisionText": "",
            "insights": [{"title": "操作建议", "body": "当前先观察。"}],
            "analystViews": [],
            "curve": [],
        }
    )

    snapshot = gateway_api._snapshot_workbench(context)
    analysis = snapshot["analysis"]
    assert analysis["generatedAt"]
    assert "最近一次有效分析时间" not in analysis["summaryBody"]
    assert "不建议重仓追高" in analysis["finalDecisionText"]
    assert any(item["title"] == "技术分析师" for item in analysis["analystViews"])
    assert any(item["title"] == "基本面分析师" for item in analysis["analystViews"])
    assert any(item["label"] == "RSI" and item["value"] != "暂无数据" for item in analysis["indicators"])
    assert len(analysis["curve"]) == 2


def test_portfolio_position_detail_includes_cached_stock_analysis(tmp_path):
    context = _make_context(tmp_path)
    context.stock_analysis_db().save_analysis(
        symbol="600519",
        stock_name="贵州茅台",
        period="1y",
        stock_info={"symbol": "600519", "name": "贵州茅台", "current_price": 1453.96, "industry": "白酒"},
        agents_results={
            "technical": {"agent_name": "技术分析师", "summary": "趋势稳健，等待回踩更合适。"},
            "risk": {"agent_name": "风险管理师", "summary": "高位波动，需要控制仓位。"},
        },
        discussion_result="团队判断趋势仍在，但当前位置不建议追高。",
        final_decision={
            "rating": "持有",
            "position_size": "轻仓",
            "operation_advice": "建议继续跟踪，等待更舒适的参与位置。",
        },
        indicators={"rsi": 53.79, "ma20": 1441.86, "volume_ratio": 1.13, "macd": 6.2792},
        historical_data=[
            {"date": "2026-04-11", "close": 1430.0},
            {"date": "2026-04-12", "close": 1453.96},
        ],
    )

    client = TestClient(create_app(context=context))
    response = client.get("/api/v1/portfolio_v2/positions/600519")

    assert response.status_code == 200
    stock_analysis = response.json()["detail"]["stockAnalysis"]
    assert stock_analysis["symbol"] == "600519"
    assert stock_analysis["stockName"] == "贵州茅台"
    assert "不建议追高" in stock_analysis["summaryBody"]
    assert any(item["label"] == "RSI" and item["value"] != "--" for item in stock_analysis["indicators"])
    assert any(item["title"] == "技术分析师" for item in stock_analysis["analystViews"])


def test_portfolio_position_detail_keeps_full_cached_stock_analysis_text(tmp_path):
    context = _make_context(tmp_path)
    discussion_tail = "团队讨论完整结论末尾标记"
    analyst_tail = "技术观点完整结论末尾标记"
    advice_tail = "操作建议完整结论末尾标记"
    context.stock_analysis_db().save_analysis(
        symbol="600519",
        stock_name="贵州茅台",
        period="1y",
        stock_info={"symbol": "600519", "name": "贵州茅台", "current_price": 1453.96, "industry": "白酒"},
        agents_results={
            "technical": {
                "agent_name": "技术分析师",
                "summary": "技术面分析：" + "趋势延续、量价配合，" * 30 + analyst_tail,
            },
        },
        discussion_result={"summary": "团队讨论：" + "基本面稳定、趋势仍在，" * 30 + discussion_tail},
        final_decision={
            "rating": "持有",
            "operation_advice": "操作建议：" + "等待回踩确认，控制仓位，" * 30 + advice_tail,
        },
        indicators={"rsi": 53.79, "ma20": 1441.86, "volume_ratio": 1.13, "macd": 6.2792},
        historical_data=[{"date": "2026-04-12", "close": 1453.96}],
    )

    client = TestClient(create_app(context=context))
    response = client.get("/api/v1/portfolio_v2/positions/600519")

    assert response.status_code == 200
    stock_analysis = response.json()["detail"]["stockAnalysis"]
    assert discussion_tail in stock_analysis["summaryBody"]
    assert any(analyst_tail in item["body"] for item in stock_analysis["analystViews"])
    assert any(advice_tail in item["body"] for item in stock_analysis["insights"])


def test_portfolio_position_detail_uses_cached_watchlist_metadata_without_blocking_remote_refresh(tmp_path, monkeypatch):
    quote_calls: list[str] = []
    basic_info_calls: list[str] = []
    selector_dir = tmp_path / "selector_results"
    selector_dir.mkdir(parents=True, exist_ok=True)
    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=selector_dir,
        watchlist_db_file=tmp_path / "watchlist.db",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        portfolio_db_file=tmp_path / "portfolio.db",
        monitor_db_file=tmp_path / "monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
        stock_analysis_db_file=tmp_path / "analysis.db",
        main_force_batch_db_file=tmp_path / "main_force_batch.db",
        stock_name_resolver=lambda code: code,
        quote_fetcher=lambda code, preferred_name=None: quote_calls.append(code)
        or {"stock_code": code, "name": "欧普泰", "current_price": 18.88},
        basic_info_fetcher=lambda code: basic_info_calls.append(code)
        or {"name": "欧普泰", "industry": "半导体"},
    )
    context.watchlist().add_stock(
        "920414",
        "欧普泰",
        "AI选股",
        latest_price=18.88,
        metadata={"industry": "半导体", "sector": "半导体"},
    )
    monkeypatch.setattr(
        gateway_api,
        "_portfolio_technical_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("technical snapshot should not block watchlist detail load")),
    )

    client = TestClient(create_app(context=context))
    response = client.get("/api/v1/portfolio_v2/positions/920414")

    assert response.status_code == 200
    detail = response.json()["detail"]
    assert quote_calls == []
    assert basic_info_calls == []
    assert detail["stockName"] == "欧普泰"
    assert detail["sector"] == "半导体"
    assert detail["marketSnapshot"]["latestPrice"] == "18.88"
    assert detail["marketSnapshot"]["source"] == "AI选股"


def test_portfolio_refresh_indicators_fetches_and_persists_watchlist_snapshot(tmp_path, monkeypatch):
    quote_calls: list[tuple[str, str | None]] = []
    basic_info_calls: list[str] = []
    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        watchlist_db_file=tmp_path / "watchlist.db",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        portfolio_db_file=tmp_path / "portfolio.db",
        monitor_db_file=tmp_path / "monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
        stock_analysis_db_file=tmp_path / "analysis.db",
        main_force_batch_db_file=tmp_path / "main_force_batch.db",
        quote_fetcher=lambda code, preferred_name=None: quote_calls.append((code, preferred_name))
        or {"stock_code": code, "name": "欧普泰", "current_price": 18.88},
        basic_info_fetcher=lambda code: basic_info_calls.append(code)
        or {"name": "欧普泰", "industry": "半导体"},
    )
    context.selector_result_dir.mkdir(parents=True, exist_ok=True)
    context.watchlist().add_stock("920414", "920414", "AI选股", latest_price=None, metadata={"industry": "半导体"})
    monkeypatch.setattr(
        gateway_api,
        "_portfolio_technical_snapshot",
        lambda symbol, cycle="1y", force_refresh=False: {
            "symbol": symbol,
            "stockName": "欧普泰",
            "sector": "半导体",
            "kline": [{"label": "2026-04-24", "value": 18.88, "open": 18.1, "high": 19.0, "low": 18.0, "close": 18.88}],
            "indicators": [{"label": "Price", "value": "18.88", "hint": "Latest traded price."}],
        },
    )

    client = TestClient(create_app(context=context))
    response = client.post(
        "/api/v1/portfolio_v2/actions/refresh-indicators",
        json={"symbols": ["920414"], "selectedSymbol": "920414", "cycle": "1y"},
    )

    assert response.status_code == 200
    detail = response.json()["detail"]
    watch = context.watchlist().get_watch("920414")
    assert quote_calls == [("920414", None)]
    assert basic_info_calls == ["920414"]
    assert watch is not None
    assert watch["stock_name"] == "欧普泰"
    assert watch["latest_price"] == 18.88
    assert watch["metadata"]["industry"] == "半导体"
    assert detail["marketSnapshot"]["latestPrice"] == "18.88"
    assert detail["stockName"] == "欧普泰"
    assert detail["kline"][0]["close"] == 18.88


def test_portfolio_position_detail_does_not_block_on_technical_snapshot_for_holdings(tmp_path, monkeypatch):
    context = _make_context(tmp_path)
    manager = context.portfolio_manager()
    success, _, stock_id = manager.add_stock("600519", "贵州茅台", "白酒", cost_price=1400.0, quantity=100)
    assert success is True
    assert stock_id is not None
    manager.db.save_analysis(
        stock_id=stock_id,
        rating="持有",
        confidence=7.5,
        current_price=1453.96,
        summary="持仓分析缓存",
    )
    monkeypatch.setattr(
        gateway_api,
        "_portfolio_technical_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("technical snapshot should only run on manual refresh")),
    )

    client = TestClient(create_app(context=context))
    response = client.get("/api/v1/portfolio_v2/positions/600519")

    assert response.status_code == 200
    detail = response.json()["detail"]
    assert detail["stockName"] == "贵州茅台"
    assert detail["sector"] == "白酒"
    assert detail["indicators"] == []
    assert detail["decision"]["summary"] == "持仓分析缓存"


def test_discover_snapshot_aggregates_selector_results(tmp_path):
    context = _make_context(tmp_path)
    selector_dir = tmp_path / "selector_results"
    _seed_discover_result(selector_dir)
    _seed_simple_selector_result(
        selector_dir,
        "low_price_bull",
        [
            {
                "股票代码": "000001",
                "股票简称": "平安银行",
                "所属行业": "银行",
                "最新价": 10.12,
                "总市值": 2000.0,
                "市盈率": 4.2,
                "市净率": 0.6,
                "理由": "低价高弹性",
            }
        ],
        "2026-04-13 15:00:00",
    )

    client = TestClient(create_app(context=context))

    response = client.get("/api/v1/discover")
    assert response.status_code == 200
    payload = response.json()
    rows = payload["candidateTable"]["rows"]
    assert [row["code"] for row in rows][:2] == ["000001", "600519"]
    assert any(strategy["name"] == "主力选股" and strategy["status"].startswith("最近推荐") for strategy in payload["strategies"])
    assert "已汇总 2 个发现策略的最新结果" in payload["summary"]["body"]


def test_discover_run_strategy_executes_real_selector_runners_and_persists_results(tmp_path, monkeypatch):
    context = _make_context(tmp_path)
    selector_dir = tmp_path / "selector_results"

    class FakeMainForceSelector:
        def get_main_force_stocks(self, **kwargs):
            return True, pd.DataFrame(
                [
                    {
                        "股票代码": "688111",
                        "股票简称": "金山办公",
                        "所属同花顺行业": "办公软件",
                        "最新价": 321.88,
                        "总市值": 1234.0,
                        "市盈率": 48.5,
                        "市净率": 8.2,
                        "理由": "主力资金回流",
                    }
                ]
            ), "ok"

    class FakeLowPriceBullSelector:
        def get_low_price_stocks(self, top_n=5):
            return True, pd.DataFrame(
                [
                    {
                        "股票代码": "000001",
                        "股票简称": "平安银行",
                        "所属行业": "银行",
                        "最新价": 10.12,
                        "总市值": 2000.0,
                        "市盈率": 4.2,
                        "市净率": 0.6,
                        "理由": "低价高弹性",
                    }
                ]
            ), "ok"

    class FakeSmallCapSelector:
        def get_small_cap_stocks(self, top_n=5):
            return True, pd.DataFrame(
                [
                    {
                        "股票代码": "300750",
                        "股票简称": "宁德时代",
                        "所属行业": "电池",
                        "最新价": 198.35,
                        "总市值": 9000.0,
                        "市盈率": 18.2,
                        "市净率": 5.6,
                        "理由": "小而活跃",
                    }
                ]
            ), "ok"

    class FakeProfitGrowthSelector:
        def get_profit_growth_stocks(self, top_n=5):
            return True, pd.DataFrame(
                [
                    {
                        "股票代码": "600519",
                        "股票简称": "贵州茅台",
                        "所属行业": "白酒",
                        "最新价": 1453.96,
                        "总市值": 18200.0,
                        "市盈率": 26.1,
                        "市净率": 9.8,
                        "理由": "利润增长稳定",
                    }
                ]
            ), "ok"

    class FakeValueStockSelector:
        def get_value_stocks(self, top_n=10):
            return True, pd.DataFrame(
                [
                    {
                        "股票代码": "600036",
                        "股票简称": "招商银行",
                        "所属行业": "银行",
                        "最新价": 42.88,
                        "总市值": 11000.0,
                        "市盈率": 6.8,
                        "市净率": 1.0,
                        "理由": "低估值修复",
                    }
                ]
            ), "ok"

    monkeypatch.setattr(gateway_api, "MainForceStockSelector", FakeMainForceSelector)
    monkeypatch.setattr(gateway_api, "LowPriceBullSelector", FakeLowPriceBullSelector)
    monkeypatch.setattr(gateway_api, "SmallCapSelector", FakeSmallCapSelector)
    monkeypatch.setattr(gateway_api, "ProfitGrowthSelector", FakeProfitGrowthSelector)
    monkeypatch.setattr(gateway_api, "ValueStockSelector", FakeValueStockSelector)

    client = TestClient(create_app(context=context))

    response = client.post("/api/v1/discover/actions/run-strategy", json={})
    assert response.status_code == 200
    payload = response.json()
    codes = {row["code"] for row in payload["candidateTable"]["rows"]}
    assert {"688111", "000001", "300750", "600519", "600036"}.issubset(codes)

    persisted = client.get("/api/v1/discover")
    assert persisted.status_code == 200
    persisted_codes = {row["code"] for row in persisted.json()["candidateTable"]["rows"]}
    assert {"688111", "000001", "300750", "600519", "600036"}.issubset(persisted_codes)


def test_discover_watchlist_action_handles_dash_latest_price(tmp_path):
    context = _make_context(tmp_path)
    save_latest_result(
        "ai_scanner",
        {
            "stocks_df": pd.DataFrame(
                [
                    {
                        "股票代码": "920414",
                        "股票简称": "欧普泰",
                        "所属行业": "半导体",
                        "最新价": "--",
                        "理由": "AI候选",
                    }
                ]
            ),
            "selected_at": "2026-04-24 00:12:29",
        },
        base_dir=context.selector_result_dir,
    )
    client = TestClient(create_app(context=context))

    response = client.post("/api/v1/discover/actions/batch-watchlist", json={"codes": ["920414"]})

    assert response.status_code == 200
    watch = context.watchlist().get_watch("920414")
    assert watch is not None
    assert watch["stock_code"] == "920414"
    assert watch["stock_name"] == "欧普泰"
    assert watch["latest_price"] == 0.0


def test_live_sim_actions_use_scheduler_and_candidate_pool(tmp_path, monkeypatch):
    context = _make_context(tmp_path)
    watchlist = context.watchlist()
    watchlist.add_manual_stock("600519")
    watchlist.add_manual_stock("000001")
    from app.watchlist_integration import add_watchlist_rows_to_quant_pool

    add_watchlist_rows_to_quant_pool(["600519", "000001"], watchlist, context.candidate_pool(), db_file=context.quant_sim_db_file)

    fake_scheduler = FakeQuantScheduler()
    analyzed_codes: list[str] = []

    monkeypatch.setattr(UIApiContext, "scheduler", lambda self: fake_scheduler, raising=False)
    monkeypatch.setattr(
        "app.gateway_api.QuantSimEngine.analyze_candidate",
        lambda self, candidate, analysis_timeframe="1d", strategy_mode="auto": analyzed_codes.append(candidate["stock_code"]) or {"action": "HOLD"},
    )

    client = TestClient(create_app(context=context))

    save_resp = client.post("/api/v1/quant/live-sim/actions/save", json={"strategyMode": "defensive"})
    assert save_resp.status_code == 200
    assert any(call[0] == "update_config" for call in fake_scheduler.calls)

    start_resp = client.post("/api/v1/quant/live-sim/actions/start", json={})
    assert start_resp.status_code == 200
    assert start_resp.json()["status"]["running"] == "运行中"

    run_resp = client.post("/api/v1/quant/live-sim/actions/bulk-quant", json={"codes": ["600519", "000001"]})
    assert run_resp.status_code == 200
    assert ("run_once", "ui_manual_run") in fake_scheduler.calls

    analyze_resp = client.post("/api/v1/quant/live-sim/actions/analyze-candidate", json="600519")
    assert analyze_resp.status_code == 200
    assert analyzed_codes == ["600519"]

    delete_resp = client.post("/api/v1/quant/live-sim/actions/delete-candidate", json={"code": "000001"})
    assert delete_resp.status_code == 200
    deleted_rows = delete_resp.json()["candidatePool"]["rows"]
    assert {row["id"] for row in deleted_rows} == {"600519"}

    reset_resp = client.post("/api/v1/quant/live-sim/actions/reset", json={"initialCash": 20000})
    assert reset_resp.status_code == 200

    stop_resp = client.post("/api/v1/quant/live-sim/actions/stop", json={})
    assert stop_resp.status_code == 200
    assert stop_resp.json()["status"]["running"] == "已停止"


def test_his_replay_actions_enqueue_cancel_delete_and_rerun(tmp_path, monkeypatch):
    context = _make_context(tmp_path)
    fake_replay = FakeReplayService()
    monkeypatch.setattr(UIApiContext, "replay_service", lambda self: fake_replay, raising=False)

    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-10 15:00:00",
        initial_cash=100000,
        status="completed",
        selected_strategy_profile_id="aggressive_v23",
        metadata={"selected_strategy_mode": "auto"},
    )
    db.update_sim_run_progress(
        run_id,
        progress_current=2,
        progress_total=12,
        latest_checkpoint_at="2026-04-02 10:00:00",
        status_message="已完成第 2/12 个检查点",
    )

    client = TestClient(create_app(context=context))

    snapshot_resp = client.get("/api/v1/quant/his-replay")
    assert snapshot_resp.status_code == 200
    task = snapshot_resp.json()["tasks"][0]
    assert task["progressCurrent"] == 2
    assert task["progressTotal"] == 12
    assert task["checkpointCount"] == 0
    assert task["latestCheckpointAt"] == "2026-04-02 10:00:00"
    assert task["mode"] == "historical_range"
    assert task["timeframe"] == "30m"
    assert task["market"] == "CN"
    assert snapshot_resp.json()["config"]["strategyProfileId"] == "aggressive"

    start_resp = client.post(
        "/api/v1/quant/his-replay/actions/start",
        json={"initialCash": 300000, "strategyProfileId": "aggressive_v23"},
    )
    assert start_resp.status_code == 200
    assert fake_replay.calls and fake_replay.calls[0][0] == "historical"
    assert fake_replay.calls[0][1]["initial_cash"] == 300000
    assert fake_replay.calls[0][1]["strategy_profile_id"] == "aggressive"

    continue_resp = client.post("/api/v1/quant/his-replay/actions/continue", json={})
    assert continue_resp.status_code == 200
    assert fake_replay.calls[-1][0] == "past_to_live"

    cancel_resp = client.post("/api/v1/quant/his-replay/actions/cancel", json={"id": run_id})
    assert cancel_resp.status_code == 200
    latest_run = context.quant_db().get_sim_runs(limit=1)[0]
    assert latest_run["status"] in {"cancel_requested", "cancelled", "completed"}

    history_resp = client.post("/api/v1/history/actions/rerun", json={})
    assert history_resp.status_code == 200
    assert fake_replay.calls[-1][0] == "historical"

    delete_resp = client.post("/api/v1/quant/his-replay/actions/delete", json={"id": run_id})
    assert delete_resp.status_code == 200
    assert all(int(item["id"]) != run_id for item in context.quant_db().get_sim_runs(limit=20))


def test_his_replay_cancel_stale_running_run_clears_active_lock(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-10 15:00:00",
        initial_cash=100000,
        status="running",
        progress_current=5,
        progress_total=100,
        metadata={"selected_strategy_mode": "auto"},
    )

    client = TestClient(create_app(context=context))
    cancel_resp = client.post("/api/v1/quant/his-replay/actions/cancel", json={"id": run_id})

    assert cancel_resp.status_code == 200
    run = context.quant_db().get_sim_run(run_id)
    assert run is not None
    assert run["status"] == "cancelled"
    assert run["cancel_requested"] == 1
    assert context.quant_db().get_active_sim_run() is None


def test_his_replay_cancel_live_running_run_releases_active_lock(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-10 15:00:00",
        initial_cash=100000,
        status="running",
        progress_current=5,
        progress_total=100,
        metadata={"selected_strategy_mode": "auto"},
    )
    db.set_sim_run_worker_pid(run_id, os.getpid())

    client = TestClient(create_app(context=context))
    cancel_resp = client.post("/api/v1/quant/his-replay/actions/cancel", json={"id": run_id})

    assert cancel_resp.status_code == 200
    run = context.quant_db().get_sim_run(run_id)
    assert run is not None
    assert run["status"] == "cancel_requested"
    assert run["cancel_requested"] == 1
    assert context.quant_db().get_active_sim_run() is None


def test_his_replay_progress_endpoint_returns_lightweight_task_progress(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2025-12-01 09:30:00",
        end_datetime="2026-01-06 15:00:00",
        initial_cash=100000,
        status="running",
        metadata={"selected_strategy_mode": "auto"},
    )
    db.update_sim_run_progress(
        run_id,
        progress_current=1497,
        progress_total=1992,
        latest_checkpoint_at="2026-01-06 10:30:00",
        status_message="检查点 2026-01-06 10:30:00：分析候选股 1/9 002463",
    )

    client = TestClient(create_app(context=context))
    response = client.get("/api/v1/quant/his-replay/progress")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"updatedAt", "tasks", "holdings", "trades", "signals", "tradeCostSummary"}
    task = payload["tasks"][0]
    assert task["runId"] == str(run_id)
    assert task["status"] == "running"
    assert task["stage"] == "检查点 2026-01-06 10:30:00：分析候选股 1/9 002463"
    assert task["progressCurrent"] == 1497
    assert task["progressTotal"] == 1992
    assert task["progress"] == 75
    assert payload["signals"]["rows"] == []
    assert payload["trades"]["rows"] == []
    assert payload["tradeCostSummary"]
    assert "curve" not in payload


def test_his_replay_progress_endpoint_does_not_read_full_trade_cost_summary(tmp_path, monkeypatch):
    context = _make_context(tmp_path)
    db = context.quant_db()
    db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2025-12-01 09:30:00",
        end_datetime="2026-01-06 15:00:00",
        initial_cash=100000,
        status="running",
        metadata={"selected_strategy_mode": "auto"},
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("progress endpoint must not scan full trade cost summary")

    monkeypatch.setattr("app.quant_sim.db.QuantSimDB.get_sim_run_trade_cost_summary", fail_if_called)

    response = TestClient(create_app(context=context)).get("/api/v1/quant/his-replay/progress")

    assert response.status_code == 200
    metric_labels = {item["label"] for item in response.json()["tradeCostSummary"]}
    assert "买入笔数" in metric_labels
    assert "加仓次数" not in metric_labels
    assert "买入lot" not in metric_labels


def test_his_replay_progress_endpoint_reports_database_busy(tmp_path, monkeypatch):
    context = _make_context(tmp_path)
    client = TestClient(create_app(context=context))

    def locked_snapshot(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(gateway_api, "_snapshot_his_replay_progress", locked_snapshot)

    response = client.get("/api/v1/quant/his-replay/progress")

    assert response.status_code == 503
    assert response.json()["detail"] == "历史回放正在写入数据库，请稍后刷新。"


def test_live_sim_snapshot_exposes_trade_cost_ledger(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    db.configure_account(100000)
    db.update_scheduler_config(commission_rate=0.001, sell_tax_rate=0.002)
    candidate_id = db.add_candidate(
        {
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "source": "manual",
            "latest_price": 10,
        }
    )
    signal_id = db.add_signal(
        {
            "candidate_id": candidate_id,
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "action": "BUY",
            "confidence": 88,
            "reasoning": "建仓",
            "position_size_pct": 20,
            "status": "pending",
        }
    )
    db.confirm_signal(
        signal_id,
        executed_action="buy",
        price=10,
        quantity=100,
        note="成本展示",
        executed_at="2026-04-08 10:00:00",
        apply_trade_cost=True,
    )

    payload = TestClient(create_app(context=context)).get("/api/v1/quant/live-sim").json()

    assert payload["trades"]["columns"] == [
        "时间",
        "代码",
        "动作",
        "类型",
        "数量",
        "价格",
        "成交毛额",
        "手续费",
        "印花税",
        "总费用",
        "现金影响",
        "盈亏",
        "盈亏率",
        "Slot用量",
        "执行明细",
        "备注",
    ]
    row = payload["trades"]["rows"][0]
    assert row["cells"][3:16] == [
        "建仓",
        "100",
        "10.00",
        "1000.00",
        "1.00",
        "0.00",
        "1.00",
        "1001.00",
        "0.00",
        "--",
        "1 slot",
        row["cells"][14],
        "成本展示",
    ]
    assert "T+1" in row["cells"][14]
    assert "slot#1 1001.00" in row["cells"][14]
    summary_by_label = {item["label"]: item["value"] for item in payload["tradeCostSummary"]}
    assert summary_by_label["买入毛额"] == "1000.00"
    assert summary_by_label["买入总成本"] == "1001.00"
    assert summary_by_label["总费用"] == "1.00"
    assert summary_by_label["买入lot"] == "1"
    assert summary_by_label["占用slot"] == "1"
    assert summary_by_label["剩余lot"] == "1"


def test_his_replay_snapshot_exposes_trade_cost_ledger(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2025-12-01 09:30:00",
        end_datetime="2026-01-06 15:00:00",
        initial_cash=100000,
        status="completed",
        metadata={"selected_strategy_mode": "auto"},
    )
    db.replace_sim_run_results(
        run_id,
        trades=[
            {
                "signal_id": 1,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "SELL",
                "price": 11,
                "quantity": 100,
                "amount": 1096.7,
                "gross_amount": 1100,
                "commission_fee": 1.1,
                "sell_tax_fee": 2.2,
                "net_amount": 1096.7,
                "fee_total": 3.3,
                "realized_pnl": 95.7,
                "trade_metadata_json": json.dumps(
                    {
                        "side": "SELL",
                        "consumed_lots": [{"lot_id": 1, "quantity": 100, "unlock_date": "2026-01-02"}],
                        "released_slot_allocations": [{"slot_index": 1, "released_cash": 1096.7, "occupied_release": 1001.0}],
                    },
                    ensure_ascii=False,
                ),
                "executed_at": "2026-01-06 10:00:00",
                "created_at": "2026-01-06 10:00:00",
            }
        ],
        snapshots=[],
        positions=[],
        signals=[],
    )
    db.finalize_sim_run(
        run_id,
        status="completed",
        final_equity=101096.7,
        total_return_pct=1.0967,
        max_drawdown_pct=0.0,
        win_rate=100.0,
        trade_count=1,
        metadata={
            "final_slot_summary": {
                "available_cash": 100000.0,
                "occupied_cash": 0.0,
                "settling_cash": 1096.7,
                "slot_count": 5,
                "slot_budget": 20000.0,
            },
            "capital_max_slots": 25,
            "capital_sell_cash_reuse_policy": "next_batch",
        },
    )

    payload = TestClient(create_app(context=context)).get("/api/v1/quant/his-replay").json()

    assert payload["trades"]["columns"] == [
        "时间",
        "信号ID",
        "代码",
        "动作",
        "类型",
        "数量",
        "价格",
        "成交毛额",
        "手续费",
        "印花税",
        "总费用",
        "现金影响",
        "盈亏",
        "盈亏率",
        "执行明细",
    ]
    assert "Slot用量" not in payload["trades"]["columns"]
    row = payload["trades"]["rows"][0]
    assert row["cells"][4:15] == [
        "卖出",
        "100",
        "11.00",
        "1100.00",
        "1.10",
        "2.20",
        "3.30",
        "1096.70",
        "95.70",
        "9.56%",
        "消耗 1 lot/100股 · lot 1 · T+1已解锁 2026-01-02 · 释放 slot#1 1096.70",
    ]
    assert "T+1已解锁" in row["cells"][14]
    summary_by_label = {item["label"]: item["value"] for item in payload["tradeCostSummary"]}
    assert summary_by_label["交易笔数"] == "1"
    assert summary_by_label["初始资金"] == "100000.00"
    assert summary_by_label["最终权益"] == "101096.70"
    assert summary_by_label["胜率"] == "100.00%"
    assert summary_by_label["总盈亏"] == "1096.70"
    assert summary_by_label["卖出毛额"] == "1100.00"
    assert summary_by_label["卖出到账"] == "1096.70"
    assert summary_by_label["总费用"] == "3.30"
    assert summary_by_label["印花税"] == "2.20"
    assert summary_by_label["实现盈亏"] == "95.70"
    assert summary_by_label["最大占用slot"] == "0"
    assert summary_by_label["最终待结算"] == "1096.70"
    assert "资金池下限" not in summary_by_label
    assert "资金池上限" not in summary_by_label
    assert "最小Slot" not in summary_by_label
    assert "资金复用" not in summary_by_label


def test_his_replay_capital_pool_endpoint_exposes_slots_and_lots(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2025-12-01 09:30:00",
        end_datetime="2026-01-06 15:00:00",
        initial_cash=50000,
        status="completed",
        metadata={
            "selected_strategy_mode": "auto",
            "final_slot_summary": {
                "available_cash": 24899.0,
                "occupied_cash": 25101.0,
                "settling_cash": 0.0,
                "slot_count": 2,
                "slot_budget": 25000.0,
            },
        },
    )
    db.replace_sim_run_results(
        run_id,
        trades=[
            {
                "signal_id": 7,
                "stock_code": "301381",
                "stock_name": "宏工科技",
                "action": "BUY",
                "price": 20.8,
                "quantity": 1200,
                "gross_amount": 24960.0,
                "commission_fee": 1.0,
                "sell_tax_fee": 0.0,
                "fee_total": 1.0,
                "net_amount": 24961.0,
                "amount": 24961.0,
                "trade_metadata_json": json.dumps(
                    {
                        "side": "BUY",
                        "is_add": False,
                        "lot": {
                            "lot_id": "301381-20260106-1",
                            "lot_count": 12,
                            "quantity": 1200,
                            "remaining_quantity": 1200,
                            "entry_price": 20.8,
                            "unlock_date": "2026-01-07",
                        },
                        "slot_allocations": [
                            {"slot_index": 1, "allocated_cash": 24961.0, "slot_units": 1.0}
                        ],
                    },
                    ensure_ascii=False,
                ),
                "executed_at": "2026-01-06 10:00:00",
                "created_at": "2026-01-06 10:00:00",
            }
        ],
        snapshots=[
            {
                "run_reason": "checkpoint",
                "initial_cash": 50000,
                "available_cash": 25039,
                "market_value": 25440,
                "total_equity": 50479,
                "realized_pnl": 0,
                "unrealized_pnl": 480,
                "created_at": "2026-01-06 15:00:00",
            }
        ],
        positions=[
            {
                "stock_code": "301381",
                "stock_name": "宏工科技",
                "quantity": 1200,
                "avg_price": 20.8,
                "latest_price": 21.2,
                "market_value": 25440,
                "unrealized_pnl": 480,
                "sellable_quantity": 0,
                "locked_quantity": 1200,
            }
        ],
        signals=[],
    )

    client = TestClient(create_app(context=context))
    snapshot = client.get("/api/v1/quant/his-replay").json()
    assert "capitalPool" not in snapshot["tasks"][0]

    payload = client.get(f"/api/v1/quant/his-replay/capital-pool?runId={run_id}").json()

    capital_pool = payload["capitalPool"]
    assert capital_pool["task"]["runId"] == str(run_id)
    assert capital_pool["task"]["status"] == "completed"
    assert capital_pool["pool"]["initialCash"] == "50000.00"
    assert capital_pool["pool"]["cashValue"] == "25039.00"
    assert capital_pool["pool"]["marketValue"] == "25440.00"
    assert capital_pool["pool"]["slotCount"] == 2
    assert capital_pool["pool"]["slotBudget"] == "25000.00"
    assert capital_pool["pool"]["occupiedCash"] == "24961.00"
    assert len(capital_pool["slots"]) == 2
    occupied_slot = capital_pool["slots"][0]
    assert occupied_slot["index"] == 1
    assert occupied_slot["status"] == "occupied"
    assert occupied_slot["occupiedCash"] == "24961.00"
    assert occupied_slot["lots"][0]["stockCode"] == "301381"
    assert occupied_slot["lots"][0]["stockName"] == "宏工科技"
    assert occupied_slot["lots"][0]["lotCount"] == 12
    assert occupied_slot["lots"][0]["quantity"] == 1200
    assert occupied_slot["lots"][0]["lockedQuantity"] == 1200
    assert occupied_slot["lots"][0]["marketValue"] == "25440.00"
    assert occupied_slot["lots"][0]["priceBasis"] == "market"


def test_his_replay_snapshot_adds_terminal_liquidation_summary_and_ranked_rows(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01 09:30:00",
        end_datetime="2026-01-03 15:00:00",
        initial_cash=50000,
        status="completed",
        metadata={
            "selected_strategy_mode": "auto",
            "commission_rate": 0.001,
            "sell_tax_rate": 0.002,
        },
    )
    db.replace_sim_run_results(
        run_id,
        trades=[],
        snapshots=[
            {
                "run_reason": "checkpoint",
                "initial_cash": 50000,
                "available_cash": 49000,
                "market_value": 3000,
                "total_equity": 52000,
                "realized_pnl": 0,
                "unrealized_pnl": 2000,
                "created_at": "2026-01-03 15:00:00",
            }
        ],
        positions=[
            {
                "stock_code": "301381",
                "stock_name": "宏工科技",
                "quantity": 100,
                "avg_price": 10,
                "latest_price": 12,
                "market_value": 1200,
                "unrealized_pnl": 200,
                "sellable_quantity": 100,
                "locked_quantity": 0,
            },
            {
                "stock_code": "300750",
                "stock_name": "宁德时代",
                "quantity": 100,
                "avg_price": 20,
                "latest_price": 18,
                "market_value": 1800,
                "unrealized_pnl": -200,
                "sellable_quantity": 100,
                "locked_quantity": 0,
            },
        ],
        signals=[],
    )
    db.finalize_sim_run(
        run_id,
        status="completed",
        final_equity=52000,
        total_return_pct=4.0,
        max_drawdown_pct=0,
        win_rate=0,
        trade_count=0,
    )

    payload = TestClient(create_app(context=context)).get("/api/v1/quant/his-replay").json()

    task = payload["tasks"][0]
    winning = task["topWinningTrades"]["rows"] if isinstance(task["topWinningTrades"], dict) else task["topWinningTrades"]
    losing = task["topLosingTrades"]["rows"] if isinstance(task["topLosingTrades"], dict) else task["topLosingTrades"]
    assert winning[0]["cells"][1] == "期末清算"
    assert winning[0]["cells"][2] == "301381"
    assert winning[0]["cells"][4] == "196.40"
    assert "期末模拟清仓" in winning[0]["cells"][6]
    assert losing[0]["cells"][1] == "期末清算"
    assert losing[0]["cells"][2] == "300750"
    assert losing[0]["cells"][4] == "-205.40"
    summary_by_label = {item["label"]: item["value"] for item in payload["tradeCostSummary"]}
    assert summary_by_label["清算后现金"] == "51991.00"
    assert summary_by_label["期末清算盈亏"] == "-9.00"
    assert summary_by_label["期末清算费用"] == "9.00"
    assert summary_by_label["清算后总盈亏"] == "1991.00"
    assert summary_by_label["清算后收益率"] == "3.98%"


def test_his_replay_capital_pool_endpoint_rebuilds_lots_at_selected_checkpoint(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01 09:30:00",
        end_datetime="2026-01-03 15:00:00",
        initial_cash=50000,
        status="completed",
        progress_current=3,
        progress_total=3,
        metadata={"selected_strategy_mode": "auto"},
    )
    for checkpoint_at, cash, market_value, total_equity in [
        ("2026-01-01 10:00:00", 47999, 2000, 49999),
        ("2026-01-02 10:00:00", 47999, 2100, 50099),
        ("2026-01-03 10:00:00", 44998, 5200, 50198),
    ]:
        db.add_sim_run_checkpoint(
            run_id,
            checkpoint_at=checkpoint_at,
            candidates_scanned=2,
            positions_checked=1,
            signals_created=1,
            auto_executed=1,
            available_cash=cash,
            market_value=market_value,
            total_equity=total_equity,
            metadata={
                "positions": [
                    {
                        "stock_code": "301381",
                        "stock_name": "宏工科技",
                        "quantity": 100,
                        "avg_price": 20,
                        "latest_price": 21,
                        "market_value": 2100,
                        "unrealized_pnl": 100,
                        "sellable_quantity": 100,
                        "locked_quantity": 0,
                    }
                ]
            }
            if checkpoint_at == "2026-01-02 10:00:00"
            else None,
        )
    db.replace_sim_run_results(
        run_id,
        trades=[
            {
                "signal_id": 7,
                "stock_code": "301381",
                "stock_name": "宏工科技",
                "action": "BUY",
                "price": 20,
                "quantity": 100,
                "gross_amount": 2000,
                "commission_fee": 1,
                "sell_tax_fee": 0,
                "fee_total": 1,
                "net_amount": 2001,
                "amount": 2001,
                "trade_metadata_json": json.dumps(
                    {
                        "side": "BUY",
                        "lot": {
                            "lot_id": "lot-before-checkpoint",
                            "lot_count": 1,
                            "quantity": 100,
                            "remaining_quantity": 100,
                            "entry_price": 20,
                            "unlock_date": "2026-01-02",
                        },
                        "slot_allocations": [{"slot_index": 1, "allocated_cash": 2001, "slot_units": 0.1}],
                    },
                    ensure_ascii=False,
                ),
                "executed_at": "2026-01-01 10:00:00",
                "created_at": "2026-01-01 10:00:00",
            },
            {
                "signal_id": 8,
                "stock_code": "300750",
                "stock_name": "宁德时代",
                "action": "BUY",
                "price": 30,
                "quantity": 100,
                "gross_amount": 3000,
                "commission_fee": 1,
                "sell_tax_fee": 0,
                "fee_total": 1,
                "net_amount": 3001,
                "amount": 3001,
                "trade_metadata_json": json.dumps(
                    {
                        "side": "BUY",
                        "lot": {
                            "lot_id": "future-lot",
                            "lot_count": 1,
                            "quantity": 100,
                            "remaining_quantity": 100,
                            "entry_price": 30,
                            "unlock_date": "2026-01-04",
                        },
                        "slot_allocations": [{"slot_index": 2, "allocated_cash": 3001, "slot_units": 0.12}],
                    },
                    ensure_ascii=False,
                ),
                "executed_at": "2026-01-03 10:00:00",
                "created_at": "2026-01-03 10:00:00",
            },
        ],
        snapshots=[],
        positions=[],
        signals=[],
    )

    response = TestClient(create_app(context=context)).get(
        f"/api/v1/quant/his-replay/capital-pool?runId={run_id}&checkpointPage=1&checkpointPageSize=2&checkpointAt=2026-01-02%2010:00:00"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["runId"] == str(run_id)
    assert payload["selectedCheckpointAt"] == "2026-01-02 10:00:00"
    assert payload["checkpoints"]["pagination"]["totalRows"] == 3
    assert payload["checkpoints"]["pagination"]["totalPages"] == 2
    assert [item["checkpointAt"] for item in payload["checkpoints"]["items"]] == [
        "2026-01-03 10:00:00",
        "2026-01-02 10:00:00",
    ]
    capital_pool = payload["capitalPool"]
    assert capital_pool["task"]["checkpoint"] == "2026-01-02 10:00:00"
    assert capital_pool["pool"]["cashValue"] == "47999.00"
    assert capital_pool["pool"]["marketValue"] == "2100.00"
    visible_lot_codes = [
        lot["stockCode"]
        for slot in capital_pool["slots"]
        for lot in slot["lots"]
    ]
    assert visible_lot_codes == ["301381"]
    assert "300750" not in visible_lot_codes
    visible_lot = next(
        lot
        for slot in capital_pool["slots"]
        for lot in slot["lots"]
        if lot["stockCode"] == "301381"
    )
    assert visible_lot["costBand"] == "20.00"
    assert visible_lot["marketValue"] == "2100.00"
    assert visible_lot["priceBasis"] == "market"


def test_his_replay_snapshot_returns_only_first_page_for_heavy_tables(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2025-12-01 09:30:00",
        end_datetime="2026-01-06 15:00:00",
        initial_cash=100000,
        status="completed",
        metadata={"selected_strategy_mode": "auto"},
    )
    signals = [
        {
            "id": index + 1,
            "stock_code": f"300{index:03d}",
            "stock_name": f"测试{index}",
            "action": "BUY",
            "confidence": 80,
            "reasoning": f"signal {index}",
            "checkpoint_at": f"2026-01-06 10:{index:02d}:00",
            "created_at": f"2026-01-06 10:{index:02d}:00",
        }
        for index in range(25)
    ]
    trades = [
        {
            "signal_id": index + 1,
            "stock_code": f"300{index:03d}",
            "stock_name": f"测试{index}",
            "action": "BUY",
            "price": 10 + index,
            "quantity": 100,
            "amount": (10 + index) * 100,
            "executed_at": f"2026-01-06 10:{index:02d}:30",
            "created_at": f"2026-01-06 10:{index:02d}:30",
        }
        for index in range(25)
    ]
    db.replace_sim_run_results(run_id, trades=trades, snapshots=[], positions=[], signals=signals)

    client = TestClient(create_app(context=context))
    snapshot = client.get("/api/v1/quant/his-replay").json()
    progress = client.get("/api/v1/quant/his-replay/progress").json()

    assert len(snapshot["signals"]["rows"]) == 20
    assert len(snapshot["trades"]["rows"]) == 20
    assert len(progress["signals"]["rows"]) == 20
    assert len(progress["trades"]["rows"]) == 20
    assert snapshot["signals"]["rows"][0]["code"] == "300024"
    assert snapshot["signals"]["rows"][-1]["code"] == "300005"


def test_his_replay_task_metrics_explain_low_win_rate_profitability(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2025-12-01 09:30:00",
        end_datetime="2026-01-06 15:00:00",
        initial_cash=100000,
        status="completed",
        metadata={"selected_strategy_mode": "auto"},
    )
    trades = [
        {
            "signal_id": 1,
            "stock_code": "300001",
            "stock_name": "盈利A",
            "action": "SELL",
            "price": 12,
            "quantity": 100,
            "amount": 1200,
            "realized_pnl": 2000,
            "executed_at": "2026-01-06 10:00:00",
            "created_at": "2026-01-06 10:00:00",
        },
        {
            "signal_id": 2,
            "stock_code": "300002",
            "stock_name": "亏损B",
            "action": "SELL",
            "price": 9,
            "quantity": 100,
            "amount": 900,
            "realized_pnl": -500,
            "executed_at": "2026-01-06 10:30:00",
            "created_at": "2026-01-06 10:30:00",
        },
        {
            "signal_id": 3,
            "stock_code": "300003",
            "stock_name": "买入C",
            "action": "BUY",
            "price": 10,
            "quantity": 100,
            "amount": 1000,
            "realized_pnl": 0,
            "executed_at": "2026-01-06 11:00:00",
            "created_at": "2026-01-06 11:00:00",
        },
    ]
    snapshots = [
        {
            "checkpoint_at": "2026-01-06 15:00:00",
            "available_cash": 70000,
            "market_value": 50000,
            "total_equity": 120000,
            "realized_pnl": 15000,
            "unrealized_pnl": 5000,
            "created_at": "2026-01-06 15:00:00",
        }
    ]
    db.replace_sim_run_results(run_id, trades=trades, snapshots=snapshots, positions=[], signals=[])
    db.finalize_sim_run(
        run_id,
        status="completed",
        final_equity=120000,
        total_return_pct=20,
        max_drawdown_pct=0,
        win_rate=50,
        trade_count=3,
        status_message="完成",
    )

    client = TestClient(create_app(context=context))
    task = client.get("/api/v1/quant/his-replay").json()["tasks"][0]

    assert task["finalEquity"] == "120000"
    assert task["cashValue"] == "70000"
    assert task["marketValue"] == "50000"
    assert task["realizedPnl"] == "15000"
    assert task["unrealizedPnl"] == "5000"
    assert task["sellWinRate"] == "50.00%"
    assert task["winningSellCount"] == 1
    assert task["losingSellCount"] == 1
    assert task["avgWin"] == "2000"
    assert task["avgLoss"] == "-500"
    assert task["payoffRatio"] == "4.00"


def test_his_replay_signal_filters_are_applied_by_database(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2025-12-01 09:30:00",
        end_datetime="2026-01-06 15:00:00",
        initial_cash=100000,
        status="running",
        metadata={"selected_strategy_mode": "auto"},
    )
    hold_signals = [
        {
            "id": index + 1,
            "stock_code": f"300{index:03d}",
            "stock_name": f"测试{index}",
            "action": "HOLD",
            "confidence": 50,
            "reasoning": f"hold {index}",
            "checkpoint_at": f"2026-01-06 10:{index:02d}:00",
            "created_at": f"2026-01-06 10:{index:02d}:00",
        }
        for index in range(25)
    ]
    trade_signals = [
        {
            "id": 101,
            "stock_code": "300684",
            "stock_name": "中石科技",
            "action": "BUY",
            "confidence": 80,
            "reasoning": "older buy",
            "checkpoint_at": "2026-01-05 10:00:00",
            "created_at": "2026-01-05 10:00:00",
        },
        {
            "id": 102,
            "stock_code": "301662",
            "stock_name": "宏工科技",
            "action": "SELL",
            "confidence": 80,
            "reasoning": "older sell",
            "checkpoint_at": "2026-01-05 09:30:00",
            "created_at": "2026-01-05 09:30:00",
        },
    ]
    db.replace_sim_run_results(run_id, trades=[], snapshots=[], positions=[], signals=[*hold_signals, *trade_signals])

    client = TestClient(create_app(context=context))
    unfiltered = client.get("/api/v1/quant/his-replay").json()
    filtered = client.get("/api/v1/quant/his-replay?signalAction=TRADE&signalPageSize=1").json()
    buy_only = client.get("/api/v1/quant/his-replay/progress?signalAction=BUY").json()

    assert {row["cells"][3] for row in unfiltered["signals"]["rows"]} == {"HOLD"}
    assert [row["cells"][3] for row in filtered["signals"]["rows"]] == ["BUY"]
    assert filtered["signals"]["pagination"]["totalRows"] == 2
    assert filtered["signals"]["pagination"]["pageSize"] == 1
    assert filtered["signals"]["pagination"]["totalPages"] == 2
    assert [row["code"] for row in buy_only["signals"]["rows"]] == ["300684"]
    assert buy_only["signals"]["pagination"]["totalRows"] == 1


def test_his_replay_snapshot_marks_completed_stale_run_with_missing_trades_as_failed(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2025-12-01 09:30:00",
        end_datetime="2026-01-06 15:00:00",
        initial_cash=50000,
        status="running",
        metadata={"selected_strategy_mode": "auto"},
    )
    db.set_sim_run_worker_pid(run_id, 99999999)
    db.update_sim_run_progress(
        run_id,
        progress_current=10,
        progress_total=10,
        latest_checkpoint_at="2026-01-06 15:00:00",
        status_message="已完成第 10/10 个检查点",
    )
    db.add_sim_run_checkpoint(
        run_id,
        checkpoint_at="2026-01-06 15:00:00",
        candidates_scanned=2,
        positions_checked=1,
        signals_created=2,
        auto_executed=1,
        available_cash=49000,
        market_value=2000,
        total_equity=51000,
    )
    db.upsert_sim_run_signals(
        run_id,
        [
            {
                "id": 101,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "confidence": 82,
                "reasoning": "已产生交易信号但成交未汇总",
                "checkpoint_at": "2026-01-06 15:00:00",
            }
        ],
    )

    client = TestClient(create_app(context=context))
    payload = client.get("/api/v1/quant/his-replay").json()

    task = payload["tasks"][0]
    assert task["runId"] == str(run_id)
    assert task["status"] == "failed"
    assert "最终成交汇总未落库" in task["stage"]
    assert task["finalEquity"] == "51000"
    assert task["tradeCount"] == "0"


def test_his_replay_start_returns_400_when_active_replay_exists(tmp_path):
    context = _make_context(tmp_path)
    db = context.quant_db()
    db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-10 15:00:00",
        initial_cash=100000,
        status="running",
        metadata={"selected_strategy_mode": "auto"},
    )

    client = TestClient(create_app(context=context))
    response = client.post("/api/v1/quant/his-replay/actions/start", json={})

    assert response.status_code == 400
    assert "已有回放任务运行中" in response.json()["detail"]


def test_portfolio_actions_call_scheduler_and_manager(tmp_path, monkeypatch):
    context = _make_context(tmp_path)
    fake_scheduler = FakePortfolioScheduler()
    fake_manager = FakePortfolioManager()

    monkeypatch.setattr(UIApiContext, "portfolio_scheduler", lambda self: fake_scheduler, raising=False)
    monkeypatch.setattr(UIApiContext, "portfolio_manager", lambda self: fake_manager, raising=False)

    client = TestClient(create_app(context=context))

    analyze_resp = client.post("/api/v1/portfolio/actions/analyze", json={"code": "600519"})
    assert analyze_resp.status_code == 200
    assert fake_manager.analyzed == ["600519"]

    refresh_resp = client.post("/api/v1/portfolio/actions/refresh-portfolio", json={})
    assert refresh_resp.status_code == 200
    assert ("run_now", None) in fake_scheduler.calls

    save_resp = client.post("/api/v1/portfolio/actions/schedule-save", json={"analysis_mode": "parallel"})
    assert save_resp.status_code == 200
    assert any(call[0] == "update" for call in fake_scheduler.calls)

    start_resp = client.post("/api/v1/portfolio/actions/schedule-start", json={})
    stop_resp = client.post("/api/v1/portfolio/actions/schedule-stop", json={})
    assert start_resp.status_code == 200
    assert stop_resp.status_code == 200
    assert ("start", None) in fake_scheduler.calls
    assert ("stop", None) in fake_scheduler.calls


def test_ai_monitor_actions_use_engine_and_delete_rows(tmp_path, monkeypatch):
    context = _make_context(tmp_path)
    db = context.smart_monitor_db()
    task_id = db.add_monitor_task(
        {
            "task_name": "贵州茅台盯盘",
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "enabled": 1,
            "check_interval": 300,
        }
    )
    fake_engine = FakeSmartMonitorEngine()
    monkeypatch.setattr(UIApiContext, "smart_monitor_engine", lambda self: fake_engine, raising=False)

    client = TestClient(create_app(context=context))

    start_resp = client.post("/api/v1/monitor/ai/actions/start", json={"id": "600519"})
    analyze_resp = client.post("/api/v1/monitor/ai/actions/analyze", json={"id": "600519"})
    stop_resp = client.post("/api/v1/monitor/ai/actions/stop", json={"id": "600519"})
    assert start_resp.status_code == 200
    assert analyze_resp.status_code == 200
    assert stop_resp.status_code == 200
    assert fake_engine.calls[:3] == [("start", "600519"), ("analyze", "600519"), ("stop", "600519")]

    delete_resp = client.post("/api/v1/monitor/ai/actions/delete", json={"id": "600519"})
    assert delete_resp.status_code == 200
    assert not context.smart_monitor_db().get_monitor_tasks(enabled_only=False)


def test_real_monitor_actions_use_scheduler_and_rule_updates(tmp_path, monkeypatch):
    context = _make_context(tmp_path)
    stock_id = context.monitor_db().add_monitored_stock(
        symbol="600519",
        name="贵州茅台",
        rating="重点跟踪",
        entry_range={"low": 1400, "high": 1500, "note": "原始说明"},
        take_profit=1600,
        stop_loss=1380,
        check_interval=30,
        notification_enabled=True,
    )
    fake_scheduler = FakeRealMonitorScheduler()
    monkeypatch.setattr(UIApiContext, "real_monitor_scheduler", lambda self: fake_scheduler, raising=False)

    client = TestClient(create_app(context=context))

    start_resp = client.post("/api/v1/monitor/real/actions/start", json={})
    stop_resp = client.post("/api/v1/monitor/real/actions/stop", json={})
    refresh_resp = client.post("/api/v1/monitor/real/actions/refresh", json={})
    assert start_resp.status_code == 200
    assert stop_resp.status_code == 200
    assert refresh_resp.status_code == 200
    assert fake_scheduler.calls == ["start", "stop"]

    update_resp = client.post(
        "/api/v1/monitor/real/actions/update-rule",
        json={"index": 0, "title": "高优先级关注", "body": "新的规则说明", "tone": "warning"},
    )
    assert update_resp.status_code == 200
    stock = context.monitor_db().get_stock_by_id(stock_id)
    assert stock is not None
    assert stock["rating"] == "高优先级关注"
    assert stock["entry_range"]["note"] == "新的规则说明"

    delete_resp = client.post("/api/v1/monitor/real/actions/delete-rule", json={"index": 0, "title": "高优先级关注"})
    assert delete_resp.status_code == 200
    assert context.monitor_db().get_monitored_stocks() == []

