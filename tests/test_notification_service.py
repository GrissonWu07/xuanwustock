from app.notification_service import NotificationService


def _reset_webhook_env(monkeypatch) -> None:
    for key in ("WEBHOOK_ENABLED", "WEBHOOK_TYPE", "WEBHOOK_URL", "WEBHOOK_KEYWORD"):
        monkeypatch.delenv(key, raising=False)


def test_notification_service_auto_detects_feishu_url(monkeypatch):
    _reset_webhook_env(monkeypatch)
    monkeypatch.setenv("WEBHOOK_ENABLED", "true")
    monkeypatch.setenv("WEBHOOK_TYPE", "dingtalk")
    monkeypatch.setenv("WEBHOOK_URL", "https://open.feishu.cn/open-apis/bot/v2/hook/test-token")

    service = NotificationService()

    assert service.config["webhook_type"] == "feishu"


def test_notification_service_routes_by_detected_webhook_type(monkeypatch):
    _reset_webhook_env(monkeypatch)
    monkeypatch.setenv("WEBHOOK_ENABLED", "true")
    monkeypatch.setenv("WEBHOOK_TYPE", "dingtalk")
    monkeypatch.setenv("WEBHOOK_URL", "https://open.feishu.cn/open-apis/bot/v2/hook/test-token")

    service = NotificationService()
    calls: list[str] = []

    monkeypatch.setattr(service, "_send_dingtalk_webhook", lambda notification: calls.append("dingtalk") or True)
    monkeypatch.setattr(service, "_send_feishu_webhook", lambda notification: calls.append("feishu") or True)

    success = service._send_webhook_notification(
        {
            "symbol": "600000",
            "name": "浦发银行",
            "type": "测试",
            "message": "测试 webhook 路由",
            "triggered_at": "2026-04-23 23:20:00",
        }
    )

    assert success is True
    assert calls == ["feishu"]
