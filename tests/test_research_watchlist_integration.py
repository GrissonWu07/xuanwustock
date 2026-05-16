from app.research_watchlist_integration import (
    add_research_stock_to_watchlist,
    add_research_stocks_to_watchlist,
)
from app.gateway_api import UIApiContext, create_app
from app.selector_result_store import save_latest_result
from app.watchlist_service import WatchlistService
from fastapi.testclient import TestClient


def _context(tmp_path):
    selector_dir = tmp_path / "selector_results"
    selector_dir.mkdir(parents=True, exist_ok=True)
    return UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=selector_dir,
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
        monitor_db_file=tmp_path / "monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
        stock_analysis_db_file=tmp_path / "analysis.db",
        main_force_batch_db_file=tmp_path / "main_force_batch.db",
    )


def test_add_research_stock_to_watchlist_accepts_code_name_shape(tmp_path):
    db_file = tmp_path / "watchlist.db"

    success, message, watch_id = add_research_stock_to_watchlist(
        stock={
            "code": "301291",
            "name": "明阳电气",
            "price": 52.96,
            "sector": "电气设备",
            "reason": "资金关注度高",
        },
        source="longhubang",
        db_file=db_file,
    )

    service = WatchlistService(db_file=db_file)
    row = service.get_watch("301291")

    assert success is True
    assert "已加入关注池" in message
    assert watch_id > 0
    assert row["stock_name"] == "明阳电气"
    assert row["latest_price"] == 52.96
    assert row["metadata"]["industry"] == "电气设备"


def test_add_research_stocks_to_watchlist_accepts_mixed_shapes(tmp_path):
    db_file = tmp_path / "watchlist.db"
    service = WatchlistService(db_file=db_file)

    summary = add_research_stocks_to_watchlist(
        stocks=[
            {
                "code": "301291",
                "name": "明阳电气",
                "price": 52.96,
                "sector": "电气设备",
            },
            {
                "股票代码": "002824",
                "股票名称": "和胜股份",
                "最新价": 22.97,
                "所属行业": "消费电子",
            },
        ],
        source="macro_analysis",
        db_file=db_file,
    )

    watchlist = {row["stock_code"]: row for row in service.list_watches()}

    assert summary == {"attempted": 2, "success_count": 2, "failures": []}
    assert set(watchlist) == {"301291", "002824"}
    assert watchlist["002824"]["metadata"]["industry"] == "消费电子"


def test_research_snapshot_exposes_read_only_lifecycle_entry_fields(tmp_path):
    context = _context(tmp_path)
    save_latest_result(
        context.research_result_key,
        {
            "outputTable": {
                "rows": [
                    {
                        "code": "301291",
                        "name": "明阳电气",
                        "industry": "电气设备",
                        "source": "longhubang",
                        "latestPrice": 52.96,
                        "reason": "资金关注度高",
                    },
                    {
                        "code": "002824",
                        "name": "和胜股份",
                        "industry": "消费电子",
                        "source": "macro",
                        "latestPrice": 22.97,
                        "reason": "宏观景气支持",
                    },
                ]
            }
        },
        base_dir=context.selector_result_dir,
    )
    db = context.quant_db()
    db.upsert_quant_universe_state("002824", {"quant_status": "active", "candidate_score": 0.66})
    db.add_candidate_event(
        {
            "stock_code": "301291",
            "stock_name": "明阳电气",
            "source_type": "research",
            "source_key": "longhubang",
            "source_score": 0.83,
            "confidence": 0.77,
            "trend": "up",
            "status": "eligible",
            "reason_text": "资金关注度高",
        }
    )
    before_events = db.list_candidate_events(stock_code="301291", limit=20)
    client = TestClient(create_app(context=context))

    response = client.get("/api/v1/research")

    assert response.status_code == 200
    rows = {row["code"]: row for row in response.json()["outputTable"]["rows"]}
    for field in ("eligible_status", "candidate_score", "blocking_reason", "already_in_quant"):
        assert field in rows["301291"]
        assert field in rows["002824"]
    assert rows["301291"]["eligible_status"] == "eligible"
    assert rows["301291"]["already_in_quant"] is False
    assert rows["301291"]["candidate_score"] == 0.0
    assert rows["002824"]["eligible_status"] == "already_in_quant"
    assert rows["002824"]["already_in_quant"] is True
    assert rows["002824"]["candidate_score"] == 0.66
    assert db.list_candidate_events(stock_code="301291", limit=20) == before_events
