from __future__ import annotations

import pytest

from app.quant_sim.db import QuantSimDB
from app.quant_sim.quant_universe_lifecycle import (
    QuantUniverseLifecyclePolicy,
    QuantUniverseManager,
)


def _manager(tmp_path) -> QuantUniverseManager:
    return QuantUniverseManager(
        db=QuantSimDB(tmp_path / "quant_sim.db"),
        profile_id="aggressive",
        policy=QuantUniverseLifecyclePolicy.aggressive_defaults(),
    )


def _bullish_payload_without_snapshot_metadata() -> dict:
    return {
        "price": 12.8,
        "ma5": 12.7,
        "ma10": 12.2,
        "ma20": 11.8,
        "ma20_slope": 0.035,
        "ma60": 10.6,
        "amount": 130_000_000,
        "volume_ratio": 1.45,
        "rsi": 61.0,
        "macd": 0.22,
        "trend": "up",
        "technical_snapshot_row_count": 180,
        "technical_confirmation_count": 5,
        "consecutive_checkpoint_score": 1.0,
        "ma20_breakout_retest_score": 1.0,
    }


@pytest.mark.parametrize(
    ("source_type", "source_key"),
    [
        ("research", "research:test"),
        ("low_price", "low_price:test"),
    ],
)
def test_non_discover_bullish_candidate_requires_ready_snapshot_metadata(
    tmp_path,
    source_type: str,
    source_key: str,
) -> None:
    manager = _manager(tmp_path)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source=source_type)

    result = manager.ingest_candidate_event(
        {
            "stock_code": "600000",
            "source_type": source_type,
            "source_key": source_key,
            "source_score": 0.99,
            "confidence": 0.99,
            "trend": "up",
            "payload_json": _bullish_payload_without_snapshot_metadata(),
        }
    )

    state = manager.db.get_quant_universe_state("600000")

    assert result["decision"] == "skipped"
    assert result["reason_code"] == "missing_technical_snapshot"
    assert result["candidate_score"] == 0.0
    assert result["candidate_confidence"] == 0.0
    assert state["quant_status"] == "inactive"
    assert state["candidate_score"] == 0.0
    assert state["candidate_confidence"] == 0.0
    blocked_events = manager.db.list_candidate_events(stock_code="600000", status="blocked")
    entry_gate = blocked_events[0]["payload_json"]["entry_gate"]
    assert entry_gate["reason_code"] == "missing_technical_snapshot"
    assert "technical_snapshot_status" in entry_gate["missing_fields"]
    assert "technical_snapshot_at" in entry_gate["missing_fields"]
