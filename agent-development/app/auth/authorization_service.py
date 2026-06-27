from __future__ import annotations

"""Agent、Tool 和资源访问的确定性授权服务。"""

from typing import Any

from pydantic import BaseModel, Field

from app.auth.principal import Principal
from app.schemas.agent_card import AgentCard
from app.tools.base import ToolDefinition


class AuthorizationDecision(BaseModel):
    allowed: bool
    reason: str | None = None
    missing_scopes: list[str] = Field(default_factory=list)
    missing_data_permissions: list[str] = Field(default_factory=list)
    denied_by: str | None = None


class AuthorizationService:
    """服务端确定性授权检查。

    授权判断不能交给 LLM：Agent 入口权限、工具 scope 权限和资源归属都必须
    由代码根据可信 Principal 与配置策略判断。资源级组织/数据边界由
    ResourceAccessService 处理，避免复制工具定义。
    """

    def check_agent_access(self, *, principal: Principal | None, agent_card: AgentCard) -> AuthorizationDecision:
        """
        YAML 不声明 access_policy，表示该 Agent 不增加任何 AgentCard 级别的访问限制，任何 Principal 都可以通过这一层检查，包括 principal=None。

        access_policy:
          required_roles:
            - operations_engineer
            - insurance_admin

          required_scopes:
            - agent:troubleshooting:access
            - policy:read

          required_data_permissions:
            - troubleshooting:diagnose

          allowed_org_types:
            - head_office
            - branch

          allowed_org_ids:
            - ORG_001
            - ORG_002

          denied_org_ids:
            - ORG_TEST

        """
        policy = agent_card.access_policy
        required_roles = set(policy.required_roles)
        required_scopes = set(policy.required_scopes)
        required_data_permissions = set(policy.required_data_permissions)
        allowed_org_types = set(policy.allowed_org_types)
        allowed_org_ids = set(policy.allowed_org_ids)
        denied_org_ids = set(policy.denied_org_ids)
        if (
            not required_roles
            and not required_scopes
            and not required_data_permissions
            and not allowed_org_types
            and not allowed_org_ids
            and not denied_org_ids
        ):
            return AuthorizationDecision(allowed=True)
        if principal is None:
            return AuthorizationDecision(allowed=False, reason="principal_required", denied_by="agent_access")
        if denied_org_ids and principal.org_id in denied_org_ids:
            return AuthorizationDecision(allowed=False, reason="org_id_denied", denied_by="agent_access")
        if allowed_org_ids and principal.org_id not in allowed_org_ids:
            return AuthorizationDecision(allowed=False, reason="org_id_not_allowed", denied_by="agent_access")
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
        missing_data_permissions = sorted(required_data_permissions.difference(principal.data_permissions))
        if missing_data_permissions:
            return AuthorizationDecision(
                allowed=False,
                reason="missing_required_data_permission",
                missing_data_permissions=missing_data_permissions,
                denied_by="agent_access",
            )
        org_type = str(principal.attributes.get("org_type") or "")
        if allowed_org_types and org_type not in allowed_org_types:
            return AuthorizationDecision(allowed=False, reason="org_type_not_allowed", denied_by="agent_access")
        return AuthorizationDecision(allowed=True)

    def check_tool_access(self, *, principal: Principal | None, tool_definition: ToolDefinition) -> AuthorizationDecision:
        # 默认不拦截
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
    """MVP resource access service for organization/resource boundaries.

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
