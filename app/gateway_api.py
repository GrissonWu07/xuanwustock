from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import akshare_client, smart_monitor_tdx_data
from app.gateway.constants import REPLAY_TABLE_PAGE_SIZE, SERVICE_NAME, UI_DIST_DIR
from app.gateway.context import UIApiContext
from app.gateway.deps import _int, _now, _payload_dict, _txt, normalize_stock_code
from app.gateway.his_replay import _action_his_replay_cancel, _action_his_replay_continue, _action_his_replay_delete, _action_his_replay_start, _his_replay_database_busy, _snapshot_his_replay, _snapshot_his_replay_capital_pool, _snapshot_his_replay_progress
from app.gateway.history import _action_history_rerun, _snapshot_history
from app.gateway.live_sim import _action_live_sim_analyze_candidate, _action_live_sim_bulk_quant, _action_live_sim_delete_candidate, _action_live_sim_delete_position, _action_live_sim_reset, _action_live_sim_save, _action_live_sim_start, _action_live_sim_stop, _live_signal_table, _live_trade_table, _snapshot_live_sim
from app.gateway.monitor import _action_ai_monitor_analyze, _action_ai_monitor_delete, _action_ai_monitor_start, _action_ai_monitor_stop, _action_real_monitor_delete_rule, _action_real_monitor_refresh, _action_real_monitor_start, _action_real_monitor_stop, _action_real_monitor_update_rule, _snapshot_ai_monitor, _snapshot_real_monitor
import app.gateway.portfolio as _gateway_portfolio_module
from app.gateway.portfolio import _action_portfolio_analyze as _action_portfolio_analyze_impl, _action_portfolio_delete_position as _action_portfolio_delete_position_impl, _action_portfolio_refresh as _action_portfolio_refresh_impl, _action_portfolio_refresh_indicators as _action_portfolio_refresh_indicators_impl, _action_portfolio_schedule_save as _action_portfolio_schedule_save_impl, _action_portfolio_schedule_start as _action_portfolio_schedule_start_impl, _action_portfolio_schedule_stop as _action_portfolio_schedule_stop_impl, _action_portfolio_update_position as _action_portfolio_update_position_impl, _portfolio_technical_snapshot as _portfolio_technical_snapshot, _snapshot_portfolio as _snapshot_portfolio_impl
from app.gateway.settings import _action_settings_save, _snapshot_settings
from app.gateway.signal_detail import _find_signal_detail
from app.gateway.signal_market import _enrich_signal_strategy_profile_with_replay_snapshot
from app.gateway.strategy_profiles import clone_strategy_profile as _clone_strategy_profile, create_strategy_profile as _create_strategy_profile, delete_strategy_profile as _delete_strategy_profile, get_strategy_profile as _get_strategy_profile, list_strategy_profiles as _list_strategy_profiles, set_default_strategy_profile as _set_default_strategy_profile, update_strategy_profile as _update_strategy_profile, validate_strategy_profile as _validate_strategy_profile
from app.gateway.table_query import _replay_table_query_from_request
from app.gateway.discover import action_discover_batch as _action_discover_batch, action_discover_item as _action_discover_item, action_discover_reset as _action_discover_reset, action_discover_run_strategy as _gateway_discover_run_strategy, discover_task_manager, snapshot_discover as _snapshot_discover
import app.gateway.discover as _gateway_discover_module
from app.gateway.research import action_research_batch as _action_research_batch, action_research_item as _action_research_item, action_research_reset as _action_research_reset, action_research_run_module as _gateway_research_run_module, research_task_manager, snapshot_research as _snapshot_research
import app.gateway.research as _gateway_research_module
from app.gateway.workbench import action_workbench_add_watchlist as _action_workbench_add_watchlist, action_workbench_analysis as _action_workbench_analysis, action_workbench_batch_portfolio as _action_workbench_batch_portfolio, action_workbench_batch_quant as _action_workbench_batch_quant, action_workbench_delete as _action_workbench_delete, action_workbench_refresh as _action_workbench_refresh
from app.gateway.workbench_analysis import _analysis_options, _hydrate_cached_workbench_analysis, _run_single_workbench_analysis, _snapshot_workbench, action_workbench_analysis_batch_compat as _action_workbench_analysis_batch_compat
from app.portfolio_rebalance_tasks import portfolio_rebalance_task_manager
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.db import is_sqlite_locked_error
from app.stock_analysis_daily_scheduler import get_stock_analysis_daily_scheduler
from app.stock_refresh_scheduler import get_unified_stock_refresh_scheduler
from app.version_info import get_version_info
from app.workbench_analysis_tasks import analysis_task_manager

MainForceStockSelector = _gateway_discover_module.MainForceStockSelector
LowPriceBullSelector = _gateway_discover_module.LowPriceBullSelector
SmallCapSelector = _gateway_discover_module.SmallCapSelector
ProfitGrowthSelector = _gateway_discover_module.ProfitGrowthSelector
ValueStockSelector = _gateway_discover_module.ValueStockSelector
SectorStrategyDataFetcher = _gateway_research_module.SectorStrategyDataFetcher
SectorStrategyEngine = _gateway_research_module.SectorStrategyEngine
LonghubangEngine = _gateway_research_module.LonghubangEngine
NewsFlowEngine = _gateway_research_module.NewsFlowEngine
MacroAnalysisEngine = _gateway_research_module.MacroAnalysisEngine
MacroCycleEngine = _gateway_research_module.MacroCycleEngine


async def _json(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return {}


def _action_discover_run_strategy(context: UIApiContext, payload: Any) -> dict[str, Any]:
    _gateway_discover_module.MainForceStockSelector = globals().get("MainForceStockSelector")
    _gateway_discover_module.LowPriceBullSelector = globals().get("LowPriceBullSelector")
    _gateway_discover_module.SmallCapSelector = globals().get("SmallCapSelector")
    _gateway_discover_module.ProfitGrowthSelector = globals().get("ProfitGrowthSelector")
    _gateway_discover_module.ValueStockSelector = globals().get("ValueStockSelector")
    return _gateway_discover_run_strategy(context, payload)


def _action_research_run_module(context: UIApiContext, payload: Any) -> dict[str, Any]:
    _gateway_research_module.SectorStrategyDataFetcher = globals().get("SectorStrategyDataFetcher")
    _gateway_research_module.SectorStrategyEngine = globals().get("SectorStrategyEngine")
    _gateway_research_module.LonghubangEngine = globals().get("LonghubangEngine")
    _gateway_research_module.NewsFlowEngine = globals().get("NewsFlowEngine")
    _gateway_research_module.MacroAnalysisEngine = globals().get("MacroAnalysisEngine")
    _gateway_research_module.MacroCycleEngine = globals().get("MacroCycleEngine")
    return _gateway_research_run_module(context, payload)


def _sync_portfolio_compat_hooks() -> None:
    _gateway_portfolio_module._portfolio_technical_snapshot = globals().get(
        "_portfolio_technical_snapshot",
        _gateway_portfolio_module._portfolio_technical_snapshot,
    )


def _snapshot_portfolio(*args: Any, **kwargs: Any) -> dict[str, Any]:
    _sync_portfolio_compat_hooks()
    return _snapshot_portfolio_impl(*args, **kwargs)


def _action_portfolio_analyze(context: UIApiContext, payload: Any) -> dict[str, Any]:
    _sync_portfolio_compat_hooks()
    return _action_portfolio_analyze_impl(context, payload)


def _action_portfolio_refresh(context: UIApiContext, payload: Any) -> dict[str, Any]:
    _sync_portfolio_compat_hooks()
    return _action_portfolio_refresh_impl(context, payload)


def _action_portfolio_refresh_indicators(context: UIApiContext, payload: Any) -> dict[str, Any]:
    _sync_portfolio_compat_hooks()
    return _action_portfolio_refresh_indicators_impl(context, payload)


def _action_portfolio_update_position(context: UIApiContext, payload: Any) -> dict[str, Any]:
    _sync_portfolio_compat_hooks()
    return _action_portfolio_update_position_impl(context, payload)


def _action_portfolio_delete_position(context: UIApiContext, payload: Any) -> dict[str, Any]:
    _sync_portfolio_compat_hooks()
    return _action_portfolio_delete_position_impl(context, payload)


def _action_portfolio_schedule_save(context: UIApiContext, payload: Any) -> dict[str, Any]:
    return _action_portfolio_schedule_save_impl(context, payload)


def _action_portfolio_schedule_start(context: UIApiContext, payload: Any) -> dict[str, Any]:
    return _action_portfolio_schedule_start_impl(context, payload)


def _action_portfolio_schedule_stop(context: UIApiContext, payload: Any) -> dict[str, Any]:
    return _action_portfolio_schedule_stop_impl(context, payload)


def _action_noop(context: UIApiContext, page: str) -> dict[str, Any]:
    return SNAPSHOT_BUILDERS[page](context)


SNAPSHOT_BUILDERS = {
    "workbench": _snapshot_workbench,
    "discover": _snapshot_discover,
    "research": _snapshot_research,
    "portfolio": _snapshot_portfolio,
    "live-sim": _snapshot_live_sim,
    "his-replay": _snapshot_his_replay,
    "ai-monitor": _snapshot_ai_monitor,
    "real-monitor": _snapshot_real_monitor,
    "history": _snapshot_history,
    "settings": _snapshot_settings,
}

ACTION_BUILDERS = {
    ("workbench", "add-watchlist"): _action_workbench_add_watchlist,
    ("workbench", "refresh-watchlist"): _action_workbench_refresh,
    ("workbench", "batch-quant"): _action_workbench_batch_quant,
    ("workbench", "batch-portfolio"): _action_workbench_batch_portfolio,
    ("workbench", "analysis"): _action_workbench_analysis,
    ("workbench", "analysis-batch"): _action_workbench_analysis_batch_compat,
    ("workbench", "clear-selection"): lambda context, payload: _action_noop(context, "workbench"),
    ("workbench", "delete-watchlist"): _action_workbench_delete,
    ("discover", "run-strategy"): _action_discover_run_strategy,
    ("discover", "batch-watchlist"): _action_discover_batch,
    ("discover", "item-watchlist"): _action_discover_item,
    ("discover", "reset-list"): _action_discover_reset,
    ("research", "run-module"): _action_research_run_module,
    ("research", "batch-watchlist"): _action_research_batch,
    ("research", "item-watchlist"): _action_research_item,
    ("research", "reset-list"): _action_research_reset,
    ("portfolio", "analyze"): _action_portfolio_analyze,
    ("portfolio", "refresh-portfolio"): _action_portfolio_refresh,
    ("portfolio", "schedule-save"): _action_portfolio_schedule_save,
    ("portfolio", "schedule-start"): _action_portfolio_schedule_start,
    ("portfolio", "schedule-stop"): _action_portfolio_schedule_stop,
    ("portfolio", "refresh-indicators"): _action_portfolio_refresh_indicators,
    ("portfolio", "update-position"): _action_portfolio_update_position,
    ("portfolio", "delete-position"): _action_portfolio_delete_position,
    ("live-sim", "save"): _action_live_sim_save,
    ("live-sim", "start"): _action_live_sim_start,
    ("live-sim", "stop"): _action_live_sim_stop,
    ("live-sim", "reset"): _action_live_sim_reset,
    ("live-sim", "analyze-candidate"): _action_live_sim_analyze_candidate,
    ("live-sim", "delete-candidate"): _action_live_sim_delete_candidate,
    ("live-sim", "delete-position"): _action_live_sim_delete_position,
    ("live-sim", "bulk-quant"): _action_live_sim_bulk_quant,
    ("his-replay", "start"): _action_his_replay_start,
    ("his-replay", "continue"): _action_his_replay_continue,
    ("his-replay", "cancel"): _action_his_replay_cancel,
    ("his-replay", "delete"): _action_his_replay_delete,
    ("ai-monitor", "start"): _action_ai_monitor_start,
    ("ai-monitor", "stop"): _action_ai_monitor_stop,
    ("ai-monitor", "analyze"): _action_ai_monitor_analyze,
    ("ai-monitor", "delete"): _action_ai_monitor_delete,
    ("real-monitor", "start"): _action_real_monitor_start,
    ("real-monitor", "stop"): _action_real_monitor_stop,
    ("real-monitor", "refresh"): _action_real_monitor_refresh,
    ("real-monitor", "update-rule"): _action_real_monitor_update_rule,
    ("real-monitor", "delete-rule"): _action_real_monitor_delete_rule,
    ("history", "rerun"): _action_history_rerun,
    ("settings", "save"): _action_settings_save,
}

TASK_MANAGERS = [analysis_task_manager, discover_task_manager, research_task_manager, portfolio_rebalance_task_manager]


def _health(path: str) -> dict[str, str]:
    version = get_version_info()
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "path": path,
        "version": str(version.get("version") or ""),
        "revision": str(version.get("revision") or ""),
    }


def _resolve_task_manager(task_id: str):
    for manager in TASK_MANAGERS:
        if manager.owns_task(task_id):
            return manager
    for manager in TASK_MANAGERS:
        if manager.get_task(task_id):
            return manager
    return None


def create_app(context: UIApiContext | None = None) -> FastAPI:
    api_context = context or UIApiContext()

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        try:
            akshare_client.reset_shutdown()
            smart_monitor_tdx_data.reset_shutdown()
            unified_stock_refresh_scheduler = get_unified_stock_refresh_scheduler(api_context)
            unified_stock_refresh_scheduler.start()
            app.state.unified_stock_refresh_scheduler = unified_stock_refresh_scheduler
        except Exception:
            app.state.unified_stock_refresh_scheduler = None
        try:
            stock_analysis_daily_scheduler = get_stock_analysis_daily_scheduler(api_context)
            stock_analysis_daily_scheduler.start()
            app.state.stock_analysis_daily_scheduler = stock_analysis_daily_scheduler
        except Exception:
            app.state.stock_analysis_daily_scheduler = None
        try:
            yield
        finally:
            akshare_client.request_shutdown()
            smart_monitor_tdx_data.request_shutdown()
            analysis_scheduler = getattr(app.state, "stock_analysis_daily_scheduler", None)
            if analysis_scheduler:
                analysis_scheduler.stop()
            scheduler = getattr(app.state, "unified_stock_refresh_scheduler", None)
            if scheduler:
                scheduler.stop()

    app = FastAPI(title="玄武AI智能体股票团队分析系统 Backend API", version="0.1.0", lifespan=app_lifespan)
    app.state.ui_context = api_context

    @app.get("/api/health")
    def api_health() -> dict[str, str]:
        return _health("/api/health")

    @app.get("/health")
    def health() -> dict[str, str]:
        return _health("/health")

    @app.get("/api/version")
    def api_version() -> dict[str, Any]:
        return get_version_info()

    @app.get("/api/v1/version")
    def api_v1_version() -> dict[str, Any]:
        return get_version_info()

    @app.get("/api/v1/tasks/{task_id}")
    def get_analysis_task(task_id: str) -> dict[str, Any]:
        manager = _resolve_task_manager(task_id)
        task = manager.get_task(task_id) if manager else None
        if not task:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        return manager.task_response(task, txt=_txt, int_fn=_int)

    @app.get("/api/v1/quant/signals/{signal_id}")
    def get_signal_detail(signal_id: str, source: str = "auto", refresh_market: bool = False) -> dict[str, Any]:
        return _find_signal_detail(api_context, signal_id, source=source, fetch_realtime_snapshot=bool(refresh_market))

    @app.get("/api/v1/quant/live-sim/signals")
    def get_live_sim_signals(page: int = 1, pageSize: int = REPLAY_TABLE_PAGE_SIZE, action: str = "ALL", stock: str = "") -> dict[str, Any]:
        return _live_signal_table(api_context, page=page, page_size=pageSize, action=action, stock=stock)

    @app.get("/api/v1/quant/live-sim/trades")
    def get_live_sim_trades(page: int = 1, pageSize: int = REPLAY_TABLE_PAGE_SIZE, action: str = "ALL", stock: str = "") -> dict[str, Any]:
        return {"updatedAt": _now(), "table": _live_trade_table(api_context, {"page": page, "pageSize": pageSize, "action": action, "stock": stock})}

    @app.get("/api/v1/portfolio_v2/positions/{symbol}")
    def get_portfolio_position(symbol: str) -> dict[str, Any]:
        normalized = normalize_stock_code(symbol)
        if not normalized:
            raise HTTPException(status_code=400, detail="Missing portfolio stock code")
        return _snapshot_portfolio(api_context, selected_symbol=normalized)

    @app.patch("/api/v1/portfolio_v2/positions/{symbol}")
    async def patch_portfolio_position(symbol: str, request: Request) -> dict[str, Any]:
        body = _payload_dict(await _json(request))
        body["code"] = normalize_stock_code(symbol)
        return _action_portfolio_update_position(api_context, body)

    @app.get("/api/v1/strategy-profiles")
    def list_strategy_profiles(include_disabled: bool = False) -> dict[str, Any]:
        return _list_strategy_profiles(api_context, include_disabled=include_disabled)

    @app.get("/api/v1/strategy-profiles/{profile_id}")
    def get_strategy_profile(profile_id: str, versions_limit: int = 20) -> dict[str, Any]:
        return _get_strategy_profile(api_context, profile_id, versions_limit=versions_limit)

    @app.post("/api/v1/strategy-profiles")
    async def create_strategy_profile(request: Request) -> dict[str, Any]:
        return _create_strategy_profile(api_context, _payload_dict(await _json(request)))

    @app.put("/api/v1/strategy-profiles/{profile_id}")
    async def update_strategy_profile(profile_id: str, request: Request) -> dict[str, Any]:
        return _update_strategy_profile(api_context, profile_id, _payload_dict(await _json(request)))

    @app.post("/api/v1/strategy-profiles/{profile_id}/clone")
    async def clone_strategy_profile(profile_id: str, request: Request) -> dict[str, Any]:
        return _clone_strategy_profile(api_context, profile_id, _payload_dict(await _json(request)))

    @app.post("/api/v1/strategy-profiles/{profile_id}/validate")
    async def validate_strategy_profile(profile_id: str, request: Request) -> dict[str, Any]:
        return _validate_strategy_profile(api_context, profile_id, _payload_dict(await _json(request)))

    @app.post("/api/v1/strategy-profiles/{profile_id}/set-default")
    def set_default_strategy_profile(profile_id: str) -> dict[str, Any]:
        return _set_default_strategy_profile(api_context, profile_id)

    @app.delete("/api/v1/strategy-profiles/{profile_id}")
    def delete_strategy_profile(profile_id: str) -> dict[str, Any]:
        return _delete_strategy_profile(api_context, profile_id)

    @app.get("/api/v1/workbench")
    def get_workbench_snapshot(request: Request) -> dict[str, Any]:
        return _snapshot_workbench(api_context, table_query=_replay_table_query_from_request(request))

    @app.get("/api/v1/discover")
    def get_discover_snapshot(request: Request) -> dict[str, Any]:
        return _snapshot_discover(api_context, table_query=_replay_table_query_from_request(request))

    @app.get("/api/v1/research")
    def get_research_snapshot(request: Request) -> dict[str, Any]:
        return _snapshot_research(api_context, table_query=_replay_table_query_from_request(request))

    @app.get("/api/v1/portfolio")
    @app.get("/api/v1/portfolio_v2")
    def get_portfolio_snapshot(request: Request) -> dict[str, Any]:
        return _snapshot_portfolio(api_context, table_query=_replay_table_query_from_request(request))

    @app.get("/api/v1/quant/live-sim")
    def get_live_sim_snapshot(request: Request) -> dict[str, Any]:
        return _snapshot_live_sim(api_context, table_query=_replay_table_query_from_request(request))

    @app.get("/api/v1/quant/his-replay")
    def get_his_replay_snapshot(request: Request) -> dict[str, Any]:
        try:
            return _snapshot_his_replay(api_context, _replay_table_query_from_request(request))
        except Exception as exc:
            if is_sqlite_locked_error(exc):
                raise _his_replay_database_busy(exc) from exc
            raise

    @app.get("/api/v1/quant/his-replay/progress")
    def get_his_replay_progress(request: Request) -> dict[str, Any]:
        try:
            return _snapshot_his_replay_progress(api_context, _replay_table_query_from_request(request))
        except Exception as exc:
            if is_sqlite_locked_error(exc):
                raise _his_replay_database_busy(exc) from exc
            raise

    @app.get("/api/v1/quant/his-replay/capital-pool")
    def get_his_replay_capital_pool(request: Request) -> dict[str, Any]:
        try:
            return _snapshot_his_replay_capital_pool(api_context, _replay_table_query_from_request(request))
        except Exception as exc:
            if is_sqlite_locked_error(exc):
                raise _his_replay_database_busy(exc) from exc
            raise

    @app.get("/api/v1/history")
    def get_history_snapshot(request: Request) -> dict[str, Any]:
        return _snapshot_history(api_context, table_query=_replay_table_query_from_request(request))

    @app.get("/api/v1/monitor/ai")
    def get_ai_monitor_snapshot(request: Request) -> dict[str, Any]:
        return _snapshot_ai_monitor(api_context, table_query=_replay_table_query_from_request(request))

    for path, page in {"/api/v1/monitor/real": "real-monitor", "/api/v1/settings": "settings"}.items():
        async def snapshot_handler(page: str = page) -> dict[str, Any]:
            return SNAPSHOT_BUILDERS[page](api_context)

        snapshot_handler.__name__ = f"get_{page.replace('-', '_').replace('/', '_')}_snapshot"
        app.get(path)(snapshot_handler)

    for path, page, action in ACTION_ROUTES:
        async def action_handler(request: Request, page: str = page, action: str = action) -> dict[str, Any]:
            payload = await _json(request)
            handler = ACTION_BUILDERS.get((page, action))
            if not handler:
                raise HTTPException(status_code=404, detail=f"Unsupported action: {page}/{action}")
            try:
                return handler(api_context, payload)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        action_handler.__name__ = f"post_{page.replace('-', '_').replace('/', '_')}_{action.replace('-', '_')}"
        app.post(path)(action_handler)

    if UI_DIST_DIR.exists():
        assets_dir = UI_DIST_DIR / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="ui-assets")

        @app.get("/", include_in_schema=False)
        @app.get("/{client_path:path}", include_in_schema=False)
        async def spa_entry(client_path: str = ""):
            if client_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            requested = UI_DIST_DIR / client_path
            if client_path and requested.is_file():
                return FileResponse(requested)
            return FileResponse(UI_DIST_DIR / "index.html")

    return app


ACTION_ROUTES = [
    ("/api/v1/workbench/actions/add-watchlist", "workbench", "add-watchlist"),
    ("/api/v1/workbench/actions/refresh-watchlist", "workbench", "refresh-watchlist"),
    ("/api/v1/workbench/actions/batch-quant", "workbench", "batch-quant"),
    ("/api/v1/workbench/actions/batch-portfolio", "workbench", "batch-portfolio"),
    ("/api/v1/workbench/actions/analysis", "workbench", "analysis"),
    ("/api/v1/workbench/actions/analysis-batch", "workbench", "analysis-batch"),
    ("/api/v1/workbench/actions/clear-selection", "workbench", "clear-selection"),
    ("/api/v1/workbench/actions/delete-watchlist", "workbench", "delete-watchlist"),
    ("/api/v1/discover/actions/item-watchlist", "discover", "item-watchlist"),
    ("/api/v1/discover/actions/batch-watchlist", "discover", "batch-watchlist"),
    ("/api/v1/discover/actions/run-strategy", "discover", "run-strategy"),
    ("/api/v1/discover/actions/reset-list", "discover", "reset-list"),
    ("/api/v1/research/actions/item-watchlist", "research", "item-watchlist"),
    ("/api/v1/research/actions/batch-watchlist", "research", "batch-watchlist"),
    ("/api/v1/research/actions/run-module", "research", "run-module"),
    ("/api/v1/research/actions/reset-list", "research", "reset-list"),
    ("/api/v1/portfolio/actions/analyze", "portfolio", "analyze"),
    ("/api/v1/portfolio/actions/refresh-portfolio", "portfolio", "refresh-portfolio"),
    ("/api/v1/portfolio/actions/schedule-save", "portfolio", "schedule-save"),
    ("/api/v1/portfolio/actions/schedule-start", "portfolio", "schedule-start"),
    ("/api/v1/portfolio/actions/schedule-stop", "portfolio", "schedule-stop"),
    ("/api/v1/portfolio/actions/refresh-indicators", "portfolio", "refresh-indicators"),
    ("/api/v1/portfolio/actions/update-position", "portfolio", "update-position"),
    ("/api/v1/portfolio/actions/delete-position", "portfolio", "delete-position"),
    ("/api/v1/portfolio_v2/actions/analyze", "portfolio", "analyze"),
    ("/api/v1/portfolio_v2/actions/refresh-portfolio", "portfolio", "refresh-portfolio"),
    ("/api/v1/portfolio_v2/actions/schedule-save", "portfolio", "schedule-save"),
    ("/api/v1/portfolio_v2/actions/schedule-start", "portfolio", "schedule-start"),
    ("/api/v1/portfolio_v2/actions/schedule-stop", "portfolio", "schedule-stop"),
    ("/api/v1/portfolio_v2/actions/refresh-indicators", "portfolio", "refresh-indicators"),
    ("/api/v1/portfolio_v2/actions/update-position", "portfolio", "update-position"),
    ("/api/v1/portfolio_v2/actions/delete-position", "portfolio", "delete-position"),
    ("/api/v1/quant/live-sim/actions/save", "live-sim", "save"),
    ("/api/v1/quant/live-sim/actions/start", "live-sim", "start"),
    ("/api/v1/quant/live-sim/actions/stop", "live-sim", "stop"),
    ("/api/v1/quant/live-sim/actions/reset", "live-sim", "reset"),
    ("/api/v1/quant/live-sim/actions/analyze-candidate", "live-sim", "analyze-candidate"),
    ("/api/v1/quant/live-sim/actions/delete-candidate", "live-sim", "delete-candidate"),
    ("/api/v1/quant/live-sim/actions/delete-position", "live-sim", "delete-position"),
    ("/api/v1/quant/live-sim/actions/bulk-quant", "live-sim", "bulk-quant"),
    ("/api/v1/quant/his-replay/actions/start", "his-replay", "start"),
    ("/api/v1/quant/his-replay/actions/continue", "his-replay", "continue"),
    ("/api/v1/quant/his-replay/actions/cancel", "his-replay", "cancel"),
    ("/api/v1/quant/his-replay/actions/delete", "his-replay", "delete"),
    ("/api/v1/monitor/ai/actions/start", "ai-monitor", "start"),
    ("/api/v1/monitor/ai/actions/stop", "ai-monitor", "stop"),
    ("/api/v1/monitor/ai/actions/analyze", "ai-monitor", "analyze"),
    ("/api/v1/monitor/ai/actions/delete", "ai-monitor", "delete"),
    ("/api/v1/monitor/real/actions/start", "real-monitor", "start"),
    ("/api/v1/monitor/real/actions/stop", "real-monitor", "stop"),
    ("/api/v1/monitor/real/actions/refresh", "real-monitor", "refresh"),
    ("/api/v1/monitor/real/actions/update-rule", "real-monitor", "update-rule"),
    ("/api/v1/monitor/real/actions/delete-rule", "real-monitor", "delete-rule"),
    ("/api/v1/history/actions/rerun", "history", "rerun"),
    ("/api/v1/settings/actions/save", "settings", "save"),
]


__all__ = ["UIApiContext", "create_app"]
