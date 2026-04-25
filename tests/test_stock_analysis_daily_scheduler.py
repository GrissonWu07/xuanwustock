from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.data.analysis_context.repository import StockAnalysisContextRepository
from app.database import StockAnalysisDatabase
from app.stock_analysis_daily_scheduler import StockAnalysisDailyScheduler


def _analysis_payload(symbol: str, *, summary: str = "偏多") -> dict:
    return {
        "symbol": symbol,
        "stock_name": symbol,
        "period": "1y",
        "stock_info": {"symbol": symbol, "name": symbol},
        "agents_results": {},
        "discussion_result": "讨论",
        "final_decision": {"rating": "持有", "confidence": 0.8},
        "indicators": {},
        "historical_data": [],
        "data_as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_as_of_quality": "exact",
        "valid_until": (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),
        "analysis_context": {"score": 0.4, "effective_score": 0.32, "confidence": 0.8, "summary": summary},
    }


def test_stock_analysis_db_replace_same_day_keeps_one_record_per_symbol(tmp_path):
    db = StockAnalysisDatabase(tmp_path / "analysis.db")

    first_id = db.save_analysis(**_analysis_payload("000001", summary="旧分析"), replace_same_day=True)
    second_id = db.save_analysis(**_analysis_payload("000001", summary="新分析"), replace_same_day=True)

    records = db.get_recent_records_by_symbol("000001", limit=10)
    assert first_id != second_id
    assert len(records) == 1
    assert records[0]["id"] == second_id
    assert records[0]["analysis_context"]["summary"] == "新分析"


def test_daily_scheduler_dedupes_codes_and_skips_existing_today(tmp_path, monkeypatch):
    db = StockAnalysisDatabase(tmp_path / "analysis.db")
    db.save_analysis(**_analysis_payload("600519"), replace_same_day=True)
    calls: list[str] = []

    def fake_analyze(symbol, period, **kwargs):
        calls.append(symbol)
        db.save_analysis(**_analysis_payload(symbol), replace_same_day=True)
        return {"success": True, "symbol": symbol}

    import app.stock_analysis_daily_scheduler as module

    monkeypatch.setattr(module.stock_analysis_service, "analyze_single_stock_for_batch", fake_analyze)

    watchlist = SimpleNamespace(list_watches=lambda: [{"stock_code": "600519"}, {"stock_code": "000001"}])
    quant_db = SimpleNamespace(
        get_candidates=lambda status="active": [{"stock_code": "000001"}, {"stock_code": "002463"}],
        get_positions=lambda: [{"stock_code": "002463"}, {"stock_code": "300750"}],
    )
    portfolio_manager = SimpleNamespace(get_all_stocks=lambda: [{"code": "300750"}, {"code": "600519"}])
    context = SimpleNamespace(
        watchlist=lambda: watchlist,
        quant_db=lambda: quant_db,
        portfolio_manager=lambda: portfolio_manager,
        stock_analysis_db=lambda: db,
        stock_analysis_db_file=tmp_path / "analysis.db",
    )

    summary = StockAnalysisDailyScheduler(lambda: context).run_once(context=context, force=False)

    assert calls == ["000001", "002463", "300750"]
    assert summary["totalCodes"] == 4
    assert summary["skippedExisting"] == 1
    assert summary["updated"] == 3


def test_daily_scheduler_treats_unsaved_analysis_as_failure(tmp_path, monkeypatch):
    db = StockAnalysisDatabase(tmp_path / "analysis.db")

    def fake_analyze(symbol, period, **kwargs):
        return {"success": True, "symbol": symbol, "saved_to_db": False, "db_error": "database is locked"}

    import app.stock_analysis_daily_scheduler as module

    monkeypatch.setattr(module.stock_analysis_service, "analyze_single_stock_for_batch", fake_analyze)

    context = SimpleNamespace(
        watchlist=lambda: SimpleNamespace(list_watches=lambda: [{"stock_code": "000001"}]),
        quant_db=lambda: SimpleNamespace(get_candidates=lambda status="active": [], get_positions=lambda: []),
        portfolio_manager=lambda: SimpleNamespace(get_all_stocks=lambda: []),
        stock_analysis_db=lambda: db,
        stock_analysis_db_file=tmp_path / "analysis.db",
    )

    summary = StockAnalysisDailyScheduler(lambda: context).run_once(context=context)

    assert summary["updated"] == 0
    assert summary["failed"] == 1
    assert "database is locked" in summary["failures"][0]


def test_daily_analysis_context_is_valid_for_next_day_realtime_decision(tmp_path):
    db = StockAnalysisDatabase(tmp_path / "analysis.db")
    generated_at = datetime.now().replace(microsecond=0)
    db.save_analysis(
        **{
            **_analysis_payload("002518", summary="日更分析可用于次日"),
            "data_as_of": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "valid_until": (generated_at + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),
        },
        replace_same_day=True,
    )

    repo = StockAnalysisContextRepository(db_path=tmp_path / "analysis.db")
    context = repo.get_latest_valid(
        "002518",
        as_of=generated_at + timedelta(hours=12),
        mode="realtime",
        ttl_hours=24,
        min_confidence=0.45,
    )

    assert context is not None
    assert context["summary"] == "日更分析可用于次日"
