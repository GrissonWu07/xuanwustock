from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.portfolio_service import PortfolioService
from quant_sim.signal_center_service import SignalCenterService


def test_candidate_pool_service_adds_manual_candidate(tmp_path):
    service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")

    candidate_id = service.add_manual_candidate(
        stock_code="000001",
        stock_name="平安银行",
        source="profit_growth",
        latest_price=12.34,
    )

    rows = service.list_candidates()

    assert candidate_id > 0
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "000001"
    assert rows[0]["source"] == "profit_growth"
    assert rows[0]["sources"] == ["profit_growth"]


def test_signal_center_creates_pending_and_observed_signals(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")

    candidate_id = candidate_service.add_manual_candidate(
        stock_code="600519",
        stock_name="贵州茅台",
        source="value_stock",
    )
    candidate = candidate_service.list_candidates()[0]

    buy_signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 81,
            "reasoning": "均线修复",
            "position_size_pct": 20,
        },
    )
    hold_signal = signal_service.create_signal(
        candidate,
        {
            "action": "HOLD",
            "confidence": 65,
            "reasoning": "等待右侧确认",
            "position_size_pct": 0,
        },
    )

    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="600519")

    assert candidate_id > 0
    assert buy_signal["status"] == "pending"
    assert hold_signal["status"] == "observed"
    assert len(pending) == 1
    assert pending[0]["action"] == "BUY"
    assert len(history) == 2


def test_portfolio_service_confirm_buy_and_delay_signal(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="300750",
        stock_name="宁德时代",
        source="main_force",
    )
    candidate = candidate_service.list_candidates()[0]
    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 84,
            "reasoning": "量价共振",
            "position_size_pct": 25,
        },
    )

    portfolio_service.delay_signal(signal["id"], note="等尾盘再看")
    delayed_signal = signal_service.list_pending_signals()[0]
    portfolio_service.confirm_buy(signal["id"], price=201.5, quantity=100, note="已在券商端买入")

    positions = portfolio_service.list_positions()
    executed = signal_service.list_signals(stock_code="300750")[0]

    assert delayed_signal["delay_count"] == 1
    assert positions[0]["stock_code"] == "300750"
    assert positions[0]["quantity"] == 100
    assert executed["status"] == "executed"


def test_signal_center_upserts_repeated_pending_signal_for_same_stock_and_action(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="600519",
        stock_name="贵州茅台",
        source="value_stock",
    )
    candidate = candidate_service.list_candidates()[0]

    first_signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 78,
            "reasoning": "第一次建仓建议",
            "position_size_pct": 20,
        },
    )
    second_signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 84,
            "reasoning": "第二次刷新后的建仓建议",
            "position_size_pct": 25,
        },
    )

    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="600519")

    assert first_signal["id"] == second_signal["id"]
    assert len(pending) == 1
    assert len(history) == 1
    assert pending[0]["confidence"] == 84
    assert pending[0]["reasoning"] == "第二次刷新后的建仓建议"
