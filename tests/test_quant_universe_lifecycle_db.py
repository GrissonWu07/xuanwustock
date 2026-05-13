import sqlite3

from app.quant_sim.db import QuantSimDB


def _table_names(db_file) -> set[str]:
    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def _column_names(db: QuantSimDB, table_name: str) -> set[str]:
    with db._connect() as conn:  # noqa: SLF001 - schema contract test
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def test_quant_universe_schema_created(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    db = QuantSimDB(db_file)

    tables = _table_names(db_file)

    assert "stock_universe_quant_state" in tables
    assert "stock_universe_candidate_events" in tables
    assert "stock_universe_quant_events" in tables
    assert "quant_universe_settings" in tables
    columns = _column_names(db, "stock_universe")
    assert {
        "quant_status",
        "quant_auto_managed",
        "quant_manual_override",
        "quant_entry_source",
        "quant_entry_at",
    } <= columns


def test_quant_universe_state_crud_updates_stock_membership(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    db.add_candidate(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "source": "manual",
            "latest_price": 10.5,
        }
    )

    state = db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "trial",
            "candidate_score": 0.71,
            "candidate_confidence": 0.63,
            "health_score": 72.5,
            "snapshot_json": {"kernel_health_base": 68.0},
        },
    )

    assert state["stock_code"] == "600000"
    assert state["stock_name"] == "浦发银行"
    assert state["quant_status"] == "trial"
    assert state["quant_enabled"] is True
    assert state["health_score"] == 72.5
    assert state["candidate_score"] == 0.71
    assert state["candidate_confidence"] == 0.63
    assert state["snapshot_json"]["kernel_health_base"] == 68.0

    loaded = db.get_quant_universe_state("600000")

    assert loaded == state
    with db._connect() as conn:  # noqa: SLF001 - verifies denormalized stock_universe fields
        row = conn.execute(
            "SELECT quant_status, quant_enabled FROM stock_universe WHERE stock_code = ?",
            ("600000",),
        ).fetchone()
    assert row["quant_status"] == "trial"
    assert int(row["quant_enabled"]) == 1


def test_quant_universe_state_ignores_legacy_source_weighted_candidate_score(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    db.upsert_quant_universe_state(
        "600000",
        {
            "stock_name": "浦发银行",
            "quant_status": "trial",
            "candidate_score": 0.82,
            "candidate_confidence": 0.78,
            "health_score": 90.0,
            "snapshot_json": {
                "candidate_score_breakdown": {
                    "source_score_component": 0.82,
                    "confidence_component": 0.78,
                    "trend_component": 1.0,
                }
            },
        },
    )

    loaded = db.get_quant_universe_state("600000")

    assert loaded["candidate_score"] == 0
    assert loaded["candidate_confidence"] == 0
    assert loaded["snapshot_json"]["legacy_source_score_component_ignored"] is True
    assert "source_score_component" not in loaded["snapshot_json"]["candidate_score_breakdown"]


def test_quant_universe_events_settings_and_overview(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    db.add_candidate({"stock_code": "600000", "stock_name": "浦发银行", "source": "manual"})
    db.add_watch(stock_code="000001", stock_name="平安银行", source="discover")
    db.upsert_quant_universe_state("600000", {"quant_status": "trial", "health_score": 88.0})

    candidate_event = db.add_candidate_event(
        {
            "stock_code": "000001",
            "source_type": "discover",
            "source_key": "main_force",
            "source_score": 0.86,
            "confidence": 0.74,
            "trend": "up",
            "reason_text": "多来源候选支持",
            "payload_json": {"rank": 1},
            "status": "eligible",
        }
    )
    events = db.list_candidate_events(stock_code="000001", status="eligible")

    assert events[0]["id"] == candidate_event["id"]
    assert events[0]["payload_json"] == {"rank": 1}
    assert events[0]["source_score"] == 0.86

    quant_event = db.record_quant_universe_event(
        {
            "stock_code": "600000",
            "event_type": "state_changed",
            "from_status": "inactive",
            "to_status": "trial",
            "reason_code": "manual_promote",
            "reason_text": "手动纳入试运行",
            "health_score_before": 100.0,
            "health_score_after": 88.0,
            "candidate_score": 0.71,
            "evidence_json": {"source": "test"},
        }
    )

    assert quant_event["evidence_json"] == {"source": "test"}

    settings = db.get_quant_universe_settings()
    assert settings["quant_universe_lifecycle_enabled"] is True
    assert settings["auto_exit_enabled"] is True
    assert settings["auto_entry_mode"] == "auto_trial"

    updated = db.update_quant_universe_settings(
        {
            "quant_universe_lifecycle_enabled": False,
            "auto_exit_enabled": False,
            "auto_entry_mode": "manual_only",
        }
    )

    assert updated["quant_universe_lifecycle_enabled"] is False
    assert updated["auto_exit_enabled"] is False
    assert updated["auto_entry_mode"] == "manual_only"

    overview = db.get_quant_universe_overview()

    assert overview["trial"]["count"] == 1
    assert overview["trial"]["top_items"] == [
        {"stock_code": "600000", "stock_name": "浦发银行", "latest_reason": ""}
    ]
    assert overview["pending_eligible"]["count"] == 1
    assert overview["pending_eligible"]["top_items"] == [
        {"stock_code": "000001", "stock_name": "平安银行", "latest_reason": "多来源候选支持"}
    ]


def test_list_quant_universe_state_filters_status_and_search(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    db.add_candidate({"stock_code": "600000", "stock_name": "浦发银行", "source": "manual"})
    db.add_candidate({"stock_code": "000001", "stock_name": "平安银行", "source": "manual"})
    db.upsert_quant_universe_state("600000", {"quant_status": "trial", "health_score": 50.0})
    db.upsert_quant_universe_state("000001", {"quant_status": "cooling", "health_score": 30.0})

    result = db.list_quant_universe_state(statuses=["trial"], keyword="浦发", limit=10, offset=0)

    assert result["total"] == 1
    assert result["items"][0]["stock_code"] == "600000"
    assert result["items"][0]["quant_status"] == "trial"
