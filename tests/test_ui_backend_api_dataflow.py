from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

import app.gateway_api as gateway_api
from app.notification_service import notification_service
from app.selector_result_store import save_latest_result


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_API_PATH = PROJECT_ROOT / "app" / "gateway.py"


def _load_backend_api_module():
    spec = importlib.util.spec_from_file_location("build_backend_api_flow", BACKEND_API_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_main_force_result(base_dir: Path) -> None:
    payload = {
        "result": {
            "success": True,
            "total_stocks": 2,
            "filtered_stocks": 2,
            "final_recommendations": [
                {
                    "rank": 1,
                    "symbol": "600519.SH",
                    "name": "贵州茅台",
                    "reasons": ["资金流入明显", "行业龙头", "基本面稳健"],
                    "highlights": "高质量核心资产",
                    "risks": "估值偏高",
                    "position": "20%",
                    "investment_period": "中长期",
                    "stock_data": {
                        "股票代码": "600519",
                        "股票简称": "贵州茅台",
                        "最新价": "1453.96",
                        "所属同花顺行业": "食品饮料-白酒",
                        "总市值[20260410]": 18200.0,
                        "市盈率(pe)[20260410]": 26.1,
                        "市净率(pb)[20260410]": 9.8,
                        "区间主力资金流向[20260112-20260410]": 12345678.0,
                        "code": "600519",
                    },
                },
            ],
        },
        "selected_at": "2026-04-13 10:00:00",
        "analyzer_state": {},
    }
    save_latest_result("main_force", payload, base_dir=base_dir)


def _seed_research_result(base_dir: Path) -> None:
    payload = {
        "modules": [
            {"name": "智策板块", "note": "板块轮动向上", "output": "600519"},
            {"name": "新闻流量", "note": "高关注", "output": "000001"},
        ],
        "marketView": [
            {"title": "市场情绪", "body": "震荡偏稳", "tone": "neutral"},
            {"title": "风险提示", "body": "短线波动仍需控制仓位", "tone": "warning"},
        ],
        "outputTable": {
            "columns": ["代码", "名称", "来源", "理由"],
            "rows": [
                {
                    "id": "600519",
                    "cells": ["600519", "贵州茅台", "智策板块", "板块轮动向上"],
                    "actions": [{"label": "加入我的关注", "icon": "⭐", "tone": "accent"}],
                    "code": "600519",
                    "name": "贵州茅台",
                    "source": "智策板块",
                    "latestPrice": "1453.96",
                }
            ],
            "emptyLabel": "暂无股票输出",
        },
        "summary": {
            "title": "研究结论：关注龙头与情绪共振",
            "body": "研究模块输出股票后，可以直接加入我的关注，再进入量化候选池。",
        },
        "updatedAt": "2026-04-13 10:00:00",
    }
    save_latest_result("research", payload, base_dir=base_dir)


def _seed_simple_selector_result(base_dir: Path, strategy_key: str, rows: list[dict[str, object]], selected_at: str) -> None:
    save_latest_result(
        strategy_key,
        {
            "stocks_df": pd.DataFrame(rows),
            "selected_at": selected_at,
        },
        base_dir=base_dir,
    )


def _make_context(tmp_path: Path):
    return gateway_api.UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        watchlist_db_file=tmp_path / "watchlist.db",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        portfolio_db_file=tmp_path / "portfolio_stocks.db",
        monitor_db_file=tmp_path / "stock_monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
        stock_name_resolver=lambda code: {"600519": "贵州茅台", "000001": "平安银行", "300750": "宁德时代"}.get(code, code),
        quote_fetcher=lambda code, market=None: {
            "stock_code": code,
            "stock_name": {"600519": "贵州茅台", "000001": "平安银行", "300750": "宁德时代"}.get(code, code),
            "latest_price": {"600519": 1453.96, "000001": 10.12, "300750": 198.35}.get(code, 1.0),
        },
    )


def _seed_structured_signal_for_detail(context: gateway_api.UIApiContext) -> int:
    db = context.quant_db()
    db.update_scheduler_config(
        strategy_profile_id="aggressive",
        ai_dynamic_strategy="hybrid",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
    )

    explainability = {
        "technical_breakdown": {
            "track": {"score": 0.036346, "confidence": 0.607384, "available": True, "track_unavailable": False},
            "groups": [
                {"id": "trend", "score": 0.03802, "coverage": 0.8, "weight_raw": 1.0, "weight_norm_in_track": 0.25, "track_contribution": 0.03802},
                {"id": "momentum", "score": 0.061856, "coverage": 0.85, "weight_raw": 0.9, "weight_norm_in_track": 0.25, "track_contribution": 0.061856},
                {"id": "volume_confirmation", "score": 0.149914, "coverage": 0.6, "weight_raw": 0.8, "weight_norm_in_track": 0.25, "track_contribution": 0.149914},
                {"id": "volatility_risk", "score": -0.213443, "coverage": 0.5, "weight_raw": 1.2, "weight_norm_in_track": 0.25, "track_contribution": -0.213443},
            ],
            "dimensions": [
                {"id": "trend_direction", "group": "trend", "score": 1.0, "track_contribution": 0.0884, "reason": "close/ma20/ma60=106.62/88.0055/79.915333"},
                {"id": "price_vs_ma20", "group": "trend", "score": 1.0, "track_contribution": 0.0752, "reason": "price above ma20"},
                {"id": "macd_level", "group": "momentum", "score": 0.7, "track_contribution": 0.059, "reason": "dif/dea/hist=3.718454/0/3.718454"},
                {"id": "rsi_zone", "group": "momentum", "score": -0.2, "track_contribution": -0.0235, "reason": "rsi14=88.013095"},
                {"id": "kdj_cross", "group": "momentum", "score": 0.0, "track_contribution": 0.0, "reason": "k/d/j=40.665798/54.474382/13.048628"},
                {"id": "volume_ratio", "group": "volume_confirmation", "score": 0.5, "track_contribution": 0.0428, "reason": "volume_ratio=1.1948"},
                {"id": "boll_position", "group": "volatility_risk", "score": -0.6, "track_contribution": -0.213443, "reason": "boll_position=0.961796"},
            ],
        },
        "context_breakdown": {
            "track": {"score": 0.033122, "confidence": 0.706667, "available": True, "track_unavailable": False},
            "groups": [
                {"id": "market_structure", "score": 0.014812, "coverage": 1.0, "weight_raw": 1.0, "weight_norm_in_track": 0.25, "track_contribution": 0.014812},
                {"id": "risk_account", "score": -0.034901, "coverage": 0.52, "weight_raw": 1.3, "weight_norm_in_track": 0.25, "track_contribution": -0.034901},
                {"id": "tradability_timing", "score": 0.012252, "coverage": 1.0, "weight_raw": 0.8, "weight_norm_in_track": 0.25, "track_contribution": 0.012252},
                {"id": "source_execution", "score": 0.040959, "coverage": 0.4, "weight_raw": 1.1, "weight_norm_in_track": 0.25, "track_contribution": 0.040959},
            ],
            "dimensions": [
                {"id": "price_structure", "group": "market_structure", "score": 0.14, "track_contribution": 0.012252, "reason": "bull stack"},
                {"id": "risk_balance", "group": "risk_account", "score": -0.08, "track_contribution": -0.034901, "reason": "risk high"},
                {"id": "source_prior", "group": "source_execution", "score": 0.28, "track_contribution": 0.040959, "reason": "source prior"},
            ],
        },
        "fusion_breakdown": {
            "mode": "hybrid",
            "tech_score": 0.036346,
            "context_score": 0.033122,
            "tech_confidence": 0.607384,
            "context_confidence": 0.706667,
            "fusion_score": 0.034331,
            "fusion_confidence": 0.668627,
            "fusion_confidence_base": 0.669436,
            "buy_threshold_base": 0.82,
            "buy_threshold_eff": 0.8773,
            "sell_threshold_base": -0.12,
            "sell_threshold_eff": -0.1562,
            "weighted_threshold_action": "HOLD",
            "weighted_action_raw": "HOLD",
            "weighted_gate_fail_reasons": [],
            "core_rule_action": "HOLD",
            "final_action": "HOLD",
            "tech_weight_raw": 0.75,
            "tech_weight_norm": 0.375,
            "context_weight_raw": 1.25,
            "context_weight_norm": 0.625,
            "divergence": 0.001612,
            "divergence_penalty": 0.001209,
            "sign_conflict": 0,
            "sell_precedence_gate": 0.2,
            "threshold_mode": "strict",
            "veto_source_mode": "structured",
        },
        "dual_track": {
            "rule_hit": "neutral_hold",
            "resonance_type": "neutral",
            "final_reason": "技术评分 0.11，上下文评分 0.48。",
        },
        "decision_path": [
            {"step": "veto_first", "matched": "false", "detail": "no_veto"},
            {"step": "mode", "matched": "hybrid", "detail": "hybrid_matrix"},
        ],
        "vetoes": [],
    }
    strategy_profile = {
        "analysis_timeframe": "30m",
        "strategy_mode": "auto",
        "market_regime": {"label": "牛市"},
        "fundamental_quality": {"label": "中性"},
        "risk_style": {"label": "稳重"},
        "auto_inferred_risk_style": {"label": "稳重"},
        "selected_strategy_profile": {"id": "conservative", "name": "保守 (conservative)", "version": "2"},
        "dual_track": {
            "min_fusion_confidence": 0.62,
            "min_tech_score_for_buy": 0.08,
            "min_context_score_for_buy": 0.10,
            "min_tech_confidence_for_buy": 0.58,
            "min_context_confidence_for_buy": 0.62,
        },
        "effective_thresholds": {
            "buy_threshold": 0.8773,
            "sell_threshold": -0.1562,
            "max_position_ratio": 0.5,
            "allow_pyramiding": False,
            "confirmation": "30分钟信号确认",
        },
        "analysis": "旧自然语言摘要：技术评分 0.11，上下文评分 0.48。",
        "decision_reason": "旧自然语言摘要：技术评分 0.11，上下文评分 0.48。",
        "dynamic_strategy": {
            "mode": "hybrid",
            "enabled": True,
            "as_of": "2026-04-24 10:30:00",
            "score": 0.34,
            "confidence": 0.82,
            "overlay_regime": "risk_on",
            "template_switch_applied": True,
            "template_switch_reason": "strong_opposite_signal",
            "adjustments": [
                {
                    "path": "base.dual_track.track_weights.tech",
                    "before": 1.0,
                    "after": 1.11,
                    "delta": 0.11,
                    "reason": "risk_on 技术轨权重上调",
                },
                {
                    "path": "profiles.candidate.dual_track.fusion_buy_threshold",
                    "before": 0.43,
                    "after": 0.39,
                    "delta": -0.04,
                    "reason": "risk_on 降低 BUY 触发阈值",
                },
                {
                    "path": "profiles.candidate.dual_track.fusion_sell_threshold",
                    "before": -0.26,
                    "after": -0.28,
                    "delta": -0.02,
                    "reason": "risk_on 延后 SELL 触发",
                },
                {
                    "path": "profiles.candidate.dual_track.sell_precedence_gate",
                    "before": -0.34,
                    "after": -0.38,
                    "delta": -0.04,
                    "reason": "risk_on 提高强卖覆盖门槛",
                },
            ],
            "components": [
                {
                    "key": "market",
                    "score": 0.44,
                    "confidence": 0.8,
                    "as_of": "2026-04-24 10:00:00",
                    "reason": "market_overview(3)",
                }
            ],
            "omitted_components": [
                {
                    "key": "news",
                    "reason": "no_historical_asof_data",
                    "as_of": "2026-04-24 10:30:00",
                }
            ],
        },
        "explainability": explainability,
    }
    return db.add_signal(
        {
            "stock_code": "002463",
            "stock_name": "沪电股份",
            "action": "HOLD",
            "confidence": 66,
            "reasoning": "旧自然语言摘要：技术评分 0.11，上下文评分 0.48。",
            "status": "observed",
            "position_size_pct": 0.0,
            "decision_type": "dual_track_weighted_hold",
            "tech_score": 0.11,
            "context_score": 0.48,
            "strategy_profile": strategy_profile,
        }
    )


def test_backend_api_dataflow_from_discover_and_research_to_watchlist_and_quant_pool(tmp_path):
    module = _load_backend_api_module()
    selector_dir = tmp_path / "selector_results"
    selector_dir.mkdir(parents=True, exist_ok=True)
    _seed_main_force_result(selector_dir)
    _seed_research_result(selector_dir)

    context = module.UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=selector_dir,
        watchlist_db_file=tmp_path / "watchlist.db",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        portfolio_db_file=tmp_path / "portfolio_stocks.db",
        monitor_db_file=tmp_path / "stock_monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
        stock_name_resolver=lambda code: {"600519": "贵州茅台", "000001": "平安银行"}.get(code, code),
        quote_fetcher=lambda code, market=None: {
            "stock_code": code,
            "stock_name": {"600519": "贵州茅台", "000001": "平安银行"}.get(code, code),
            "latest_price": {"600519": 1453.96, "000001": 10.12}.get(code, 1.0),
        },
    )
    app = module.create_app(context=context)
    client = TestClient(app)

    discover = client.get("/api/v1/discover").json()
    assert discover["candidateTable"]["rows"]
    assert discover["candidateTable"]["rows"][0]["code"] == "600519"
    assert "贵州茅台" in discover["recommendation"]["body"]
    assert any("主力选股" in chip for chip in discover["recommendation"]["chips"])

    research = client.get("/api/v1/research").json()
    assert research["outputTable"]["rows"]
    assert research["outputTable"]["rows"][0]["code"] == "600519"

    add_watchlist = client.post("/api/v1/discover/actions/item-watchlist", json={"code": "600519"})
    assert add_watchlist.status_code == 200
    workbench = client.get("/api/v1/workbench").json()
    watchlist_codes = {row["code"] for row in workbench["watchlist"]["rows"]}
    assert "600519" in watchlist_codes

    add_from_research = client.post("/api/v1/research/actions/item-watchlist", json={"code": "000001"})
    assert add_from_research.status_code == 200
    workbench = client.get("/api/v1/workbench").json()
    watchlist_codes = {row["code"] for row in workbench["watchlist"]["rows"]}
    assert {"600519", "000001"}.issubset(watchlist_codes)

    batch_quant = client.post("/api/v1/workbench/actions/batch-quant", json={"codes": ["600519", "000001"]})
    assert batch_quant.status_code == 200
    live_sim = client.get("/api/v1/quant/live-sim").json()
    candidate_codes = {row["code"] for row in live_sim["candidatePool"]["rows"]}
    assert {"600519", "000001"}.issubset(candidate_codes)

    replay = client.get("/api/v1/quant/his-replay").json()
    assert replay["candidatePool"]["columns"] == ["股票代码", "股票名称", "最新价格"]
    for row in replay["candidatePool"]["rows"]:
        assert "actions" not in row or not row["actions"]


def test_workbench_watchlist_updates_immediately_after_discover_and_research_watchlist_actions(tmp_path):
    module = _load_backend_api_module()
    selector_dir = tmp_path / "selector_results"
    selector_dir.mkdir(parents=True, exist_ok=True)
    _seed_main_force_result(selector_dir)
    _seed_research_result(selector_dir)

    context = module.UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=selector_dir,
        watchlist_db_file=tmp_path / "watchlist.db",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        portfolio_db_file=tmp_path / "portfolio_stocks.db",
        monitor_db_file=tmp_path / "stock_monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
        stock_name_resolver=lambda code: {"600519": "贵州茅台", "000001": "平安银行"}.get(code, code),
        quote_fetcher=lambda code, market=None: {
            "stock_code": code,
            "stock_name": {"600519": "贵州茅台", "000001": "平安银行"}.get(code, code),
            "latest_price": {"600519": 1453.96, "000001": 10.12}.get(code, 1.0),
        },
    )
    app = module.create_app(context=context)
    client = TestClient(app)

    discover_add = client.post("/api/v1/discover/actions/item-watchlist", json={"code": "600519"})
    assert discover_add.status_code == 200
    workbench_after_discover = client.get("/api/v1/workbench")
    assert workbench_after_discover.status_code == 200
    discover_rows = workbench_after_discover.json()["watchlist"]["rows"]
    assert any(row["code"] == "600519" and row["name"] == "贵州茅台" for row in discover_rows)

    research_add = client.post("/api/v1/research/actions/item-watchlist", json={"code": "000001"})
    assert research_add.status_code == 200
    workbench_after_research = client.get("/api/v1/workbench")
    assert workbench_after_research.status_code == 200
    research_rows = workbench_after_research.json()["watchlist"]["rows"]
    assert any(row["code"] == "600519" for row in research_rows)
    assert any(row["code"] == "000001" and row["name"] == "平安银行" for row in research_rows)


def test_signal_detail_prefers_canonical_breakdown_and_clean_audit_labels(tmp_path):
    context = _make_context(tmp_path)
    signal_id = _seed_structured_signal_for_detail(context)
    client = TestClient(gateway_api.create_app(context=context))

    response = client.get(f"/api/v1/quant/signals/{signal_id}?source=live")

    assert response.status_code == 200
    payload = response.json()
    rows = {row["name"]: row for row in payload["parameterDetails"]}
    basis_lines = payload["explanation"]["basis"]

    assert payload["decision"]["techScore"] == "0.036346"
    assert payload["decision"]["contextScore"] == "0.033122"
    assert rows["环境分"]["value"] == "0.033122"
    assert rows["环境轨置信度"]["value"] == "0.706667"
    assert rows["技术轨方向"]["value"] == "偏多"
    assert rows["环境轨方向"]["value"] == "偏多"
    assert rows["仓位建议"]["value"] == "不变"
    assert rows["阈值.min_fusion_confidence"]["value"] == "0.62"
    assert rows["阈值.min_tech_score_for_buy"]["value"] == "0.08"
    assert rows["阈值.min_context_score_for_buy"]["value"] == "0.1"
    assert rows["AI动态调整模式"]["value"] == "hybrid"
    assert rows["AI动态档位"]["value"] == "risk_on"
    assert rows["AI动态评分"]["value"] == "0.34 / 0.82"
    assert rows["AI动态as_of"]["value"] == "2026-04-24 10:30:00"
    assert rows["AI动态使用组件.market"]["value"] == "score=0.44 / confidence=0.8 / as_of=2026-04-24 10:00:00"
    assert rows["AI动态省略组件.news"]["value"] == "no_historical_asof_data @ 2026-04-24 10:30:00"
    assert rows["AI动态调整.fusion_buy_threshold"]["value"] == "0.4300 -> 0.3900 (Δ-0.0400)"
    assert rows["AI动态调整.fusion_sell_threshold"]["value"] == "-0.2600 -> -0.2800 (Δ-0.0200)"
    assert rows["AI动态调整.sell_precedence_gate"]["value"] == "-0.3400 -> -0.3800 (Δ-0.0400)"
    assert rows["AI动态调整.track_weights.tech"]["value"] == "1.0000 -> 1.1100 (Δ+0.1100)"
    assert rows["双轨融合模式"]["value"] == "hybrid"
    assert "兼容派生" in rows["规则命中（兼容派生）"]["name"]
    assert "兼容派生" in rows["共振类型（兼容派生）"]["name"]
    assert not any("最终理由:" in line for line in basis_lines)
    assert not any("技术评分 0.11" in line for line in basis_lines)

    technical_rows = {row["name"]: row for row in payload["technicalIndicators"]}
    assert technical_rows["当前价"]["value"] == "106.62"
    assert technical_rows["DIF"]["value"] == "3.718454"
    assert technical_rows["DEA"]["value"] == "0"
    assert technical_rows["RSI12"]["value"] == "88.013095"
    assert technical_rows["KDJ-K"]["value"] == "40.665798"
    assert technical_rows["KDJ-D"]["value"] == "54.474382"
    assert technical_rows["KDJ-J"]["value"] == "13.048628"
    assert technical_rows["量比"]["value"] == "1.1948"


def test_signal_detail_exposes_position_add_gate_and_execution_delta(tmp_path):
    context = _make_context(tmp_path)
    _seed_structured_signal_for_detail(context)
    db = context.quant_db()
    base_signal = db.get_signals(stock_code="002463", limit=1)[0]
    strategy_profile = base_signal["strategy_profile"]
    fusion_breakdown = strategy_profile["explainability"]["fusion_breakdown"]
    fusion_breakdown.update(
        {
            "final_action": "BUY",
            "core_rule_action": "BUY",
            "weighted_threshold_action": "BUY",
            "weighted_action_raw": "BUY",
        }
    )
    strategy_profile["execution_intent"] = "position_add"
    strategy_profile["position_add_gate"] = {
        "intent": "position_add",
        "status": "passed",
        "current_position_pct": 5.2,
        "target_position_pct": 20.0,
        "add_position_delta_pct": 14.8,
        "max_position_pct": 30.0,
        "min_unrealized_pnl_pct": 2.0,
        "min_tech_score": 0.25,
        "reasons": ["已有浮盈 4.00% >= 2.00%"],
    }
    signal_id = db.add_signal(
        {
            "stock_code": "002463",
            "stock_name": "沪电股份",
            "action": "BUY",
            "confidence": 86,
            "reasoning": "持仓加仓门控通过",
            "status": "pending",
            "position_size_pct": 14.8,
            "decision_type": "position_add",
            "tech_score": 0.32,
            "context_score": 0.12,
            "strategy_profile": strategy_profile,
        }
    )
    client = TestClient(gateway_api.create_app(context=context))

    response = client.get(f"/api/v1/quant/signals/{signal_id}?source=live")

    assert response.status_code == 200
    payload = response.json()
    rows = {row["name"]: row for row in payload["parameterDetails"]}

    assert payload["decision"]["executionIntent"] == "position_add"
    assert rows["执行语义"]["value"] == "加仓/增持"
    assert rows["加仓门控"]["value"] == "通过"
    assert rows["当前持仓比例(%)"]["value"] == "5.2"
    assert rows["目标持仓比例(%)"]["value"] == "20.0"
    assert rows["建议加仓比例(%)"]["value"] == "14.8"
    assert rows["加仓门控理由"]["value"] == "已有浮盈 4.00% >= 2.00%"


def test_replay_signal_detail_enriches_missing_market_snapshot_from_checkpoint_provider():
    class FakeProvider:
        def __init__(self):
            self.prepared = None

        def prepare(self, stock_codes, start_datetime, end_datetime, timeframe):
            self.prepared = (stock_codes, start_datetime, end_datetime, timeframe)

        def get_snapshot(self, stock_code, checkpoint, timeframe, *, stock_name=None):
            return {
                "current_price": 36.63,
                "open": 36.1,
                "high": 37.2,
                "low": 35.8,
                "volume": 123456,
                "amount": 4567.8,
                "turnover_rate": 2.34,
                "dif": 0.49,
                "dea": 0.52,
                "k": 40.6,
                "d": 54.4,
                "j": 13.0,
            }

    class FakeReplayService:
        def __init__(self):
            self.snapshot_provider = FakeProvider()

    class FakeContext:
        def __init__(self):
            self.service = FakeReplayService()

        def replay_service(self):
            return self.service

    context = FakeContext()
    profile = gateway_api._enrich_signal_strategy_profile_with_replay_snapshot(
        context=context,
        signal={"stock_code": "002518", "stock_name": "科士达", "checkpoint_at": "2025-08-29 13:30:00"},
        source="replay",
        replay_run={"timeframe": "30m"},
        strategy_profile={"analysis_timeframe": "30m", "market_snapshot": {"current_price": 36.63}},
    )

    snapshot = profile["market_snapshot"]
    assert context.service.snapshot_provider.prepared[0] == ["002518"]
    assert context.service.snapshot_provider.prepared[3] == "30m"
    assert snapshot["current_price"] == 36.63
    assert snapshot["open"] == 36.1
    assert snapshot["high"] == 37.2
    assert snapshot["low"] == 35.8
    assert snapshot["volume"] == 123456
    assert snapshot["turnover_rate"] == 2.34


def test_discover_snapshot_aggregates_multiple_selector_results(tmp_path, monkeypatch):
    module = _load_backend_api_module()
    selector_dir = tmp_path / "selector_results"
    selector_dir.mkdir(parents=True, exist_ok=True)

    _seed_main_force_result(selector_dir)
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
    _seed_simple_selector_result(
        selector_dir,
        "small_cap",
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
        ],
        "2026-04-13 13:30:00",
    )

    context = _make_context(tmp_path)
    app = module.create_app(context=context)
    client = TestClient(app)

    discover = client.get("/api/v1/discover").json()
    rows = discover["candidateTable"]["rows"]
    assert [row["code"] for row in rows][:3] == ["000001", "300750", "600519"]
    assert any(strategy["name"] == "低价擒牛" and "最近推荐 1 只" in strategy["status"] for strategy in discover["strategies"])
    assert "已汇总 3 个发现策略的最新结果" in discover["summary"]["body"]

    class FakeMainForceSelector:
        def get_main_force_stocks(self, **kwargs):
            return True, pd.DataFrame(
                [
                    {
                        "股票代码": "600519",
                        "股票简称": "贵州茅台",
                        "所属同花顺行业": "白酒",
                        "最新价": 1678.0,
                        "总市值": 21000.0,
                        "市盈率": 28.4,
                        "市净率": 8.6,
                        "理由": "主力持续流入",
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
            return False, pd.DataFrame(), "skip"

    class FakeValueStockSelector:
        def get_value_stocks(self, top_n=10):
            return False, pd.DataFrame(), "skip"

    monkeypatch.setattr(gateway_api, "MainForceStockSelector", FakeMainForceSelector)
    monkeypatch.setattr(gateway_api, "LowPriceBullSelector", FakeLowPriceBullSelector)
    monkeypatch.setattr(gateway_api, "SmallCapSelector", FakeSmallCapSelector)
    monkeypatch.setattr(gateway_api, "ProfitGrowthSelector", FakeProfitGrowthSelector)
    monkeypatch.setattr(gateway_api, "ValueStockSelector", FakeValueStockSelector)

    run_strategy = client.post("/api/v1/discover/actions/run-strategy", json={})
    assert run_strategy.status_code == 200
    run_rows = run_strategy.json()["candidateTable"]["rows"]
    assert [row["code"] for row in run_rows][:3] == ["600519", "000001", "300750"]

    add_watchlist_1 = client.post("/api/v1/discover/actions/item-watchlist", json={"code": "600519"})
    add_watchlist_2 = client.post("/api/v1/discover/actions/item-watchlist", json={"code": "000001"})
    assert add_watchlist_1.status_code == 200
    assert add_watchlist_2.status_code == 200

    batch_quant = client.post("/api/v1/workbench/actions/batch-quant", json={"codes": ["600519", "000001"]})
    assert batch_quant.status_code == 200
    live_sim = client.get("/api/v1/quant/live-sim").json()
    candidate_codes = {row["code"] for row in live_sim["candidatePool"]["rows"]}
    assert {"600519", "000001"}.issubset(candidate_codes)

    replay = client.get("/api/v1/quant/his-replay").json()
    assert replay["candidatePool"]["columns"] == ["股票代码", "股票名称", "最新价格"]
    for row in replay["candidatePool"]["rows"]:
        assert "actions" not in row or not row["actions"]


def test_backend_api_research_run_module_persists_real_snapshot(tmp_path, monkeypatch):
    module = _load_backend_api_module()
    selector_dir = tmp_path / "selector_results"
    selector_dir.mkdir(parents=True, exist_ok=True)

    class FakeSectorStrategyDataFetcher:
        def get_cached_data_with_fallback(self):
            return {"success": True, "market_overview": {}, "news": [], "sectors": {}, "concepts": {}, "sector_fund_flow": {}, "north_flow": {}}

    class FakeSectorStrategyEngine:
        def run_comprehensive_analysis(self, data):
            return {
                "comprehensive_report": "板块轮动向上",
                "final_predictions": {"long_short": {"bullish": [{"sector": "AI"}], "bearish": []}},
                "agents_analysis": {"chief": {"analysis": "板块分析完成"}},
            }

    class FakeLonghubangEngine:
        def run_comprehensive_analysis(self, days=1):
            return {
                "recommended_stocks": [{"code": "002463", "name": "沪电股份", "reason": "龙虎榜资金集中", "latest_price": "90.40"}],
                "agents_analysis": {"chief": {"analysis": "龙虎榜结论"}},
                "final_report": {"summary": "龙虎榜 summary"},
            }

    class FakeNewsFlowEngine:
        def run_full_analysis(self, include_ai=True):
            return {
                "ai_analysis": {
                    "stock_recommend": {"recommended_stocks": [{"code": "600519", "name": "贵州茅台", "reason": "新闻热度", "latest_price": "1453.96"}]},
                    "investment_advice": {"advice": "观望", "confidence": 60, "summary": "情绪偏稳"},
                },
                "trading_signals": {"operation_advice": "等待确认"},
            }

    class FakeMacroAnalysisEngine:
        def run_full_analysis(self, progress_callback=None):
            return {
                "candidate_stocks": [{"code": "300750", "name": "宁德时代", "reason": "宏观映射", "latest_price": "200.00"}],
                "agents_analysis": {
                    "chief": {
                        "analysis": "# A股后市综合报告\n\n## 当前宏观判断\n\n### 弱复苏中的结构分化\n总量修复偏慢，结构机会更强。\n\n### 出口链景气延续\n外需方向仍有支撑，景气链条仍值得跟踪。"
                    }
                },
                "sector_view": {"market_view": "行业景气回升"},
            }

    class FakeMacroCycleEngine:
        def run_full_analysis(self, progress_callback=None):
            return {"agents_analysis": {"chief": {"analysis": "周期仍在复苏"}}, "formatted_data": "周期数据"}

    monkeypatch.setattr(gateway_api, "SectorStrategyDataFetcher", FakeSectorStrategyDataFetcher)
    monkeypatch.setattr(gateway_api, "SectorStrategyEngine", FakeSectorStrategyEngine)
    monkeypatch.setattr(gateway_api, "LonghubangEngine", FakeLonghubangEngine)
    monkeypatch.setattr(gateway_api, "NewsFlowEngine", FakeNewsFlowEngine)
    monkeypatch.setattr(gateway_api, "MacroAnalysisEngine", FakeMacroAnalysisEngine)
    monkeypatch.setattr(gateway_api, "MacroCycleEngine", FakeMacroCycleEngine)
    sent_notifications: list[dict] = []
    monkeypatch.setattr(
        notification_service,
        "send_research_notification",
        lambda result, *, task_id=None, selected_modules=None: sent_notifications.append(
            {"result": result, "task_id": task_id, "selected_modules": selected_modules}
        )
        or True,
        raising=False,
    )

    context = module.UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=selector_dir,
        watchlist_db_file=tmp_path / "watchlist.db",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        portfolio_db_file=tmp_path / "portfolio_stocks.db",
        monitor_db_file=tmp_path / "stock_monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
        stock_name_resolver=lambda code: {"002463": "沪电股份", "600519": "贵州茅台", "300750": "宁德时代"}.get(code, code),
    )
    app = module.create_app(context=context)
    client = TestClient(app)

    response = client.post("/api/v1/research/actions/run-module", json={})
    assert response.status_code == 200
    payload = response.json()

    assert payload["modules"] and len(payload["modules"]) == 5
    assert payload["modules"][0]["name"] == "智策板块"
    assert payload["modules"][3]["output"] == "股票输出 1 只"
    assert "弱复苏中的结构分化" in payload["modules"][3]["note"]
    assert "出口链景气延续" in payload["modules"][3]["note"]
    assert not payload["modules"][3]["note"].endswith("…")
    assert [row["code"] for row in payload["outputTable"]["rows"]] == ["002463", "600519", "300750"]
    assert all(row["source"] in {"智瞰龙虎", "新闻流量", "宏观分析"} for row in payload["outputTable"]["rows"])
    assert payload["summary"]["body"].startswith("已刷新 5 个研究模块，其中 3 只股票有明确输出")

    snapshot = client.get("/api/v1/research").json()
    assert snapshot["outputTable"]["rows"] == payload["outputTable"]["rows"]
    assert snapshot["modules"][3]["note"] == payload["modules"][3]["note"]
    assert len(sent_notifications) == 1
    assert sent_notifications[0]["selected_modules"] == ["sector", "longhubang", "news", "macro", "cycle"]
    assert sent_notifications[0]["result"]["summary"]["title"] == "研究情报已更新"

