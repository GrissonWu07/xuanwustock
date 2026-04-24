from datetime import datetime

from app.quant_kernel.models import Decision
from app.quant_sim.stockpolicy_adapter import StockPolicyAdapter


class FakeFetcher:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []

    def get_comprehensive_data(self, stock_code, preferred_name=None):
        self.calls.append({"stock_code": stock_code, "preferred_name": preferred_name})
        return dict(self.snapshot)


class FakeRuntime:
    def __init__(self):
        self.candidate_calls = []
        self.position_calls = []

    def evaluate_candidate(self, *, candidate, market_snapshot, current_time, analysis_timeframe="1d"):
        self.candidate_calls.append(
            {
                "candidate": candidate,
                "market_snapshot": market_snapshot,
                "current_time": current_time,
                "analysis_timeframe": analysis_timeframe,
            }
        )
        return Decision(
            code=candidate["stock_code"],
            action="BUY",
            confidence=0.81,
            price=float(market_snapshot["current_price"]),
            timestamp=current_time,
            reason="kernel-candidate",
            tech_score=0.6,
            context_score=0.3,
            position_ratio=0.5,
            decision_type="dual_track_resonance",
            strategy_profile={"analysis_timeframe": {"key": analysis_timeframe}},
        )

    def evaluate_position(self, *, candidate, position, market_snapshot, current_time, analysis_timeframe="1d"):
        self.position_calls.append(
            {
                "candidate": candidate,
                "position": position,
                "market_snapshot": market_snapshot,
                "current_time": current_time,
                "analysis_timeframe": analysis_timeframe,
            }
        )
        return Decision(
            code=position["stock_code"],
            action="SELL",
            confidence=0.76,
            price=float(market_snapshot["current_price"]),
            timestamp=current_time,
            reason="kernel-position",
            tech_score=-0.4,
            context_score=0.1,
            position_ratio=0.0,
            decision_type="dual_track_divergence",
            strategy_profile={"analysis_timeframe": {"key": analysis_timeframe}},
        )


def test_stockpolicy_adapter_delegates_candidate_analysis_to_kernel_runtime():
    snapshot = {
        "current_price": 61.99,
        "ma5": 58.7,
        "ma20": 55.5,
        "ma60": 51.37,
        "macd": 0.534,
        "rsi12": 70.6,
        "volume_ratio": 2.26,
        "trend": "up",
    }
    runtime = FakeRuntime()
    adapter = StockPolicyAdapter(data_fetcher=FakeFetcher(snapshot), runtime=runtime)

    decision = adapter.analyze_candidate(
        {
            "stock_code": "300390",
            "stock_name": "天华新能",
            "source": "main_force",
            "sources": ["main_force"],
        }
    )

    assert decision.reason == "kernel-candidate"
    assert len(runtime.candidate_calls) == 1
    assert runtime.candidate_calls[0]["candidate"]["stock_code"] == "300390"
    assert runtime.candidate_calls[0]["market_snapshot"]["current_price"] == 61.99
    assert runtime.candidate_calls[0]["analysis_timeframe"] == "1d"
    assert adapter.market_data_provider.data_fetcher.calls[0]["preferred_name"] == "天华新能"


def test_stockpolicy_adapter_merges_account_context_into_snapshot():
    snapshot = {
        "current_price": 61.99,
        "ma5": 58.7,
        "ma20": 55.5,
        "ma60": 51.37,
        "macd": 0.534,
        "rsi12": 70.6,
        "volume_ratio": 2.26,
        "trend": "up",
    }
    runtime = FakeRuntime()
    adapter = StockPolicyAdapter(data_fetcher=FakeFetcher(snapshot), runtime=runtime)

    adapter.analyze_candidate(
        {
            "stock_code": "300390",
            "stock_name": "天华新能",
            "source": "main_force",
            "sources": ["main_force"],
            "_quant_account_context": {"cash_ratio": 0.73},
        }
    )

    assert runtime.candidate_calls[0]["market_snapshot"]["cash_ratio"] == 0.73


def test_stockpolicy_adapter_passes_requested_timeframe_to_kernel_runtime():
    snapshot = {
        "current_price": 61.99,
        "ma5": 58.7,
        "ma20": 55.5,
        "ma60": 51.37,
        "macd": 0.534,
        "rsi12": 70.6,
        "volume_ratio": 2.26,
        "trend": "up",
    }
    runtime = FakeRuntime()
    adapter = StockPolicyAdapter(data_fetcher=FakeFetcher(snapshot), runtime=runtime)

    decision = adapter.analyze_candidate(
        {
            "stock_code": "300390",
            "stock_name": "天华新能",
            "source": "main_force",
            "sources": ["main_force"],
        },
        analysis_timeframe="1d+30m",
    )

    assert decision.strategy_profile["analysis_timeframe"]["key"] == "1d+30m"
    assert runtime.candidate_calls[0]["analysis_timeframe"] == "1d+30m"


def test_stockpolicy_adapter_delegates_position_analysis_to_kernel_runtime():
    snapshot = {
        "current_price": 52.96,
        "ma20": 55.73,
        "macd": -1.361,
        "rsi12": 42.12,
    }
    runtime = FakeRuntime()
    adapter = StockPolicyAdapter(data_fetcher=FakeFetcher(snapshot), runtime=runtime)

    decision = adapter.analyze_position(
        {
            "stock_code": "301291",
            "stock_name": "明阳电气",
            "source": "main_force",
            "sources": ["main_force"],
        },
        {
            "stock_code": "301291",
            "stock_name": "明阳电气",
            "avg_price": 53.5,
            "latest_price": 53.0,
        },
    )

    assert decision.reason == "kernel-position"
    assert len(runtime.position_calls) == 1
    assert runtime.position_calls[0]["position"]["stock_code"] == "301291"
    assert runtime.position_calls[0]["market_snapshot"]["current_price"] == 52.96
    assert adapter.market_data_provider.data_fetcher.calls[0]["preferred_name"] == "明阳电气"
