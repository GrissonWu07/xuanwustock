from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_sim.candidate_pool_service import CandidatePoolService
from watchlist_service import WatchlistService


def add_watchlist_rows_to_quant_pool(
    stock_codes: list[str],
    watchlist_service: WatchlistService,
    candidate_service: CandidatePoolService | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    candidate_service = candidate_service or CandidatePoolService(db_file=db_file)  # type: ignore[arg-type]
    summary = {"attempted": 0, "success_count": 0, "failures": []}

    for stock_code in stock_codes:
        watch = watchlist_service.get_watch(stock_code)
        if not watch:
            summary["failures"].append(f"{stock_code}: watchlist row not found")
            continue

        summary["attempted"] += 1
        candidate_service.add_manual_candidate(
            stock_code=watch["stock_code"],
            stock_name=watch["stock_name"],
            source=watch["source_summary"] or "watchlist",
            latest_price=watch["latest_price"],
            notes=watch.get("notes"),
            metadata=watch.get("metadata"),
        )
        watchlist_service.mark_in_quant_pool(watch["stock_code"], True)
        summary["success_count"] += 1

    return summary
