from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.integration import add_stock_to_quant_sim


def test_add_selected_stock_to_quant_sim_candidate_pool(tmp_path):
    success, message, candidate_id = add_stock_to_quant_sim(
        stock_code="600000.SH",
        stock_name="浦发银行",
        source="main_force",
        latest_price=10.45,
        db_file=tmp_path / "quant_sim.db",
    )

    service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    candidates = service.list_candidates()

    assert success is True
    assert "已加入量化模拟" in message
    assert candidate_id > 0
    assert candidates[0]["stock_code"] == "600000"
    assert candidates[0]["source"] == "main_force"


def test_add_stock_to_quant_sim_is_idempotent_per_stock(tmp_path):
    add_stock_to_quant_sim(
        stock_code="000001.SZ",
        stock_name="平安银行",
        source="profit_growth",
        latest_price=12.34,
        db_file=tmp_path / "quant_sim.db",
    )
    success, _, candidate_id = add_stock_to_quant_sim(
        stock_code="000001",
        stock_name="平安银行",
        source="profit_growth",
        latest_price=12.5,
        db_file=tmp_path / "quant_sim.db",
    )

    service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    candidates = service.list_candidates()

    assert success is True
    assert candidate_id > 0
    assert len(candidates) == 1
    assert candidates[0]["latest_price"] == 12.5
