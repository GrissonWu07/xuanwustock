from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.scheduler import QuantSimScheduler


def test_scheduler_run_once_scans_candidates_and_creates_signals(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")
    candidate_service.add_manual_candidate("000001", "平安银行", "profit_growth")

    scheduler = QuantSimScheduler(db_file=tmp_path / "quant_sim.db")

    def fake_analyze(candidate, market_snapshot=None):
        if candidate["stock_code"] == "600000":
            return {
                "action": "BUY",
                "confidence": 81,
                "reasoning": "趋势修复",
                "position_size_pct": 20,
            }
        return {
            "action": "HOLD",
            "confidence": 60,
            "reasoning": "继续观察",
            "position_size_pct": 0,
        }

    monkeypatch.setattr(scheduler.engine.adapter, "analyze_candidate", fake_analyze)

    result = scheduler.run_once()

    assert result["candidates_scanned"] == 2
    assert result["signals_created"] == 2
    assert result["positions_checked"] == 0
