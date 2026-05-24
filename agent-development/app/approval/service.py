from __future__ import annotations

"""Human approval workflow service."""

import json
from datetime import UTC, datetime
from uuid import uuid4
from typing import Any

from app.approval.client import ApprovalSystemClient
from app.approval.store import SQLiteApprovalStore
from app.compliance.final_checker import FinalComplianceChecker
from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.schemas.agent_card import AgentCard
from app.schemas.approval import (
    ApprovalCallbackHandleResult,
    ApprovalCallbackRequest,
    ApprovalRequest,
    ApprovalResumeResult,
    ApprovalSubmitResult,
)
from app.session.message_store import MessageStore
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.executor import ToolExecutor


class ApprovalService:
    """Creates approvals, submits them externally, and resumes approved flows."""

    def __init__(
        self,
        *,
        store: SQLiteApprovalStore,
        client: ApprovalSystemClient,
        tool_executor: ToolExecutor,
        tool_calling_runner: ToolCallingRunner,
        final_compliance_checker: FinalComplianceChecker,
        message_store: MessageStore,
        short_memory: ShortTermMemoryManager,
        callback_url: str,
    ) -> None:
        self.store = store
        self.client = client
        self.tool_executor = tool_executor
        self.tool_calling_runner = tool_calling_runner
        self.final_compliance_checker = final_compliance_checker
        self.message_store = message_store
        self.short_memory = short_memory
        self.callback_url = callback_url

    async def create_approval_request(
        self,
        *,
        session_key: str,
        request_id: str,
        trace_id: str | None,
        agent_name: str,
        tool_name: str,
        operation_type: str,
        risk_level: str,
        arguments: dict[str, Any],
        reason: str,
        pending_state: dict[str, Any],
        pending_messages: list[dict[str, Any]],
        pending_tools: list[dict[str, Any]],
        pending_tool_call: dict[str, Any],
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            approval_id=f"approval_{uuid4().hex}",
            session_key=session_key,
            request_id=request_id,
            trace_id=trace_id,
            agent_name=agent_name,
            tool_name=tool_name,
            operation_type=operation_type,
            risk_level=risk_level,
            arguments=arguments,
            reason=reason,
            callback_url=self.callback_url,
            pending_state=pending_state,
            pending_messages=pending_messages,
            pending_tools=pending_tools,
            pending_tool_call=pending_tool_call,
        )
        return await self.store.create(request)

    async def submit_to_external_approval_system(self, approval_request: ApprovalRequest) -> ApprovalSubmitResult:
        result = await self.client.submit_approval_request(approval_request)
        if result.accepted:
            approval_request.status = "pending"
            approval_request.external_approval_id = result.external_approval_id
            await self.store.update(
                approval_request,
                event_type="submitted",
                payload=result.model_dump(),
            )
            return result

        approval_request.status = "submit_failed"
        approval_request.error = result.error or "approval_submit_failed"
        await self.store.update(
            approval_request,
            event_type="submit_failed",
            payload=result.model_dump(),
        )
        return result

    async def handle_callback(self, callback: ApprovalCallbackRequest) -> ApprovalCallbackHandleResult:
        approval_request = await self.store.get(callback.approval_id)
        if approval_request is None:
            raise KeyError(callback.approval_id)

        if approval_request.status in {"completed", "rejected"}:
            return ApprovalCallbackHandleResult(
                approval_request=approval_request,
                resumed=False,
                final_answer=approval_request.final_answer,
                error=approval_request.error,
                already_processed=True,
            )

        approval_request.external_approval_id = callback.external_approval_id or approval_request.external_approval_id
        approval_request.approver = callback.approver
        approval_request.comment = callback.comment
        approval_request.decided_at = callback.decided_at or self._now()

        if callback.status == "rejected":
            final_answer = await self._finalize_rejected(approval_request)
            return ApprovalCallbackHandleResult(
                approval_request=approval_request,
                resumed=True,
                final_answer=final_answer,
            )

        approval_request.status = "approved"
        await self.store.update(
            approval_request,
            event_type="approved",
            payload=callback.model_dump(),
        )
        resume = await self.resume_after_approval(approval_request)
        refreshed = await self.store.get(callback.approval_id) or approval_request
        return ApprovalCallbackHandleResult(
            approval_request=refreshed,
            resumed=True,
            final_answer=resume.final_answer,
            error=resume.error,
        )

    async def resume_after_approval(self, approval_request: ApprovalRequest) -> ApprovalResumeResult:
        pending_state = approval_request.pending_state
        pending_messages = list(approval_request.pending_messages)
        pending_tools = list(approval_request.pending_tools)
        pending_tool_call = approval_request.pending_tool_call
        agent_card = self._agent_card_from_state(pending_state)
        tool_call_id = pending_tool_call.get("tool_call_id") or pending_tool_call.get("id") or f"approved_{approval_request.approval_id}"

        tool_result = await self.tool_executor.execute_approved_tool(
            approval_id=approval_request.approval_id,
            agent_name=approval_request.agent_name,
            tool_name=approval_request.tool_name,
            arguments=approval_request.arguments,
            session_key=approval_request.session_key or "",
            request_id=approval_request.request_id or "",
            trace_id=approval_request.trace_id,
            agent_card=agent_card,
        )
        dumped_tool_result = tool_result.model_dump()
        pending_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": approval_request.tool_name,
                "content": json.dumps(dumped_tool_result, ensure_ascii=False, default=str),
            }
        )

        run_result = await self.tool_calling_runner.run(
            agent_name=approval_request.agent_name,
            messages=pending_messages,
            tools=pending_tools,
            session_key=approval_request.session_key or "",
            request_id=approval_request.request_id or "",
            trace_id=approval_request.trace_id,
            agent_card=agent_card,
        )
        final_answer = run_result.final_answer or run_result.error or "审批通过后继续执行失败。"
        final_answer = await self._sanitize_and_persist_answer(
            approval_request=approval_request,
            raw_answer=final_answer,
            subagent_result={"tool_result": dumped_tool_result, "runner": run_result.model_dump()},
        )
        approval_request.status = "completed"
        approval_request.result = {
            "tool_result": dumped_tool_result,
            "runner": run_result.model_dump(),
        }
        approval_request.final_answer = final_answer
        approval_request.error = run_result.error if run_result.stopped_reason != "final" else None
        await self.store.update(
            approval_request,
            event_type="completed",
            payload={"final_answer": final_answer, "tool_result": dumped_tool_result},
        )
        return ApprovalResumeResult(
            approval_id=approval_request.approval_id,
            status=approval_request.status,
            final_answer=final_answer,
            error=approval_request.error,
            tool_result=dumped_tool_result,
        )

    async def _finalize_rejected(self, approval_request: ApprovalRequest) -> str:
        raw_answer = "审批未通过，相关操作未执行。"
        final_answer = await self._sanitize_and_persist_answer(
            approval_request=approval_request,
            raw_answer=raw_answer,
            subagent_result={"approval_status": "rejected"},
        )
        approval_request.status = "rejected"
        approval_request.final_answer = final_answer
        approval_request.result = {"approval_status": "rejected"}
        await self.store.update(
            approval_request,
            event_type="rejected",
            payload={"final_answer": final_answer, "approver": approval_request.approver, "comment": approval_request.comment},
        )
        return final_answer

    async def _sanitize_and_persist_answer(
        self,
        *,
        approval_request: ApprovalRequest,
        raw_answer: str,
        subagent_result: dict[str, Any],
    ) -> str:
        compliance = await self.final_compliance_checker.check(raw_answer)
        final_answer = compliance.sanitized_answer if compliance.passed else compliance.fallback_answer
        pending_state = approval_request.pending_state
        await self.message_store.append(
            session_key=approval_request.session_key or "",
            role="assistant",
            content=final_answer,
            metadata={
                "request_id": approval_request.request_id,
                "trace_id": approval_request.trace_id,
                "original_query": pending_state.get("original_query"),
                "rewritten_query": pending_state.get("rewritten_query"),
                "intent": pending_state.get("intent"),
                "entities": pending_state.get("entities", {}),
                "selected_agent": approval_request.agent_name,
                "session_key": approval_request.session_key,
                "approval_id": approval_request.approval_id,
                "approval_status": approval_request.status,
            },
        )
        await self.short_memory.compress_after_turn(
            session_key=approval_request.session_key or "",
            original_query=pending_state.get("original_query", ""),
            rewritten_query=pending_state.get("rewritten_query", pending_state.get("original_query", "")),
            intent=pending_state.get("intent", "unknown"),
            answer=final_answer,
            subagent_result=subagent_result,
        )
        return final_answer

    @staticmethod
    def _agent_card_from_state(state: dict[str, Any]) -> AgentCard | None:
        data = state.get("selected_agent_card")
        return AgentCard(**data) if isinstance(data, dict) else None

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
