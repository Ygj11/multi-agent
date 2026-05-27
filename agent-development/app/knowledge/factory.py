from __future__ import annotations

"""KnowledgeService factory."""

from app.config.settings import Settings
from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.integrations.knowledge_api_client import KnowledgeAPIClient
from app.knowledge.disabled_service import DisabledKnowledgeService
from app.knowledge.service import KnowledgeService


def build_knowledge_service(settings: Settings) -> KnowledgeService:
    """Build the configured KnowledgeService implementation."""
    if not settings.enable_knowledge_api:
        return DisabledKnowledgeService()
    if not settings.knowledge_api_url:
        raise ValueError("ENABLE_KNOWLEDGE_API=true requires KNOWLEDGE_API_URL.")
    return KnowledgeAPIClient(
        BaseIntegrationHTTPClient(
            base_url=settings.knowledge_api_url,
            timeout=settings.knowledge_api_timeout,
        )
    )
