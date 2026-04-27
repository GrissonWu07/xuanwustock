from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request

from app import stock_analysis_service
from app.config_manager import ConfigManager, config_manager
from app.database import StockAnalysisDatabase
from app.gateway.common import (
    code_from_payload as _code_from_payload,
    first_non_empty as _first_non_empty,
    float_value as _float,
    insight as _insight,
    int_value as _int,
    metric as _metric,
    now as _now,
    num as _num,
    p as _p,
    payload_dict as _payload_dict,
    pct as _pct,
    table as _table,
    timeline as _timeline,
    txt as _txt,
)
from app.main_force_batch_db import MainForceBatchDatabase
from app.monitor_db import StockMonitorDatabase, monitor_db
from app.portfolio_db import portfolio_db
from app.portfolio_rebalance_tasks import portfolio_rebalance_task_manager
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.capital_slots import calculate_slot_plan, normalize_capital_slot_config
from app.quant_sim.db import (
    DEFAULT_AI_DYNAMIC_LOOKBACK,
    DEFAULT_AI_DYNAMIC_STRENGTH,
    DEFAULT_AI_DYNAMIC_STRATEGY,
    DEFAULT_COMMISSION_RATE,
    DEFAULT_SELL_TAX_RATE,
    QuantSimDB,
    is_sqlite_locked_error,
)
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.replay_service import QuantSimReplayService
from app.quant_sim.scheduler import get_quant_sim_scheduler
from app.runtime_paths import DATA_DIR, LOGS_DIR, default_db_path
from app.selector_result_store import DEFAULT_SELECTOR_RESULT_DIR
from app.stock_refresh_scheduler import load_stock_runtime_entries
from app.watchlist_selector_integration import normalize_stock_code
from app.watchlist_service import WatchlistService
from app.workbench_analysis_payloads import (
    analysis_config as _workbench_analysis_config,
    analysis_options as _workbench_analysis_options,
    build_workbench_analysis_payload as _build_workbench_analysis_payload,
)
from app.workbench_analysis_tasks import analysis_task_manager

__all__ = [name for name in globals() if not name.startswith("__")]
