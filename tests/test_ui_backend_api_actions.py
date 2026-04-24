from __future__ import annotations

from pathlib import Path
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

    start_resp = client.post("/api/v1/quant/his-replay/actions/start", json={})
    assert start_resp.status_code == 200
    assert fake_replay.calls and fake_replay.calls[0][0] == "historical"

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

