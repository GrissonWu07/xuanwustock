from fastapi.testclient import TestClient

from app.gateway_api import UIApiContext, create_app


def _context(tmp_path):
    selector_dir = tmp_path / "selector_results"
    selector_dir.mkdir(parents=True, exist_ok=True)
    return UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=selector_dir,
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
        monitor_db_file=tmp_path / "monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
        stock_analysis_db_file=tmp_path / "analysis.db",
        main_force_batch_db_file=tmp_path / "main_force_batch.db",
    )


def test_quant_universe_state_settings_and_overview_endpoints(tmp_path):
    context = _context(tmp_path)
    db = context.quant_db()
    db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "trial",
            "candidate_score": 0.82,
            "candidate_confidence": 0.76,
            "health_score": 66,
            "downtrend_streak": 1,
            "weakening_warning_streak": 2,
            "cooling_until": "2026-05-09T00:00:00Z",
            "quant_entry_source": "discover",
        },
    )
    db.add_watch(stock_code="600001", stock_name="邯郸钢铁", source="discover")
    db.add_candidate_event(
        {
            "stock_code": "600001",
            "source_type": "discover",
            "source_score": 0.9,
            "confidence": 0.8,
            "trend": "up",
            "reason_text": "主力共振",
            "status": "eligible",
        }
    )
    client = TestClient(create_app(context=context))

    state = client.get("/api/v1/quant/universe/state?status=trial").json()
    assert state["total"] == 1
    assert state["items"][0]["stock_code"] == "600000"
    assert state["items"][0]["quant_status"] == "trial"
    assert state["items"][0]["health_score"] == 66

    settings = client.get("/api/v1/quant/universe/settings").json()
    assert settings["auto_entry_mode"] == "confirm_first"
    updated_settings = client.post(
        "/api/v1/quant/universe/settings",
        json={"auto_entry_mode": "auto_trial", "auto_exit_enabled": False},
    ).json()
    assert updated_settings["auto_entry_mode"] == "auto_trial"
    assert updated_settings["auto_exit_enabled"] is False

    overview = client.get("/api/v1/quant/universe/overview").json()
    pending_item = overview["cards"]["pending_eligible"]["top_items"][0]
    assert pending_item == {
        "stock_code": "600001",
        "stock_name": "邯郸钢铁",
        "latest_reason": "主力共振",
    }
    assert "latest_price" not in pending_item
    assert "kline" not in pending_item


def test_quant_universe_action_endpoints(tmp_path):
    context = _context(tmp_path)
    db = context.quant_db()
    db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    db.add_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "discover",
            "source_key": "main_force",
            "source_score": 0.95,
            "confidence": 0.9,
            "trend": "up",
            "reason_text": "候选达标",
            "status": "eligible",
        }
    )
    db.add_watch(stock_code="600001", stock_name="邯郸钢铁", source="discover")
    db.add_candidate_event(
        {
            "stock_code": "600001",
            "source_type": "discover",
            "source_score": 0.9,
            "confidence": 0.8,
            "trend": "up",
            "status": "eligible",
        }
    )
    client = TestClient(create_app(context=context))

    promoted = client.post(
        "/api/v1/quant/universe/actions/promote-to-trial",
        json={"stock_codes": ["600000"], "source_type": "manual"},
    ).json()
    assert promoted["success"] == [{"stock_code": "600000", "new_status": "trial"}]
    assert db.get_quant_universe_state("600000")["quant_status"] == "trial"

    ignored = client.post(
        "/api/v1/quant/universe/actions/ignore-auto-entry",
        json={"stock_codes": ["600001"], "source_type": "discover"},
    ).json()
    assert ignored["success"] == ["600001"]

    override = client.post(
        "/api/v1/quant/universe/actions/set-override",
        json={"stock_code": "600000", "override_type": "manual_pause"},
    ).json()
    assert override["quant_status"] == "manual_paused"
    assert override["quant_manual_override"] == "manual_pause"

    restored = client.post(
        "/api/v1/quant/universe/actions/restore-to-trial",
        json={"stock_code": "600000"},
    ).json()
    assert restored == {"stock_code": "600000", "old_status": "manual_paused", "new_status": "trial"}


def test_quant_universe_restore_to_trial_returns_400_for_active_stock(tmp_path):
    context = _context(tmp_path)
    db = context.quant_db()
    db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    db.upsert_quant_universe_state("600000", {"quant_status": "active"})
    client = TestClient(create_app(context=context))

    response = client.post(
        "/api/v1/quant/universe/actions/restore-to-trial",
        json={"stock_code": "600000"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error_code": "invalid_restore_state",
        "error_message": "股票当前处于 active，无需恢复",
    }
