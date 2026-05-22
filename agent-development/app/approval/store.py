from __future__ import annotations

"""In-memory approval request store for the MVP."""

from datetime import UTC, datetime

from app.schemas.approval import ApprovalRequest, ApprovalStatus


class InMemoryApprovalStore:
    """Local approval state flow.  No UI integration in phase one."""

    def __init__(self) -> None:
        self._items: dict[str, ApprovalRequest] = {}

    def create(self, request: ApprovalRequest) -> ApprovalRequest:
        self._items[request.approval_id] = request
        return request

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self._items.get(approval_id)

    def update_status(self, approval_id: str, status: ApprovalStatus) -> ApprovalRequest:
        item = self._items[approval_id]
        item.status = status
        item.updated_at = datetime.now(UTC).isoformat()
        return item
