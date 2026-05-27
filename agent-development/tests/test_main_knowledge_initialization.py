from fastapi.testclient import TestClient

from app.integrations.knowledge_api_client import KnowledgeAPIClient
from app.knowledge.disabled_service import DisabledKnowledgeService


def test_create_app_uses_disabled_knowledge_service_by_default(app_factory):
    app = app_factory("knowledge-default.sqlite3")

    assert isinstance(app.state.knowledge_service, DisabledKnowledgeService)


def test_create_app_can_use_knowledge_api_client_when_factory_returns_it(app_factory, monkeypatch):
    from app.config.settings import Settings
    from app.knowledge.factory import build_knowledge_service

    service = build_knowledge_service(
        Settings(enable_knowledge_api=True, knowledge_api_url="https://knowledge.example.test")
    )

    monkeypatch.setattr("app.main.build_knowledge_service", lambda settings: service)
    app = app_factory("knowledge-enabled.sqlite3")

    assert isinstance(app.state.knowledge_service, KnowledgeAPIClient)
    response = TestClient(app).post(
        "/api/chat",
        json={
            "tenant_id": "tenant",
            "channel": "web",
            "user_id": "user",
            "session_id": "session",
            "messages": [{"role": "user", "content": "查询保单 P123456"}],
        },
    )
    assert response.status_code == 200
