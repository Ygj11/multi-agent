import pytest

from app.config.settings import Settings
from app.integrations.knowledge_api_client import KnowledgeAPIClient
from app.knowledge.disabled_service import DisabledKnowledgeService
from app.knowledge.factory import build_knowledge_service


def test_factory_returns_disabled_service_by_default():
    service = build_knowledge_service(Settings(enable_knowledge_api=False))

    assert isinstance(service, DisabledKnowledgeService)


def test_factory_returns_knowledge_api_client_when_enabled():
    service = build_knowledge_service(
        Settings(enable_knowledge_api=True, knowledge_api_url="https://knowledge.example.test")
    )

    assert isinstance(service, KnowledgeAPIClient)
    assert service.http.base_url == "https://knowledge.example.test"


def test_factory_requires_url_when_enabled():
    with pytest.raises(ValueError, match="KNOWLEDGE_API_URL"):
        build_knowledge_service(Settings(enable_knowledge_api=True, knowledge_api_url=None))
