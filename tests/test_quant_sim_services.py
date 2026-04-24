from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.signal_center_service import SignalCenterService
from app.notification_service import notification_service


def test_candidate_pool_service_adds_manual_candidate(tmp_path):
    service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")

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
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

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
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

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
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

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


def test_signal_center_does_not_emit_sell_signal_without_open_position(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="301291",
        stock_name="明阳电气",
        source="main_force",
    )
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "SELL",
            "confidence": 72,
            "reasoning": "趋势走弱，建议卖出",
            "position_size_pct": 0,
        },
    )

    pending = signal_service.list_pending_signals()

    assert signal["action"] == "HOLD"
    assert signal["status"] == "observed"
    assert pending == []
    assert "无持仓" in signal["reasoning"]


def test_signal_center_sanitizes_legacy_pending_sell_without_open_position(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="301291",
        stock_name="明阳电气",
        source="main_force",
    )
    candidate = candidate_service.list_candidates()[0]
    signal_id = signal_service.db.add_signal(
        {
            "candidate_id": candidate["id"],
            "stock_code": candidate["stock_code"],
            "stock_name": candidate["stock_name"],
            "action": "SELL",
            "confidence": 72,
            "reasoning": "历史遗留卖出信号",
            "position_size_pct": 0,
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "decision_type": "legacy",
            "tech_score": -0.15,
            "context_score": 0.28,
            "status": "pending",
        }
    )

    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="301291")

    assert pending == []
    assert history[0]["id"] == signal_id
    assert history[0]["action"] == "HOLD"
    assert history[0]["status"] == "observed"
    assert "无持仓" in history[0]["reasoning"]


def test_signal_center_persists_strategy_profile(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        metadata={"profit_growth_pct": 35.0, "roe_pct": 19.0},
    )
    candidate = candidate_service.list_candidates()[0]

    signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 87,
            "reasoning": "策略共振买入",
            "position_size_pct": 60,
            "strategy_profile": {
                "market_regime": {"label": "牛市", "score": 0.66},
                "fundamental_quality": {"label": "强基本面", "score": 0.58},
                "risk_style": {"label": "激进", "max_position_ratio": 0.8},
                "analysis_timeframe": {"key": "30m"},
                "effective_thresholds": {"buy_threshold": 0.64, "sell_threshold": -0.25},
            },
        },
    )

    signal = signal_service.list_signals(stock_code="300390", limit=1)[0]

    assert signal["strategy_profile"]["market_regime"]["label"] == "牛市"
    assert signal["strategy_profile"]["fundamental_quality"]["label"] == "强基本面"
    assert signal["strategy_profile"]["risk_style"]["label"] == "激进"
    assert signal["strategy_profile"]["analysis_timeframe"]["key"] == "30m"


def test_signal_center_can_skip_live_notification(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    sent_notifications: list[dict] = []

    monkeypatch.setattr(notification_service, "send_notification", lambda payload: sent_notifications.append(payload) or True)

    candidate_service.add_manual_candidate(
        stock_code="002594",
        stock_name="比亚迪",
        source="main_force",
        latest_price=256.3,
    )
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 88,
            "reasoning": "强趋势突破",
            "position_size_pct": 35,
        },
        notify=False,
    )

    assert signal["status"] == "pending"
    assert sent_notifications == []


def test_signal_center_temp_db_does_not_emit_external_side_effects(tmp_path, monkeypatch):
    saved_ai_decisions: list[dict] = []
    sent_notifications: list[dict] = []

    class FakeSmartMonitorDB:
        def __init__(self, db_file):
            self.db_file = db_file

        def save_ai_decision(self, payload):
            saved_ai_decisions.append(payload)

    monkeypatch.setattr("app.quant_sim.signal_center_service.SmartMonitorDB", FakeSmartMonitorDB)
    monkeypatch.setattr(notification_service, "send_notification", lambda payload: sent_notifications.append(payload) or True)

    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate(
        stock_code="300750",
        stock_name="宁德时代",
        source="main_force",
        latest_price=201.5,
    )
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 82,
            "reasoning": "建仓",
            "position_size_pct": 20,
        },
    )

    assert signal["status"] == "pending"
    assert saved_ai_decisions == []
    assert sent_notifications == []


def test_signal_center_notify_false_skips_ai_decision_mirror(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    saved_ai_decisions: list[dict] = []

    class FakeSmartMonitorDB:
        def __init__(self, db_file):
            self.db_file = db_file

        def save_ai_decision(self, payload):
            saved_ai_decisions.append(payload)

    monkeypatch.setattr("app.quant_sim.signal_center_service.DEFAULT_DB_FILE", str(db_file))
    monkeypatch.setattr("app.quant_sim.signal_center_service.SmartMonitorDB", FakeSmartMonitorDB)

    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    candidate_service.add_manual_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=86.5,
    )
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 82,
            "reasoning": "历史回放买入信号",
            "position_size_pct": 60,
        },
        notify=False,
    )

    assert signal["status"] == "pending"
    assert saved_ai_decisions == []
