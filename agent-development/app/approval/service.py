from __future__ import annotations

"""人工审批工作流服务。"""

from datetime import UTC, datetime
from uuid import uuid4
from typing import Any

from app.approval.client import ApprovalSystemClient
from app.approval.store import SQLiteApprovalStore
from app.auth.principal import principal_dict_from_auth_context
from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.schemas.approval import (
    ApprovalCallbackHandleResult,
    ApprovalCallbackRequest,
    ApprovalRequest,
    ApprovalResumeResult,
    ApprovalSubmitResult,
)
from app.session.message_store import MessageStore
from app.verification.schemas import VerificationInput
from app.verification.service import VerificationService


class ApprovalService:
    """创建审批、提交外部审批系统，并在审批通过后恢复流程。

    当前恢复机制依赖 ApprovalStore 保存 resume_state 与 pending tool loop 数据，
    不是 LangGraph 原生 interrupt。审批记录是外部审批台账，checkpoint 是 Graph
    状态快照，两者职责不同。
    """

    def __init__(
        self,
        *,
        store: SQLiteApprovalStore,
        client: ApprovalSystemClient,
        verification_service: VerificationService,
        message_store: MessageStore,
        short_memory: ShortTermMemoryManager,
        callback_url: str,
        orchestrator: Any | None = None,
    ) -> None:
        self.store = store
        self.client = client
        self.verification_service = verification_service
        self.message_store = message_store
        self.short_memory = short_memory
        self.callback_url = callback_url
        self.orchestrator = orchestrator

    async def create_approval_request(
        self,
        *,
        session_key: str,
        request_id: str,
        trace_id: str | None,
        thread_id: str | None = None,
        checkpoint_id: str | None = None,
        parent_approval_id: str | None = None,
        root_approval_id: str | None = None,
        approval_depth: int = 0,
        approval_scope: str = "single_tool_call",
        idempotency_key: str | None = None,
        tenant_id: str | None = None,
        subject: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        org_path: list[str] | None = None,
        principal_snapshot: dict[str, Any] | None = None,
        auth_context_snapshot: dict[str, Any] | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        tool_required_scopes: list[str] | None = None,
        agent_name: str,
        tool_name: str,
        operation_type: str,
        risk_level: str,
        arguments: dict[str, Any],
        reason: str,
        resume_state: dict[str, Any],
        pending_messages: list[dict[str, Any]],
        pending_tools: list[dict[str, Any]],
        pending_tool_call: dict[str, Any],
    ) -> ApprovalRequest:
        """持久化一次待审批工具调用及恢复所需状态。"""
        approval_id = f"approval_{uuid4().hex}"
        root_id = root_approval_id or approval_id
        resume_state_payload = {
            **resume_state,
            "approval_id": approval_id,
            "approval_status": "created",
            "parent_approval_id": parent_approval_id,
            "root_approval_id": root_id,
            "approval_depth": approval_depth,
        }
        request = ApprovalRequest(
            approval_id=approval_id,
            session_key=session_key,
            request_id=request_id,
            trace_id=trace_id,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            parent_approval_id=parent_approval_id,
            root_approval_id=root_id,
            approval_depth=approval_depth,
            approval_scope=approval_scope,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            subject=subject,
            user_id=user_id,
            org_id=org_id,
            org_path=org_path or [],
            principal_snapshot=principal_snapshot or principal_dict_from_auth_context(auth_context_snapshot) or {},
            auth_context_snapshot=auth_context_snapshot or {},
            resource_type=resource_type,
            resource_id=resource_id,
            tool_required_scopes=tool_required_scopes or [],
            agent_name=agent_name,
            tool_name=tool_name,
            operation_type=operation_type,
            risk_level=risk_level,
            arguments=arguments,
            reason=reason,
            callback_url=self.callback_url,
            pending_state=resume_state_payload,
            resume_state=resume_state_payload,
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

        if approval_request.status in {"completed", "rejected", "manual_intervention_required"}:
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
        resume = await self.resume_graph_after_approval(approval_request)
        refreshed = await self.store.get(callback.approval_id) or approval_request
        return ApprovalCallbackHandleResult(
            approval_request=refreshed,
            resumed=True,
            final_answer=resume.final_answer,
            error=resume.error,
        )

    async def resume_graph_after_approval(self, approval_request: ApprovalRequest) -> ApprovalResumeResult:
        if self.orchestrator is None:
            raise RuntimeError("approval_resume_orchestrator_not_configured")

        state = await self.orchestrator.resume_after_approval(approval_request)
        refreshed = await self.store.get(approval_request.approval_id) or approval_request
        final_answer = state.get("answer")
        new_approval_id = state.get("approval_id")
        has_next_approval = bool(
            state.get("approval_required") and new_approval_id and new_approval_id != approval_request.approval_id
        )

        if has_next_approval:
            refreshed.status = "completed"
            refreshed.next_approval_id = new_approval_id
            refreshed.error = None
            refreshed.final_answer = final_answer
            refreshed.result = {
                **(refreshed.result or {}),
                "next_approval_id": new_approval_id,
                "graph_path": state.get("graph_path", []),
            }
            await self.store.update(
                refreshed,
                event_type="completed_with_next_approval",
                payload={"next_approval_id": new_approval_id, "final_answer": final_answer},
            )
        elif state.get("manual_intervention_required"):
            refreshed.status = "manual_intervention_required"
            refreshed.error = "manual_intervention_required"
            refreshed.final_answer = final_answer
            refreshed.result = {"graph_path": state.get("graph_path", []), "manual_intervention_required": True}
            await self.store.update(
                refreshed,
                event_type="manual_intervention_required",
                payload={"final_answer": final_answer},
            )
        else:
            refreshed.status = "completed"
            refreshed.error = state.get("error")
            refreshed.final_answer = final_answer
            refreshed.result = {
                "graph_path": state.get("graph_path", []),
                "subagent_result": state.get("subagent_result"),
            }
            await self.store.update(
                refreshed,
                event_type="completed",
                payload={"final_answer": final_answer, "error": refreshed.error},
            )

        return ApprovalResumeResult(
            approval_id=refreshed.approval_id,
            status=refreshed.status,
            final_answer=refreshed.final_answer,
            error=refreshed.error,
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
        verification = await self.verification_service.verify(
            VerificationInput(
                stage="pre_answer",
                request_id=approval_request.request_id,
                trace_id=approval_request.trace_id,
                session_key=approval_request.session_key,
                auth_context=approval_request.auth_context_snapshot or {},
                principal=principal_dict_from_auth_context(approval_request.auth_context_snapshot)
                or approval_request.principal_snapshot
                or None,
                agent_name=approval_request.agent_name,
                answer=raw_answer,
                metadata={"approval_id": approval_request.approval_id, "approval_status": approval_request.status},
            )
        )
        if verification.action == "patch" and isinstance(verification.patched_output, str):
            final_answer = verification.patched_output
        elif verification.action in {"allow", "patch"} and verification.passed:
            final_answer = raw_answer
        else:
            final_answer = "当前回复未通过最终验证，已拦截原始内容。请补充更具体的业务问题，我会在不暴露敏感信息的前提下重新说明。"
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
    def _now() -> str:
        return datetime.now(UTC).isoformat()
