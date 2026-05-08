from app.quant_sim.quant_universe_notifications import (
    build_quant_universe_daily_summary,
    build_quant_universe_retired_notification,
)
from app.notification_service import notification_service
from app.quant_sim.scheduler import QuantSimScheduler


def _event(code: str, from_status: str, to_status: str, **overrides):
    payload = {
        "stock_code": code,
        "stock_name": f"{code}股份",
        "from_status": from_status,
        "to_status": to_status,
        "reason_text": f"{from_status}->{to_status}",
        "candidate_score": 0.71,
        "health_score_before": 55.0,
        "health_score_after": 42.5,
        "manual_override": "none",
        "created_at": "2026-05-08T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_daily_summary_groups_lifecycle_events_and_limits_rows():
    events = [
        *[_event(f"600{i:03d}", "inactive", "trial") for i in range(12)],
        _event("601001", "trial", "active"),
        _event("601002", "active", "exit_only"),
        _event("601003", "active", "cooling"),
        _event("601004", "cooling", "retired"),
        _event("601005", "cooling", "trial"),
    ]

    summary = build_quant_universe_daily_summary(events)

    assert summary is not None
    assert summary["symbol"] == "QUANT_UNIVERSE"
    assert summary["type"] == "量化池生命周期日报"
    assert set(summary["groups"]) == {
        "new_trial",
        "upgraded_active",
        "downgraded_exit_only",
        "entered_cooling",
        "entered_retired",
        "recovered_from_cooling",
    }
    trial_group = summary["groups"]["new_trial"]
    assert len(trial_group["rows"]) == 10
    assert trial_group["overflow_count"] == 2
    first = trial_group["rows"][0]
    assert first == {
        "stock_code": "600000",
        "stock_name": "600000股份",
        "from_status": "inactive",
        "to_status": "trial",
        "status_change": "inactive -> trial",
        "reason": "inactive->trial",
        "candidate_score": 0.71,
        "health_score_before": 55.0,
        "health_score_after": 42.5,
        "health_delta": -12.5,
        "manual_override": "none",
    }


def test_daily_summary_returns_none_for_empty_events():
    assert build_quant_universe_daily_summary([]) is None


def test_retired_notification_payload_contains_key_lifecycle_context():
    payload = build_quant_universe_retired_notification(
        _event(
            "603000",
            "cooling",
            "retired",
            stock_name="生命周期样本",
            reason_text="冷却后仍未恢复",
            health_score_before=30,
            health_score_after=18,
            manual_override="manual_pin",
        )
    )

    assert payload["symbol"] == "603000"
    assert payload["name"] == "生命周期样本"
    assert payload["type"] == "量化池退出"
    assert "cooling -> retired" in payload["message"]
    assert "冷却后仍未恢复" in payload["message"]
    assert payload["lifecycle"]["manual_override"] == "manual_pin"
    assert payload["lifecycle"]["health_delta"] == -12.0


def test_scheduler_dispatches_retired_lifecycle_notification(tmp_path, monkeypatch):
    scheduler = QuantSimScheduler(db_file=tmp_path / "quant_sim.db")
    sent: list[dict] = []
    monkeypatch.setattr(notification_service, "send_notification", lambda payload: sent.append(payload) or True)

    scheduler._dispatch_lifecycle_notifications(
        [
            _event("603001", "cooling", "retired", stock_name="退场样本"),
            _event("603002", "trial", "active", stock_name="升级样本"),
        ]
    )

    assert len(sent) == 1
    assert sent[0]["symbol"] == "603001"
    assert sent[0]["type"] == "量化池退出"
