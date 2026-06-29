from __future__ import annotations

"""Trusted request principal schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Principal(BaseModel):
    """Trusted access subject derived from headers, JWT, or a gateway."""

    tenant_id: str
    subject: str
    user_id: str | None = None
    org_id: str | None = None
    org_path: list[str] = Field(default_factory=list)
    branch_code: str | None = None
    channel: str | None = None
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    data_permissions: list[str] = Field(default_factory=list)
    resource_domains: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def effective_user_id(self) -> str:
        return self.user_id or self.subject


class AuthContext(BaseModel):
    """Serializable authentication context propagated through graph state."""

    principal: Principal
    auth_source: Literal["gateway", "jwt", "dev_header", "body_fallback", "service_account"] = "dev_header"
    raw_claims: dict[str, Any] = Field(default_factory=dict) # 认证系统返回的原始声明信息
    authenticated_at: str | None = None  # 本次身份认证发生的时间


def principal_from_auth_context(value: AuthContext | dict[str, Any] | None) -> Principal | None:
    """Extract the trusted Principal from an AuthContext payload."""
    if value is None:
        return None
    if isinstance(value, AuthContext):
        return value.principal
    if not isinstance(value, dict):
        return None
    principal_data = value.get("principal")
    if isinstance(principal_data, Principal):
        return principal_data
    if isinstance(principal_data, dict):
        try:
            return Principal(**principal_data)
        except Exception:
            return None
    return None


def principal_dict_from_auth_context(value: AuthContext | dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a serializable Principal dict from an AuthContext payload."""
    principal = principal_from_auth_context(value)
    return principal.model_dump() if principal else None
