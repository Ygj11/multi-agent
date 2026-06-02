from __future__ import annotations

"""Authorization services for agent, tool, and resource access."""

from typing import Any

from pydantic import BaseModel, Field

from app.auth.principal import Principal
from app.schemas.agent_card import AgentCard
from app.tools.base import ToolDefinition


class AuthorizationDecision(BaseModel):
    allowed: bool
    reason: str | None = None
    missing_scopes: list[str] = Field(default_factory=list)
    denied_by: str | None = None


class AuthorizationService:
    """Deterministic, service-side authorization checks."""

    def check_agent_access(self, *, principal: Principal | None, agent_card: AgentCard) -> AuthorizationDecision:
        policy = getattr(agent_card, "access_policy", {}) or {}
        required_roles = set(policy.get("required_roles") or [])
        required_scopes = set(policy.get("required_scopes") or [])
        allowed_org_types = set(policy.get("allowed_org_types") or [])
        if not required_roles and not required_scopes and not allowed_org_types:
            return AuthorizationDecision(allowed=True)
        if principal is None:
            return AuthorizationDecision(allowed=False, reason="principal_required", denied_by="agent_access")
        if required_roles and not required_roles.intersection(principal.roles):
            return AuthorizationDecision(allowed=False, reason="missing_required_role", denied_by="agent_access")
        missing_scopes = sorted(required_scopes.difference(principal.scopes))
        if missing_scopes:
            return AuthorizationDecision(
                allowed=False,
                reason="missing_required_scope",
                missing_scopes=missing_scopes,
                denied_by="agent_access",
            )
        org_type = str(principal.attributes.get("org_type") or "")
        if allowed_org_types and org_type not in allowed_org_types:
            return AuthorizationDecision(allowed=False, reason="org_type_not_allowed", denied_by="agent_access")
        return AuthorizationDecision(allowed=True)

    def check_tool_access(self, *, principal: Principal | None, tool_definition: ToolDefinition) -> AuthorizationDecision:
        required_scopes = set(tool_definition.required_scopes or [])
        if not required_scopes:
            return AuthorizationDecision(allowed=True)
        if principal is None:
            return AuthorizationDecision(allowed=False, reason="principal_required", denied_by="tool_access")
        missing_scopes = sorted(required_scopes.difference(principal.scopes))
        if missing_scopes:
            return AuthorizationDecision(
                allowed=False,
                reason="missing_required_scope",
                missing_scopes=missing_scopes,
                denied_by="tool_access",
            )
        return AuthorizationDecision(allowed=True)


class ResourceAccessService:
    """MVP resource access service.

    The enterprise version should delegate to an organization/resource policy
    service. This local implementation supports allowlists in principal
    attributes, e.g. {"policy_allowlist": ["P001"]}.
    """

    async def check_access(
        self,
        *,
        principal: Principal | None,
        resource_type: str | None,
        resource_id: str | None,
        action: str = "read",
    ) -> AuthorizationDecision:
        if not resource_type or not resource_id:
            return AuthorizationDecision(allowed=True)
        if principal is None:
            return AuthorizationDecision(allowed=False, reason="principal_required", denied_by="resource_access")

        allowlist_key = f"{resource_type}_allowlist"
        allowlist = principal.attributes.get(allowlist_key)
        if isinstance(allowlist, list) and allowlist and resource_id not in {str(item) for item in allowlist}:
            return AuthorizationDecision(allowed=False, reason="resource_not_allowed", denied_by="resource_access")
        return AuthorizationDecision(allowed=True)

