from __future__ import annotations

"""FastAPI dependencies for resolving trusted principals."""

from typing import Annotated

from fastapi import Header, HTTPException

from app.auth.principal import Principal
from app.config.settings import get_settings


def _split_header(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


async def get_current_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_subject: Annotated[str | None, Header()] = None,
    x_org_id: Annotated[str | None, Header()] = None,
    x_org_path: Annotated[str | None, Header()] = None,
    x_branch_code: Annotated[str | None, Header()] = None,
    x_channel: Annotated[str | None, Header()] = None,
    x_user_roles: Annotated[str | None, Header()] = None,
    x_user_scopes: Annotated[str | None, Header()] = None,
    x_data_permissions: Annotated[str | None, Header()] = None,
) -> Principal | None:
    """Resolve the trusted principal.

    MVP supports trusted development headers. If no auth headers are present,
    dev mode returns None so the request adapter can use the legacy body
    identity as a local fallback.
    """
    settings = get_settings()
    has_header_identity = bool(x_tenant_id or x_user_id or x_subject or authorization)
    if not has_header_identity:
        if settings.auth_mode in {"required", "jwt"}:
            raise HTTPException(status_code=401, detail="authentication_required")
        return None

    if not x_tenant_id:
        raise HTTPException(status_code=401, detail="x-tenant-id_required")
    subject = x_subject or x_user_id
    if not subject:
        raise HTTPException(status_code=401, detail="x-user-id_or_x-subject_required")

    return Principal(
        tenant_id=x_tenant_id,
        subject=subject,
        user_id=x_user_id,
        org_id=x_org_id,
        org_path=_split_header(x_org_path),
        branch_code=x_branch_code,
        channel=x_channel,
        roles=_split_header(x_user_roles),
        scopes=_split_header(x_user_scopes),
        data_permissions=_split_header(x_data_permissions),
    )

