from types import SimpleNamespace

from app.stock_refresh_scheduler import UnifiedStockRefreshScheduler, load_stock_runtime_entries


def test_runtime_entry_fetches_required_basic_info_even_if_legacy_env_disabled(monkeypatch):
    monkeypatch.setenv("UNIFIED_STOCK_REFRESH_BASIC_INFO_ENABLED", "false")
    basic_info_calls: list[str] = []

    class FakeWatchlistService:
        def quote_fetcher(self, code, preferred_name=None):
            return {"current_price": 18.8, "name": code}

        def basic_info_fetcher(self, code):
            basic_info_calls.append(code)
            return {"name": "慢接口", "industry": "半导体"}

    entry = UnifiedStockRefreshScheduler._fetch_runtime_entry(
        watchlist_service=FakeWatchlistService(),
        stock_code="301560",
        existing=None,
    )

    assert basic_info_calls == ["301560"]
    assert entry["stock_code"] == "301560"
    assert entry["stock_name"] == "慢接口"
    assert entry["latest_price"] == 18.8
    assert entry["sector"] == "半导体"


def test_runtime_entry_prefers_latest_trading_snapshot_outside_trading(monkeypatch):
    class FakeWatchlistService:
        def quote_fetcher(self, code, preferred_name=None):
            return {"current_price": 99.9, "name": "实时旧价", "update_time": "2026-04-25 10:00:00"}

        def basic_info_fetcher(self, code):
            return {"name": "平安银行", "industry": "银行"}

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
        watchlist_service=FakeWatchlistService(),
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

        def quote_fetcher(self, code, preferred_name=None):
            return {"current_price": 99.9, "name": code, "update_time": "2026-04-25 10:00:00"}

        def basic_info_fetcher(self, code):
            return {"name": "平安银行", "industry": "银行"}

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
