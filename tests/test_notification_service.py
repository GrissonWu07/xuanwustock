from app.notification_service import NotificationService
import app.notification_research as notification_research


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


def test_notification_service_sends_research_completion_to_email_and_webhook(monkeypatch):
    _reset_webhook_env(monkeypatch)
    monkeypatch.setenv("EMAIL_ENABLED", "true")
    monkeypatch.setenv("SMTP_SERVER", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_TO", "to@example.com")
    monkeypatch.setenv("WEBHOOK_ENABLED", "true")
    monkeypatch.setenv("WEBHOOK_TYPE", "feishu")
    monkeypatch.setenv("WEBHOOK_URL", "https://open.feishu.cn/open-apis/bot/v2/hook/test-token")

    service = NotificationService()
    emails: list[tuple[str, str, str]] = []
    webhooks: list[tuple[str, str]] = []
    monkeypatch.setattr(service, "_send_custom_email", lambda subject, html, text: emails.append((subject, html, text)) or True)
    monkeypatch.setattr(notification_research, "_send_webhook", lambda service, subject, text, **kwargs: webhooks.append((subject, text)) or True)

    success = service.send_research_notification(
        {
            "updatedAt": "2026-04-29 10:00:00",
            "modules": [{"name": "新闻流量", "note": "产业链热度提升", "output": "股票输出 1 只"}],
            "marketView": [{"title": "市场情绪", "body": "震荡偏强"}],
            "outputTable": {
                "rows": [{"code": "600519", "name": "贵州茅台", "source": "新闻流量", "reason": "热度提升"}]
            },
            "summary": {"body": "已刷新 1 个研究模块，其中 1 只股票有明确输出。"},
        },
        task_id="research_1",
        selected_modules=["news"],
    )

    assert success is True
    assert emails and "研究情报完成 - 1只股票输出" in emails[0][0]
    assert "600519" in emails[0][2]
    assert webhooks and "研究情报完成 - 1只股票输出" in webhooks[0][0]
