from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.runtime.session_locks import SessionExecutionLockTimeout


def test_chat_returns_409_when_session_lock_times_out(monkeypatch):
    class TimeoutOrchestrator:
        async def run(self, inbound):
            raise SessionExecutionLockTimeout(inbound.session_key, 0.01)

    class FakeContainer:
        def __init__(self) -> None:
            self.orchestrator = TimeoutOrchestrator()
            self.approval_service = SimpleNamespace()
            self.storage = SimpleNamespace(approval_store=SimpleNamespace())

        async def startup(self) -> None:
            return None

        async def shutdown(self) -> None:
            return None

    monkeypatch.setattr("app.main.build_app_container", lambda settings, sqlite_db_path=None: FakeContainer())

    from app.main import create_app

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/chat",
            json={
                "tenant_id": "tenant",
                "channel": "web",
                "user_id": "u1",
                "session_id": "s1",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 409
    assert "上一条请求仍在处理中" in response.json()["detail"]
