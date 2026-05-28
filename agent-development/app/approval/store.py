from __future__ import annotations

"""SQLite approval request store."""

import json
from datetime import UTC, datetime
from typing import Any

from app.config.settings import get_settings
from app.schemas.approval import ApprovalRequest, ApprovalStatus
from app.storage.sqlite import SQLiteDatabase


class SQLiteApprovalStore:
    """Persistent approval state flow used by callback-based resumes."""

    def __init__(self, db: SQLiteDatabase | None = None) -> None:
        self.db = db or SQLiteDatabase(get_settings().sqlite_db_path)

    async def create(self, request: ApprovalRequest) -> ApprovalRequest:
        def write(conn):
            conn.execute(
                """
                INSERT INTO approval_requests(
                    approval_id, external_approval_id, session_key, request_id, trace_id,
                    agent_name, tool_name, operation_type, risk_level, arguments_json,
                    reason, status, callback_url, pending_state_json, pending_messages_json,
                    pending_tools_json, pending_tool_call_json, result_json, final_answer,
                    error, approver, comment, created_at, updated_at, decided_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._request_values(request),
            )

        await self.db.run(write)
        await self.append_event(request.approval_id, "created", request.model_dump())
        return request

    async def get(self, approval_id: str) -> ApprovalRequest | None:
        def read(conn):
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            return self._row_to_request(row) if row else None

        return await self.db.run(read)

    async def update(self, request: ApprovalRequest, event_type: str | None = None, payload: dict[str, Any] | None = None) -> ApprovalRequest:
        request.updated_at = self._now()

        def write(conn):
            conn.execute(
                """
                UPDATE approval_requests
                SET external_approval_id = ?, session_key = ?, request_id = ?, trace_id = ?,
                    agent_name = ?, tool_name = ?, operation_type = ?, risk_level = ?,
                    arguments_json = ?, reason = ?, status = ?, callback_url = ?,
                    pending_state_json = ?, pending_messages_json = ?, pending_tools_json = ?,
                    pending_tool_call_json = ?, result_json = ?, final_answer = ?, error = ?,
                    approver = ?, comment = ?, updated_at = ?, decided_at = ?
                WHERE approval_id = ?
                """,
                (
                    request.external_approval_id,
                    request.session_key,
                    request.request_id,
                    request.trace_id,
                    request.agent_name,
                    request.tool_name,
                    request.operation_type,
                    request.risk_level,
                    self._to_json(request.arguments),
                    request.reason,
                    request.status,
                    request.callback_url,
                    self._to_json(request.pending_state),
                    self._to_json(request.pending_messages),
                    self._to_json(request.pending_tools),
                    self._to_json(request.pending_tool_call),
                    self._to_json(request.result) if request.result is not None else None,
                    request.final_answer,
                    request.error,
                    request.approver,
                    request.comment,
                    request.updated_at,
                    request.decided_at,
                    request.approval_id,
                ),
            )

        await self.db.run(write)
        if event_type:
            await self.append_event(request.approval_id, event_type, payload or request.model_dump())
        return request

    async def update_status(self, approval_id: str, status: ApprovalStatus) -> ApprovalRequest:
        request = await self.get(approval_id)
        if request is None:
            raise KeyError(approval_id)
        request.status = status
        return await self.update(request, event_type=f"status_{status}", payload={"status": status})

    async def append_event(self, approval_id: str, event_type: str, payload: dict[str, Any]) -> None:
        created_at = self._now()

        def write(conn):
            conn.execute(
                """
                INSERT INTO approval_events(approval_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (approval_id, event_type, self._to_json(payload), created_at),
            )

        await self.db.run(write)

    async def list_events(self, approval_id: str) -> list[dict[str, Any]]:
        def read(conn):
            rows = conn.execute(
                """
                SELECT event_id, approval_id, event_type, payload_json, created_at
                FROM approval_events
                WHERE approval_id = ?
                ORDER BY event_id ASC
                """,
                (approval_id,),
            ).fetchall()
            return [
                {
                    "event_id": row["event_id"],
                    "approval_id": row["approval_id"],
                    "event_type": row["event_type"],
                    "payload": json.loads(row["payload_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

        return await self.db.run(read)

    @classmethod
    def _request_values(cls, request: ApprovalRequest) -> tuple[Any, ...]:
        return (
            request.approval_id,
            request.external_approval_id,
            request.session_key,
            request.request_id,
            request.trace_id,
            request.agent_name,
            request.tool_name,
            request.operation_type,
            request.risk_level,
            cls._to_json(request.arguments),
            request.reason,
            request.status,
            request.callback_url,
            cls._to_json(request.pending_state),
            cls._to_json(request.pending_messages),
            cls._to_json(request.pending_tools),
            cls._to_json(request.pending_tool_call),
            cls._to_json(request.result) if request.result is not None else None,
            request.final_answer,
            request.error,
            request.approver,
            request.comment,
            request.created_at,
            request.updated_at,
            request.decided_at,
        )

    @classmethod
    def _row_to_request(cls, row) -> ApprovalRequest:
        return ApprovalRequest(
            approval_id=row["approval_id"],
            external_approval_id=row["external_approval_id"],
            session_key=row["session_key"],
            request_id=row["request_id"],
            trace_id=row["trace_id"],
            agent_name=row["agent_name"],
            tool_name=row["tool_name"],
            operation_type=row["operation_type"],
            risk_level=row["risk_level"],
            arguments=json.loads(row["arguments_json"]),
            reason=row["reason"],
            status=row["status"],
            callback_url=row["callback_url"],
            pending_state=json.loads(row["pending_state_json"]),
            pending_messages=json.loads(row["pending_messages_json"]),
            pending_tools=json.loads(row["pending_tools_json"]),
            pending_tool_call=json.loads(row["pending_tool_call_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            final_answer=row["final_answer"],
            error=row["error"],
            approver=row["approver"],
            comment=row["comment"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            decided_at=row["decided_at"],
        )

    @staticmethod
    def _to_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
