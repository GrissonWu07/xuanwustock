import threading
import sys
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.quant_kernel import trading_time_utils
from app.selector_result_store import save_latest_result
from app.stock_refresh_scheduler import UnifiedStockRefreshScheduler, load_stock_runtime_entries, save_stock_runtime_entries


def test_stock_refresh_scheduler_trading_time_uses_market_timezone():
    assert UnifiedStockRefreshScheduler._is_trading_time(
        "US",
        now_local=datetime(2026, 5, 4, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )
    assert not UnifiedStockRefreshScheduler._is_trading_time(
        "US",
        now_local=datetime(2026, 5, 4, 8, 0, tzinfo=ZoneInfo("America/New_York")),
    )


def test_stock_refresh_scheduler_reuses_cn_calendar_for_holidays(monkeypatch):
    monkeypatch.setattr(trading_time_utils, "HAS_CHINESE_CALENDAR", True)
    monkeypatch.setattr(
        trading_time_utils,
        "chinese_calendar",
        SimpleNamespace(is_workday=lambda value: False),
        raising=False,
    )

    assert not UnifiedStockRefreshScheduler._is_trading_time(
        "CN",
        now_local=datetime(2026, 5, 4, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )


def test_stock_refresh_scheduler_first_job_is_due_immediately():
    scheduler = UnifiedStockRefreshScheduler(lambda: None, interval_minutes=2)

    scheduler._register_jobs()
    jobs = scheduler.scheduler.get_jobs(scheduler.job_tag)

    assert jobs
    assert jobs[0].next_run <= datetime.now()


def test_stock_runtime_snapshot_persists_basic_info_status(tmp_path):
    save_stock_runtime_entries(
        {
            "600128": {
                "stock_code": "600128",
                "stock_name": "苏豪弘业",
                "latest_price": 9.92,
                "basic_info_checked_at": "2026-05-17T09:00:00Z",
                "basic_info_status": "remote_failed",
                "basic_info_failure_at": "2026-05-17T09:00:00Z",
            }
        },
        base_dir=tmp_path,
    )

    entry = load_stock_runtime_entries(base_dir=tmp_path)["600128"]

    assert entry["basic_info_status"] == "remote_failed"
    assert entry["basic_info_failure_at"] == "2026-05-17T09:00:00Z"


def test_runtime_entry_fetches_required_basic_info_even_if_legacy_env_disabled(monkeypatch):
    monkeypatch.setenv("UNIFIED_STOCK_REFRESH_BASIC_INFO_ENABLED", "false")
    basic_info_calls: list[str] = []
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_realtime_quote", staticmethod(lambda code, preferred_name=None: {"current_price": 18.8, "name": code}))
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_basic_info",
        staticmethod(lambda code: basic_info_calls.append(code) or {"name": "慢接口", "industry": "半导体"}),
    )

    entry = UnifiedStockRefreshScheduler._fetch_runtime_entry(
        stock_code="301560",
        existing=None,
    )

    assert basic_info_calls == ["301560"]
    assert entry["stock_code"] == "301560"
    assert entry["stock_name"] == "慢接口"
    assert entry["latest_price"] == 18.8
    assert entry["sector"] == "半导体"


def test_runtime_entry_refetches_basic_info_when_recent_check_left_metrics_missing(monkeypatch):
    basic_info_calls: list[str] = []
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_realtime_quote",
        staticmethod(lambda code, preferred_name=None: {"current_price": 9.92, "name": "苏豪弘业"}),
    )
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_basic_info",
        staticmethod(
            lambda code: basic_info_calls.append(code)
            or {
                "name": "苏豪弘业",
                "industry": "商贸零售",
                "market_cap": 2_450_000_000,
                "pe_ratio": 18.2,
                "pb_ratio": 1.1,
            }
        ),
    )

    entry = UnifiedStockRefreshScheduler._fetch_runtime_entry(
        stock_code="600128",
        existing={
            "stock_code": "600128",
            "stock_name": "苏豪弘业",
            "latest_price": 9.92,
            "basic_info_checked_at": datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S"),
        },
    )

    assert basic_info_calls == ["600128"]
    assert entry["sector"] == "商贸零售"
    assert entry["market_cap"] == 2_450_000_000
    assert entry["pe_ratio"] == 18.2
    assert entry["pb_ratio"] == 1.1
    assert entry["basic_info_status"] == "ready"


def test_realtime_quote_backfills_unresolved_tdx_name_from_data_source(monkeypatch):
    class FakeTdxFetcher:
        def get_realtime_quote(self, stock_code, preferred_name=None):
            return {
                "code": stock_code,
                "name": stock_code,
                "current_price": 11.1,
                "amount": 1000,
            }

    class FakeDataSourceManager:
        def get_realtime_quotes(self, stock_code):
            return {
                "symbol": stock_code,
                "name": "欣贺股份",
                "current_price": 11.2,
                "market_cap": 1_234_000_000,
                "pe_ratio": 18.5,
                "pb_ratio": 1.7,
            }

    monkeypatch.setitem(
        sys.modules,
        "app.smart_monitor_tdx_data",
        SimpleNamespace(SmartMonitorTDXDataFetcher=FakeTdxFetcher),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.data_source_manager",
        SimpleNamespace(data_source_manager=FakeDataSourceManager()),
    )

    quote = UnifiedStockRefreshScheduler._fetch_realtime_quote("003016")

    assert quote["name"] == "欣贺股份"
    assert quote["current_price"] == 11.1
    assert quote["market_cap"] == 1_234_000_000
    assert quote["pe_ratio"] == 18.5
    assert quote["pb_ratio"] == 1.7


def test_runtime_entry_stops_before_basic_info_after_shutdown_signal(monkeypatch):
    stop_event = threading.Event()
    basic_info_calls: list[str] = []
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_realtime_quote",
        staticmethod(lambda code, preferred_name=None: stop_event.set() or {"current_price": 18.8, "name": code}),
    )
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_basic_info",
        staticmethod(lambda code: basic_info_calls.append(code) or {"name": "不应继续取", "industry": "半导体"}),
    )

    entry = UnifiedStockRefreshScheduler._fetch_runtime_entry(
        stock_code="301560",
        existing=None,
        stop_event=stop_event,
    )

    assert basic_info_calls == []
    assert entry["stock_code"] == "301560"
    assert entry["stock_name"] == "301560"
    assert entry["latest_price"] == 18.8


def test_run_once_skips_remote_fetches_after_stop_requested(tmp_path):
    quote_calls: list[str] = []

    class FakeWatchlistService:
        def list_watches(self):
            return [{"stock_code": "000001"}]

        def quote_fetcher(self, code, preferred_name=None):
            quote_calls.append(code)
            return {"current_price": 99.9}

        def basic_info_fetcher(self, code):
            return {"name": "平安银行", "industry": "银行"}

    class FakeQuantDB:
        def get_candidates(self, status=None):
            return []

        def get_positions(self):
            return []

    class FakePortfolioManager:
        def get_all_stocks(self):
            return []

    context = SimpleNamespace(
        selector_result_dir=tmp_path,
        research_result_key="research",
        watchlist=lambda: FakeWatchlistService(),
        portfolio_manager=lambda: FakePortfolioManager(),
        quant_db=lambda: FakeQuantDB(),
        scheduler=lambda: SimpleNamespace(get_status=lambda: {"market": "CN"}),
    )
    scheduler = UnifiedStockRefreshScheduler(lambda: context)
    scheduler.stop_event.set()

    summary = scheduler.run_once(context=context, run_reason="scheduled")

    assert quote_calls == []
    assert summary["reason"] == "scheduled"
    assert summary["stopped"] is True
    assert summary["updated"] == 0


def test_runtime_entry_prefers_latest_trading_snapshot_outside_trading(monkeypatch):
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_realtime_quote", staticmethod(lambda code, preferred_name=None: {"current_price": 99.9, "name": "实时旧价", "update_time": "2026-04-25 10:00:00"}))
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_basic_info", staticmethod(lambda code: {"name": "平安银行", "industry": "银行"}))
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_latest_trading_snapshot",
        staticmethod(
            lambda code, preferred_name=None: {
                "current_price": 12.3,
                "name": "平安银行",
                "update_time": "2026-04-24 15:00:00",
                "data_source": "tdx_daily_latest",
            }
        ),
    )

    entry = UnifiedStockRefreshScheduler._fetch_runtime_entry(
        stock_code="000001",
        existing=None,
        prefer_last_trading_snapshot=True,
    )

    assert entry["stock_code"] == "000001"
    assert entry["stock_name"] == "实时旧价"
    assert entry["latest_price"] == 12.3
    assert entry["sector"] == "银行"
    assert entry["price_as_of"] == "2026-04-24 15:00:00"
    assert entry["data_source"] == "tdx_daily_latest"


def test_scheduled_cycle_runs_outside_trading(monkeypatch):
    class FakeContext:
        pass

    runs: list[tuple[object, str]] = []
    scheduler = UnifiedStockRefreshScheduler(lambda: FakeContext())
    monkeypatch.setattr(
        scheduler,
        "run_once",
        lambda *, context=None, run_reason="manual": runs.append((context, run_reason)) or {},
    )

    scheduler._run_scheduled_cycle()

    assert len(runs) == 1
    assert runs[0][1] == "scheduled"


def test_run_once_uses_last_trading_snapshot_when_market_closed(monkeypatch, tmp_path):
    updates: list[dict[str, object]] = []

    class FakeWatchlistService:
        def list_watches(self):
            return [{"stock_code": "000001"}]

        def update_watch_snapshot(self, code, *, latest_price=None, stock_name=None, metadata=None):
            updates.append(
                {
                    "code": code,
                    "latest_price": latest_price,
                    "stock_name": stock_name,
                    "metadata": metadata,
                }
            )

    class FakeQuantDB:
        def get_candidates(self, status=None):
            return []

        def get_positions(self):
            return []

        def update_candidate_latest_price(self, code, price):
            return None

        def update_position_market_price(self, code, price):
            return None

    class FakePortfolioManager:
        db = SimpleNamespace(update_stock=lambda *args, **kwargs: None)

        def get_all_stocks(self):
            return []

    watchlist = FakeWatchlistService()
    context = SimpleNamespace(
        selector_result_dir=tmp_path,
        research_result_key="research",
        watchlist=lambda: watchlist,
        portfolio_manager=lambda: FakePortfolioManager(),
        quant_db=lambda: FakeQuantDB(),
        scheduler=lambda: SimpleNamespace(get_status=lambda: {"market": "CN"}),
    )
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_is_trading_time", staticmethod(lambda market: False))
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_realtime_quote", staticmethod(lambda code, preferred_name=None: {"current_price": 99.9, "name": code, "update_time": "2026-04-25 10:00:00"}))
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_basic_info", staticmethod(lambda code: {"name": "平安银行", "industry": "银行"}))
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_latest_trading_snapshot",
        staticmethod(
            lambda code, preferred_name=None: {
                "current_price": 12.3,
                "name": "平安银行",
                "update_time": "2026-04-24 15:00:00",
                "data_source": "tdx_daily_latest",
            }
        ),
    )

    summary = UnifiedStockRefreshScheduler(lambda: context).run_once(context=context, run_reason="scheduled")
    entries = load_stock_runtime_entries(base_dir=tmp_path)

    assert summary["marketState"] == "last_trading_snapshot"
    assert updates[0]["latest_price"] == 12.3
    assert updates[0]["stock_name"] == "平安银行"
    assert entries["000001"]["latest_price"] == 12.3
    assert entries["000001"]["price_as_of"] == "2026-04-24 15:00:00"


def test_run_once_repairs_quant_candidate_name_when_refresh_resolves_it(monkeypatch, tmp_path):
    candidate_updates: list[dict[str, object]] = []

    class FakeWatchlistService:
        def list_watches(self):
            return []

    class FakeQuantDB:
        def get_candidates(self, status=None):
            return [{"stock_code": "301217", "stock_name": "301217", "latest_price": 70.0}]

        def get_positions(self):
            return []

        def update_candidate_latest_price(self, code, price):
            candidate_updates.append({"method": "price", "code": code, "price": price})

        def update_candidate_snapshot(self, code, *, latest_price=None, stock_name=None, metadata=None):
            candidate_updates.append(
                {
                    "method": "snapshot",
                    "code": code,
                    "latest_price": latest_price,
                    "stock_name": stock_name,
                    "metadata": metadata,
                }
            )

        def update_position_market_price(self, code, price):
            return None

    class FakePortfolioManager:
        db = SimpleNamespace(update_stock=lambda *args, **kwargs: None)

        def get_all_stocks(self):
            return []

    context = SimpleNamespace(
        selector_result_dir=tmp_path,
        research_result_key="research",
        watchlist=lambda: FakeWatchlistService(),
        portfolio_manager=lambda: FakePortfolioManager(),
        quant_db=lambda: FakeQuantDB(),
        scheduler=lambda: SimpleNamespace(get_status=lambda: {"market": "CN"}),
    )
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_is_trading_time", staticmethod(lambda market: True))
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_realtime_quote", staticmethod(lambda code, preferred_name=None: {"current_price": 70.98, "name": "和顺电气"}))
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_basic_info", staticmethod(lambda code: {"industry": "电力设备"}))

    UnifiedStockRefreshScheduler(lambda: context).run_once(context=context, run_reason="scheduled")

    assert {
        "method": "snapshot",
        "code": "301217",
        "latest_price": 70.98,
        "stock_name": "和顺电气",
        "metadata": {"industry": "电力设备", "sector": "电力设备"},
    } in candidate_updates


def test_run_once_uses_fresh_runtime_cache_without_remote_fetch(monkeypatch, tmp_path):
    quote_calls: list[str] = []
    updates: list[dict[str, object]] = []
    now_text = datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    save_stock_runtime_entries(
        {
            "000001": {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "latest_price": 12.34,
                "market_cap": 1200.0,
                "pe_ratio": 6.5,
                "pb_ratio": 0.8,
                "sector": "银行",
                "price_as_of": now_text,
                "data_source": "tdx_realtime",
                "ma5": 12.6,
                "ma10": 12.5,
                "ma20": 12.2,
                "ma20_slope": 0.02,
                "ma60": 11.8,
                "amount": 100_000_000,
                "volume_ratio": 1.4,
                "rsi": 58.0,
                "macd": 0.04,
                "trend": "up",
                "technical_snapshot_ready": True,
                "technical_snapshot_status": "ready",
                "technical_snapshot_missing_fields": [],
                "technical_snapshot_timeframe": "30m",
                "technical_snapshot_provider": "fixture",
                "technical_snapshot_at": now_text,
                "technical_snapshot_prepared_at": now_text,
                "technical_snapshot_row_count": 120,
                "technical_snapshot_indicator_version": "fixture-v1",
            }
        },
        base_dir=tmp_path,
        updated_at=now_text,
    )

    class FakeWatchlistService:
        def list_watches(self):
            return [{"stock_code": "000001"}]

        def update_watch_snapshot(self, code, *, latest_price=None, stock_name=None, metadata=None):
            updates.append({"code": code, "latest_price": latest_price, "stock_name": stock_name, "metadata": metadata})

    class FakeQuantDB:
        def get_candidates(self, status=None):
            return []

        def get_positions(self):
            return []

        def update_candidate_snapshot(self, *args, **kwargs):
            return None

        def update_position_market_price(self, *args, **kwargs):
            return None

        def list_candidate_events(self, *args, **kwargs):
            return []

    class FakePortfolioManager:
        def get_all_stocks(self):
            return []

    context = SimpleNamespace(
        selector_result_dir=tmp_path,
        research_result_key="research",
        watchlist=lambda: FakeWatchlistService(),
        portfolio_manager=lambda: FakePortfolioManager(),
        quant_db=lambda: FakeQuantDB(),
        scheduler=lambda: SimpleNamespace(get_status=lambda: {"market": "CN"}),
    )
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_is_trading_time", staticmethod(lambda market: True))
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_realtime_quote", staticmethod(lambda code, preferred_name=None: quote_calls.append(code) or {"current_price": 99.9}))

    summary = UnifiedStockRefreshScheduler(lambda: context).run_once(context=context, run_reason="scheduled")

    assert quote_calls == []
    assert summary["cacheHit"] == 1
    assert summary["remoteFetched"] == 0
    assert updates[0]["latest_price"] == 12.34


def test_run_once_refetches_fresh_cache_when_stock_name_is_only_code(monkeypatch, tmp_path):
    quote_calls: list[str] = []
    basic_info_calls: list[str] = []
    candidate_updates: list[dict[str, object]] = []
    now_text = datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    ready_snapshot = {
        "price": 36.88,
        "ma5": 35.6,
        "ma10": 35.1,
        "ma20": 34.8,
        "ma20_slope": 0.02,
        "ma60": 33.0,
        "amount": 88_000_000,
        "volume_ratio": 1.3,
        "rsi": 58.0,
        "macd": 0.04,
        "trend": "up",
        "technical_snapshot_ready": True,
        "technical_snapshot_status": "ready",
        "technical_snapshot_missing_fields": [],
        "technical_snapshot_timeframe": "30m",
        "technical_snapshot_provider": "fixture",
        "technical_snapshot_at": now_text,
        "technical_snapshot_prepared_at": now_text,
        "technical_snapshot_row_count": 120,
        "technical_snapshot_indicator_version": "fixture-v1",
    }
    save_stock_runtime_entries(
        {
            "301118": {
                "stock_code": "301118",
                "stock_name": "301118",
                "latest_price": 36.88,
                "market_cap": 1200.0,
                "pe_ratio": 32.0,
                "pb_ratio": 2.8,
                "sector": "化工",
                "price_as_of": now_text,
                "data_source": "fixture",
                "basic_info_checked_at": now_text,
                **ready_snapshot,
            }
        },
        base_dir=tmp_path,
        updated_at=now_text,
    )

    class FakeWatchlistService:
        def list_watches(self):
            return []

    class FakeQuantDB:
        def get_candidates(self, status=None):
            return [{"stock_code": "301118", "stock_name": "301118", "latest_price": 36.88}]

        def get_positions(self):
            return []

        def update_candidate_snapshot(self, code, *, latest_price=None, stock_name=None, metadata=None):
            candidate_updates.append({"code": code, "latest_price": latest_price, "stock_name": stock_name, "metadata": metadata})

        def update_position_market_price(self, *args, **kwargs):
            return None

        def list_candidate_events(self, *args, **kwargs):
            return []

    class FakePortfolioManager:
        def get_all_stocks(self):
            return []

    context = SimpleNamespace(
        selector_result_dir=tmp_path,
        research_result_key="research",
        watchlist=lambda: FakeWatchlistService(),
        portfolio_manager=lambda: FakePortfolioManager(),
        quant_db=lambda: FakeQuantDB(),
        scheduler=lambda: SimpleNamespace(get_status=lambda: {"market": "CN"}),
    )
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_is_trading_time", staticmethod(lambda market: True))
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_realtime_quote",
        staticmethod(lambda code, preferred_name=None: quote_calls.append(code) or {"current_price": 37.12, "name": code}),
    )
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_basic_info",
        staticmethod(lambda code: basic_info_calls.append(code) or {"name": "恒光股份", "industry": "化工"}),
    )
    monkeypatch.setattr("app.stock_refresh_scheduler.prepare_discovery_market_snapshot_safely", lambda code: ready_snapshot)

    summary = UnifiedStockRefreshScheduler(lambda: context).run_once(context=context, run_reason="scheduled")
    entries = load_stock_runtime_entries(base_dir=tmp_path)

    assert quote_calls == ["301118"]
    assert basic_info_calls == ["301118"]
    assert summary["cacheHit"] == 0
    assert summary["remoteFetched"] == 1
    assert entries["301118"]["stock_name"] == "恒光股份"
    assert candidate_updates[0]["stock_name"] == "恒光股份"


def test_run_once_refetches_fresh_cache_when_basic_info_is_incomplete(monkeypatch, tmp_path):
    quote_calls: list[str] = []
    basic_info_calls: list[str] = []
    now_text = datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    ready_snapshot = {
        "price": 9.92,
        "ma5": 9.8,
        "ma10": 9.7,
        "ma20": 9.6,
        "ma20_slope": 0.01,
        "ma60": 9.2,
        "amount": 42_000_000,
        "volume_ratio": 1.1,
        "rsi": 55.0,
        "macd": 0.03,
        "trend": "up",
        "technical_snapshot_ready": True,
        "technical_snapshot_status": "ready",
        "technical_snapshot_missing_fields": [],
        "technical_snapshot_timeframe": "30m",
        "technical_snapshot_provider": "fixture",
        "technical_snapshot_at": now_text,
        "technical_snapshot_prepared_at": now_text,
        "technical_snapshot_row_count": 120,
        "technical_snapshot_indicator_version": "fixture-v1",
    }
    save_stock_runtime_entries(
        {
            "600128": {
                "stock_code": "600128",
                "stock_name": "苏豪弘业",
                "latest_price": 9.92,
                "price_as_of": now_text,
                "data_source": "fixture",
                "basic_info_checked_at": now_text,
                **ready_snapshot,
            }
        },
        base_dir=tmp_path,
        updated_at=now_text,
    )

    class FakeWatchlistService:
        def list_watches(self):
            return [{"stock_code": "600128", "stock_name": "苏豪弘业"}]

        def update_watch_snapshot(self, *args, **kwargs):
            return None

    class FakeQuantDB:
        def get_candidates(self, status=None):
            return []

        def get_positions(self):
            return []

        def update_position_market_price(self, *args, **kwargs):
            return None

        def update_candidate_latest_price(self, *args, **kwargs):
            return None

    class FakePortfolioManager:
        def get_all_stocks(self):
            return []

    context = SimpleNamespace(
        selector_result_dir=tmp_path,
        research_result_key="research",
        watchlist=lambda: FakeWatchlistService(),
        portfolio_manager=lambda: FakePortfolioManager(),
        quant_db=lambda: FakeQuantDB(),
        scheduler=lambda: SimpleNamespace(get_status=lambda: {"market": "CN"}),
    )
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_is_trading_time", staticmethod(lambda market: True))
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_realtime_quote",
        staticmethod(lambda code, preferred_name=None: quote_calls.append(code) or {"current_price": 9.92, "name": "苏豪弘业"}),
    )
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_basic_info",
        staticmethod(lambda code: basic_info_calls.append(code) or {"name": "苏豪弘业", "industry": "商贸零售"}),
    )
    monkeypatch.setattr("app.stock_refresh_scheduler.prepare_discovery_market_snapshot_safely", lambda code: ready_snapshot)

    summary = UnifiedStockRefreshScheduler(lambda: context).run_once(context=context, run_reason="scheduled")

    assert summary["cacheHit"] == 0
    assert summary["remoteFetched"] == 1
    assert quote_calls == ["600128"]
    assert basic_info_calls == ["600128"]


def test_run_once_uses_discovery_artifact_name_when_remote_name_is_unresolved(monkeypatch, tmp_path):
    watch_updates: list[dict[str, object]] = []
    candidate_updates: list[dict[str, object]] = []

    save_latest_result(
        "discovery_candidate_artifact",
        {
            "rows": [
                {
                    "code": "300083",
                    "name": "创世纪",
                    "industry": "机械设备-通用设备-机床工具",
                    "latestPrice": "11.93",
                    "marketCap": "198.62",
                    "peRatio": "68.82",
                    "pbRatio": "3.74",
                }
            ]
        },
        base_dir=tmp_path,
    )

    class FakeWatchlistService:
        def list_watches(self):
            return [{"stock_code": "300083", "stock_name": "300083"}]

        def update_watch_snapshot(self, code, *, latest_price=None, stock_name=None, metadata=None):
            watch_updates.append({"code": code, "latest_price": latest_price, "stock_name": stock_name, "metadata": metadata})

    class FakeQuantDB:
        def get_candidates(self, status=None):
            return [{"stock_code": "300083", "stock_name": "300083"}]

        def get_positions(self):
            return []

        def update_candidate_snapshot(self, code, *, latest_price=None, stock_name=None, metadata=None):
            candidate_updates.append({"code": code, "latest_price": latest_price, "stock_name": stock_name, "metadata": metadata})

        def update_position_market_price(self, *args, **kwargs):
            return None

        def list_candidate_events(self, *args, **kwargs):
            return []

    class FakePortfolioManager:
        def get_all_stocks(self):
            return []

    context = SimpleNamespace(
        selector_result_dir=tmp_path,
        research_result_key="research",
        watchlist=lambda: FakeWatchlistService(),
        portfolio_manager=lambda: FakePortfolioManager(),
        quant_db=lambda: FakeQuantDB(),
        scheduler=lambda: SimpleNamespace(get_status=lambda: {"market": "CN"}),
    )
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_is_trading_time", staticmethod(lambda market: True))
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_realtime_quote", staticmethod(lambda code, preferred_name=None: {"current_price": 12.34, "name": code}))
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_basic_info", staticmethod(lambda code: {}))
    monkeypatch.setattr(
        "app.stock_refresh_scheduler.prepare_discovery_market_snapshot_safely",
        lambda code: {"price": 12.34, "technical_snapshot_ready": True},
    )

    summary = UnifiedStockRefreshScheduler(lambda: context).run_once(context=context, run_reason="scheduled")
    entries = load_stock_runtime_entries(base_dir=tmp_path)

    assert summary["remoteFetched"] == 1
    assert entries["300083"]["stock_name"] == "创世纪"
    assert entries["300083"]["market_cap"] == 198.62
    assert entries["300083"]["pe_ratio"] == 68.82
    assert entries["300083"]["pb_ratio"] == 3.74
    assert watch_updates[0]["stock_name"] == "创世纪"
    assert candidate_updates[0]["stock_name"] == "创世纪"


def test_run_once_updates_watchlist_metrics_from_basic_info_interface(monkeypatch, tmp_path):
    updates: list[dict[str, object]] = []

    class FakeWatchlistService:
        def list_watches(self):
            return [{"stock_code": "000001"}]

        def update_watch_snapshot(self, code, *, latest_price=None, stock_name=None, metadata=None):
            updates.append({"code": code, "latest_price": latest_price, "stock_name": stock_name, "metadata": metadata})

    class FakeQuantDB:
        def get_candidates(self, status=None):
            return []

        def get_positions(self):
            return []

        def update_candidate_snapshot(self, *args, **kwargs):
            return None

        def update_position_market_price(self, *args, **kwargs):
            return None

    class FakePortfolioManager:
        def get_all_stocks(self):
            return []

    context = SimpleNamespace(
        selector_result_dir=tmp_path,
        research_result_key="research",
        watchlist=lambda: FakeWatchlistService(),
        portfolio_manager=lambda: FakePortfolioManager(),
        quant_db=lambda: FakeQuantDB(),
        scheduler=lambda: SimpleNamespace(get_status=lambda: {"market": "CN"}),
    )
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_is_trading_time", staticmethod(lambda market: True))
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_realtime_quote", staticmethod(lambda code, preferred_name=None: {"current_price": 12.34, "name": "平安银行"}))
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_basic_info",
        staticmethod(lambda code: {"industry": "银行", "总市值": 120_000_000_000, "市盈率": 6.5, "市净率": 0.8}),
    )

    summary = UnifiedStockRefreshScheduler(lambda: context).run_once(context=context, run_reason="scheduled")
    entries = load_stock_runtime_entries(base_dir=tmp_path)

    assert summary["remoteFetched"] == 1
    assert updates[0]["metadata"] == {
        "industry": "银行",
        "sector": "银行",
        "market_cap": 120_000_000_000,
        "pe_ratio": 6.5,
        "pb_ratio": 0.8,
    }
    assert entries["000001"]["market_cap"] == 120_000_000_000
    assert entries["000001"]["pe_ratio"] == 6.5
    assert entries["000001"]["pb_ratio"] == 0.8


def test_run_once_respects_failure_cooldown_without_remote_retry(monkeypatch, tmp_path):
    quote_calls: list[str] = []
    now_text = datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    save_stock_runtime_entries(
        {
            "000001": {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "latest_price": 12.34,
                "sector": "银行",
                "price_as_of": now_text,
                "data_source": "remote_failed",
                "refresh_status": "remote_failed",
                "failure_at": now_text,
                "failure_count": 1,
            }
        },
        base_dir=tmp_path,
        updated_at=now_text,
    )

    class FakeWatchlistService:
        def list_watches(self):
            return [{"stock_code": "000001"}]

        def update_watch_snapshot(self, *args, **kwargs):
            return None

    class FakeQuantDB:
        def get_candidates(self, status=None):
            return []

        def get_positions(self):
            return []

        def update_candidate_snapshot(self, *args, **kwargs):
            return None

        def update_position_market_price(self, *args, **kwargs):
            return None

    class FakePortfolioManager:
        def get_all_stocks(self):
            return []

    context = SimpleNamespace(
        selector_result_dir=tmp_path,
        research_result_key="research",
        watchlist=lambda: FakeWatchlistService(),
        portfolio_manager=lambda: FakePortfolioManager(),
        quant_db=lambda: FakeQuantDB(),
        scheduler=lambda: SimpleNamespace(get_status=lambda: {"market": "CN"}),
    )
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_is_trading_time", staticmethod(lambda market: True))
    monkeypatch.setattr(UnifiedStockRefreshScheduler, "_fetch_realtime_quote", staticmethod(lambda code, preferred_name=None: quote_calls.append(code) or {"current_price": 99.9}))

    summary = UnifiedStockRefreshScheduler(lambda: context).run_once(context=context, run_reason="scheduled")

    assert quote_calls == []
    assert summary["cooldownSkipped"] == 1
