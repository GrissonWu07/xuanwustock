from __future__ import annotations

from pathlib import Path
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
        lambda symbol, period, enabled_analysts_config=None, selected_model=None: {
            "success": True,
            "symbol": symbol,
            "stock_info": {"name": "贵州茅台", "current_price": 1453.96},
            "indicators": {"RSI": 53.79, "MA20": 1441.86, "量比": 1.13, "MACD": 6.2792},
            "final_decision": {"decision": "偏多看待，等待回踩再介入", "reasoning": "趋势与资金共振"},
            "discussion_result": {"summary": "多位分析师认为趋势与资金面偏强，但不建议追高。"},
            "agents_results": {
                "technical": {"summary": "趋势向上，均线多头。"},
                "fundamental": {"summary": "基本面稳定，估值仍可接受。"},
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

    client = TestClient(create_app(context=context))

    single = client.post(
        "/api/ui/workbench/actions/analysis",
        json={"stockCode": "600519", "analysts": ["technical", "fundamental"], "cycle": "1y", "mode": "单个分析"},
    )
    assert single.status_code == 200
    analysis = single.json()["analysis"]
    assert analysis["symbol"] == "600519"
    assert "贵州茅台" in analysis["summaryTitle"]
    assert "多位分析师" in analysis["summaryBody"]
    assert analysis["indicators"]
    assert "偏多" in analysis["decision"]

    batch = client.post(
        "/api/ui/workbench/actions/analysis-batch",
        json={"stockCodes": ["600519", "600519"], "analysts": ["technical"], "cycle": "1y", "mode": "批量分析"},
    )
    assert batch.status_code == 200
    batch_analysis = batch.json()["analysis"]
    assert batch_analysis["mode"] == "批量分析"
    assert "批量" in batch_analysis["summaryTitle"]
    assert "2" in batch_analysis["summaryBody"] or "两" in batch_analysis["summaryBody"]


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

    response = client.get("/api/ui/discover")
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

    response = client.post("/api/ui/discover/actions/run-strategy", json={})
    assert response.status_code == 200
    payload = response.json()
    codes = {row["code"] for row in payload["candidateTable"]["rows"]}
    assert {"688111", "000001", "300750", "600519", "600036"}.issubset(codes)

    persisted = client.get("/api/ui/discover")
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

    save_resp = client.post("/api/ui/quant/live-sim/actions/save", json={"strategyMode": "defensive"})
    assert save_resp.status_code == 200
    assert any(call[0] == "update_config" for call in fake_scheduler.calls)

    start_resp = client.post("/api/ui/quant/live-sim/actions/start", json={})
    assert start_resp.status_code == 200
    assert start_resp.json()["status"]["running"] == "运行中"

    run_resp = client.post("/api/ui/quant/live-sim/actions/bulk-quant", json={"codes": ["600519", "000001"]})
    assert run_resp.status_code == 200
    assert ("run_once", "ui_manual_run") in fake_scheduler.calls

    analyze_resp = client.post("/api/ui/quant/live-sim/actions/analyze-candidate", json="600519")
    assert analyze_resp.status_code == 200
    assert analyzed_codes == ["600519"]

    delete_resp = client.post("/api/ui/quant/live-sim/actions/delete-candidate", json={"code": "000001"})
    assert delete_resp.status_code == 200
    deleted_rows = delete_resp.json()["candidatePool"]["rows"]
    assert {row["id"] for row in deleted_rows} == {"600519"}

    reset_resp = client.post("/api/ui/quant/live-sim/actions/reset", json={"initialCash": 20000})
    assert reset_resp.status_code == 200

    stop_resp = client.post("/api/ui/quant/live-sim/actions/stop", json={})
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

    client = TestClient(create_app(context=context))

    start_resp = client.post("/api/ui/quant/his-replay/actions/start", json={})
    assert start_resp.status_code == 200
    assert fake_replay.calls and fake_replay.calls[0][0] == "historical"

    continue_resp = client.post("/api/ui/quant/his-replay/actions/continue", json={})
    assert continue_resp.status_code == 200
    assert fake_replay.calls[-1][0] == "past_to_live"

    cancel_resp = client.post("/api/ui/quant/his-replay/actions/cancel", json={"id": run_id})
    assert cancel_resp.status_code == 200
    latest_run = context.quant_db().get_sim_runs(limit=1)[0]
    assert latest_run["status"] in {"cancel_requested", "cancelled", "completed"}

    history_resp = client.post("/api/ui/history/actions/rerun", json={})
    assert history_resp.status_code == 200
    assert fake_replay.calls[-1][0] == "historical"

    delete_resp = client.post("/api/ui/quant/his-replay/actions/delete", json={"id": run_id})
    assert delete_resp.status_code == 200
    assert all(int(item["id"]) != run_id for item in context.quant_db().get_sim_runs(limit=20))


def test_portfolio_actions_call_scheduler_and_manager(tmp_path, monkeypatch):
    context = _make_context(tmp_path)
    fake_scheduler = FakePortfolioScheduler()
    fake_manager = FakePortfolioManager()

    monkeypatch.setattr(UIApiContext, "portfolio_scheduler", lambda self: fake_scheduler, raising=False)
    monkeypatch.setattr(UIApiContext, "portfolio_manager", lambda self: fake_manager, raising=False)

    client = TestClient(create_app(context=context))

    analyze_resp = client.post("/api/ui/portfolio/actions/analyze", json={"code": "600519"})
    assert analyze_resp.status_code == 200
    assert fake_manager.analyzed == ["600519"]

    refresh_resp = client.post("/api/ui/portfolio/actions/refresh-portfolio", json={})
    assert refresh_resp.status_code == 200
    assert ("run_now", None) in fake_scheduler.calls

    save_resp = client.post("/api/ui/portfolio/actions/schedule-save", json={"analysis_mode": "parallel"})
    assert save_resp.status_code == 200
    assert any(call[0] == "update" for call in fake_scheduler.calls)

    start_resp = client.post("/api/ui/portfolio/actions/schedule-start", json={})
    stop_resp = client.post("/api/ui/portfolio/actions/schedule-stop", json={})
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

    start_resp = client.post("/api/ui/monitor/ai/actions/start", json={"id": "600519"})
    analyze_resp = client.post("/api/ui/monitor/ai/actions/analyze", json={"id": "600519"})
    stop_resp = client.post("/api/ui/monitor/ai/actions/stop", json={"id": "600519"})
    assert start_resp.status_code == 200
    assert analyze_resp.status_code == 200
    assert stop_resp.status_code == 200
    assert fake_engine.calls[:3] == [("start", "600519"), ("analyze", "600519"), ("stop", "600519")]

    delete_resp = client.post("/api/ui/monitor/ai/actions/delete", json={"id": "600519"})
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

    start_resp = client.post("/api/ui/monitor/real/actions/start", json={})
    stop_resp = client.post("/api/ui/monitor/real/actions/stop", json={})
    refresh_resp = client.post("/api/ui/monitor/real/actions/refresh", json={})
    assert start_resp.status_code == 200
    assert stop_resp.status_code == 200
    assert refresh_resp.status_code == 200
    assert fake_scheduler.calls == ["start", "stop"]

    update_resp = client.post(
        "/api/ui/monitor/real/actions/update-rule",
        json={"index": 0, "title": "高优先级关注", "body": "新的规则说明", "tone": "warning"},
    )
    assert update_resp.status_code == 200
    stock = context.monitor_db().get_stock_by_id(stock_id)
    assert stock is not None
    assert stock["rating"] == "高优先级关注"
    assert stock["entry_range"]["note"] == "新的规则说明"

    delete_resp = client.post("/api/ui/monitor/real/actions/delete-rule", json={"index": 0, "title": "高优先级关注"})
    assert delete_resp.status_code == 200
    assert context.monitor_db().get_monitored_stocks() == []
