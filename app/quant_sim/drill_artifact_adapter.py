"""Live-quant drill artifact helpers.

This module intentionally reuses the run-scoped replay artifact adapter so
historical replay and drill runs cannot diverge in fact-layer behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.quant_sim.replay_artifact_adapter import RunArtifactContext, write_run_artifact_from_snapshot


def write_drill_artifact_from_snapshot(
    *,
    db_file: str | Path,
    run_id: int | str,
    stock_code: str,
    checkpoint: Any,
    snapshot: dict[str, Any],
    market: str = "CN",
    timeframe: str = "30m",
) -> dict[str, Any]:
    return write_run_artifact_from_snapshot(
        RunArtifactContext(
            db_file=db_file,
            run_id=run_id,
            run_type="live_quant_drill",
            market=market,
            timeframe=timeframe,
            trace_id=f"live-quant-drill:{run_id}",
        ),
        stock_code=stock_code,
        checkpoint=checkpoint,
        snapshot=snapshot,
    )
