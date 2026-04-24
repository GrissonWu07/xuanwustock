import pytest

from app.notification_service import notification_service


@pytest.fixture(autouse=True)
def block_global_notification_delivery(monkeypatch):
    monkeypatch.setattr(notification_service, "send_notification", lambda payload: False)
