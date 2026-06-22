from __future__ import annotations

"""Approval-related LangGraph node handlers."""

import json
from typing import Any

from app.auth.principal import principal_dict_from_auth_context
from app.approval.service import ApprovalService
from app.agents.card_loader import AgentCardLoader
from app.runtime.state_projector import project_approval_resume_state
from app.schemas.agent_card import AgentCard
from app.schemas.approval import ApprovalRequest
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.executor import ToolExecutor


class ApprovalGraphHandler:
    """Own human-approval node internals while graph.py keeps routing."""

    def __init__(
        self,
        *,
        approval_service: ApprovalService | None,
        tool_executor: ToolExecutor | None,
        tool_calling_runner: ToolCallingRunner | None,
        max_approval_chain_depth: int,
        max_write_tools_per_request: int,
        agent_card_loader: AgentCardLoader | None = None,
    ) -> None:
        self.approval_service = approval_service
        self.tool_executor = tool_executor
        self.tool_calling_runner = tool_calling_runner
        self.agent_card_loader = agent_card_loader
        self.max_approval_chain_depth = max_approval_chain_depth
        self.max_write_tools_per_request = max_write_tools_per_request

    async def resume_approved_tool(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.tool_executor is None or self.tool_calling_runner is None:
            raise RuntimeError("approval_resume_dependencies_not_configured")
        if self.approval_service is None:
            raise RuntimeError("approval_service_not_configured")

        approval_id = state.get("approval_id") or state.get("current_approval_id")
        if not approval_id:
            raise RuntimeError("approval_id_required_for_resume")

        approval_request = await self._approval_request_from_state(state, approval_id)
        if approval_request is None:
            raise RuntimeError("approval_request_not_found")

        resume_state = approval_request.resume_state or approval_request.pending_state
        pending_messages = list(state.get("pending_messages") or approval_request.pending_messages or resume_state.get("pending_messages") or [])
        pending_tools = list(state.get("pending_tools") or approval_request.pending_tools or resume_state.get("pending_tools") or [])
        pending_tool_call = dict(state.get("pending_tool_call") or approval_request.pending_tool_call or resume_state.get("pending_tool_call") or {})
        agent_card = self._agent_card_from_state(state, self.agent_card_loader)
        tool_call_id = pending_tool_call.get("tool_call_id") or pending_tool_call.get("id") or f"approved_{approval_id}"

        auth_context = state.get("auth_context") or approval_request.auth_context_snapshot
        principal = principal_dict_from_auth_context(auth_context)
        tool_result = await self.tool_executor.execute_approved_tool(
            approval_id=approval_id,
            agent_name=approval_request.agent_name,
            tool_name=approval_request.tool_name,
            arguments=approval_request.arguments,
            session_key=approval_request.session_key or state.get("session_key", ""),
            request_id=approval_request.request_id or state.get("request_id", ""),
            trace_id=approval_request.trace_id or state.get("trace_id"),
            agent_card=agent_card,
            principal=principal,
            auth_context=auth_context,
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

        if not tool_result.success:
            subagent_result = self._build_resume_subagent_result(
                state=state,
                stopped_reason="error",
                final_answer=tool_result.error or "approved_tool_execution_failed",
                tool_calls=[dumped_tool_result],
                needs_human_approval=False,
                approval_payload=None,
                pending_tool_call=None,
                pending_messages=pending_messages,
                pending_tools=pending_tools,
                error=tool_result.error,
            )
            answer = subagent_result["answer"]
        else:
            run_result = await self.tool_calling_runner.run(
                agent_name=approval_request.agent_name,
                messages=pending_messages,
                tools=pending_tools,
                session_key=approval_request.session_key or state.get("session_key", ""),
                request_id=approval_request.request_id or state.get("request_id", ""),
                trace_id=approval_request.trace_id or state.get("trace_id"),
                agent_card=agent_card,
                principal=principal,
                auth_context=auth_context,
                evidence=[dumped_tool_result],
            )
            needs_approval = run_result.needs_human_approval or run_result.stopped_reason == "human_approval_required"
            answer = (
                "This operation requires human approval and has not been executed."
                if needs_approval
                else run_result.final_answer or run_result.error or "approval_resume_finished_without_answer"
            )
            subagent_result = self._build_resume_subagent_result(
                state=state,
                stopped_reason=run_result.stopped_reason,
                final_answer=answer,
                tool_calls=run_result.tool_calls,
                needs_human_approval=needs_approval,
                approval_payload=run_result.approval_payload,
                pending_tool_call=run_result.pending_tool_call,
                pending_messages=run_result.messages,
                pending_tools=run_result.tools,
                error=run_result.error,
            )

        return {
            "subagent_result": subagent_result,
            "answer": answer,
            "approval_required": bool(subagent_result.get("needs_human_approval")),
            "approval_payloads": subagent_result.get("approval_payloads", []),
            "current_approval_id": approval_id,
            "root_approval_id": approval_request.root_approval_id or approval_id,
            "approval_depth": approval_request.approval_depth,
        }

    def check_required(self, state: dict[str, Any]) -> dict[str, Any]:
        result = state.get("subagent_result") or {}
        approval_payloads = result.get("approval_payloads") or []
        approval_required = bool(result.get("needs_human_approval") or approval_payloads)
        return {
            "approval_required": approval_required,
            "approval_payloads": approval_payloads,
        }

    async def create_request(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.approval_service is None:
            raise RuntimeError("approval_service_not_configured")
        current_approval_id = state.get("current_approval_id")
        current_depth = int(state.get("approval_depth") or 0)
        next_depth = current_depth + 1 if current_approval_id else 0
        next_write_count = next_depth + 1
        if current_approval_id and (
            next_depth > self.max_approval_chain_depth or next_write_count > self.max_write_tools_per_request
        ):
            return {
                "approval_required": False,
                "approval_status": "manual_intervention_required",
                "manual_intervention_required": True,
                "answer": "连续写操作审批次数已超过上限，当前操作未执行，请人工接管后继续处理。",
                "error": "manual_intervention_required",
            }

        payload = (state.get("approval_payloads") or [{}])[0]
        runner_meta = ((state.get("subagent_result") or {}).get("metadata") or {}).get("tool_calling_runner") or {}
        pending_tool_call = runner_meta.get("pending_tool_call") or payload.get("pending_tool_call") or {
            "name": payload.get("tool_name"),
            "arguments": payload.get("arguments", {}),
        }
        thread_id = state.get("thread_id") or self._thread_id(state)
        root_approval_id = state.get("root_approval_id") or current_approval_id
        auth_context_snapshot = state.get("auth_context") or {}
        principal_snapshot = principal_dict_from_auth_context(auth_context_snapshot) or {}
        pending_messages = runner_meta.get("pending_messages") or []
        pending_tools = runner_meta.get("pending_tools") or []
        resume_state = project_approval_resume_state(
            state,
            pending_tool_call=pending_tool_call,
            pending_messages=pending_messages,
            pending_tools=pending_tools,
            parent_approval_id=current_approval_id,
            root_approval_id=root_approval_id,
            approval_depth=next_depth,
        )
        approval_request = await self.approval_service.create_approval_request(
            session_key=state["session_key"],
            request_id=state["request_id"],
            trace_id=state.get("trace_id"),
            thread_id=thread_id,
            parent_approval_id=current_approval_id,
            root_approval_id=root_approval_id,
            approval_depth=next_depth,
            tenant_id=(principal_snapshot or {}).get("tenant_id") or state.get("tenant_id"),
            subject=(principal_snapshot or {}).get("subject"),
            user_id=(principal_snapshot or {}).get("user_id") or state.get("user_id"),
            org_id=(principal_snapshot or {}).get("org_id"),
            org_path=(principal_snapshot or {}).get("org_path") or [],
            principal_snapshot=principal_snapshot or {},
            auth_context_snapshot=auth_context_snapshot,
            resource_type=payload.get("resource_type"),
            resource_id=payload.get("resource_id"),
            tool_required_scopes=payload.get("required_scopes") or [],
            agent_name=payload.get("agent_name") or state.get("selected_agent") or "unknown",
            tool_name=payload.get("tool_name") or pending_tool_call.get("name") or "unknown",
            operation_type=payload.get("operation_type") or "write",
            risk_level=payload.get("risk_level") or "high",
            arguments=payload.get("arguments") or pending_tool_call.get("arguments") or {},
            reason=payload.get("reason") or "Write-side tool call requires human approval.",
            resume_state=resume_state.model_dump(mode="json"),
            pending_messages=pending_messages,
            pending_tools=pending_tools,
            pending_tool_call=pending_tool_call,
        )
        if current_approval_id:
            parent = await self.approval_service.store.get(current_approval_id)
            if parent is not None:
                parent.status = "completed"
                parent.next_approval_id = approval_request.approval_id
                parent.error = None
                parent.result = {**(parent.result or {}), "next_approval_id": approval_request.approval_id}
                await self.approval_service.store.update(
                    parent,
                    event_type="next_approval_created",
                    payload={"next_approval_id": approval_request.approval_id},
                )

        return {
            "approval_id": approval_request.approval_id,
            "approval_status": approval_request.status,
            "parent_approval_id": approval_request.parent_approval_id,
            "root_approval_id": approval_request.root_approval_id,
            "approval_depth": approval_request.approval_depth,
            "manual_intervention_required": False,
        }

    async def submit_request(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.approval_service is None:
            raise RuntimeError("approval_service_not_configured")
        approval_id = state.get("approval_id")
        approval_request = await self._approval_request_from_state(state, approval_id)
        if approval_request is None:
            raise RuntimeError("approval_request_not_found")
        submit_result = await self.approval_service.submit_to_external_approval_system(approval_request)
        refreshed = await self.approval_service.store.get(approval_request.approval_id)
        return {
            "approval_status": refreshed.status if refreshed else submit_result.status,
            "approval_submit_result": submit_result.model_dump(),
        }

    async def pause(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.approval_service is None:
            raise RuntimeError("approval_service_not_configured")
        approval_id = state.get("approval_id")
        submit_result = state.get("approval_submit_result") or {}
        if not submit_result.get("accepted"):
            answer = "审批系统提交失败，操作未执行。"
            approval_request = await self._approval_request_from_state(state, approval_id)
            if approval_request is not None:
                approval_request.final_answer = answer
                approval_request.error = submit_result.get("error") or "approval_submit_failed"
                await self.approval_service.store.update(
                    approval_request,
                    event_type="submit_failed_answer_prepared",
                    payload={"answer": answer, "error": approval_request.error},
                )
        else:
            answer = f"该操作需要人工审批，审批请求已提交，approval_id={approval_id}。当前操作尚未执行。"
        return {
            "answer": answer,
            "approval_status": state.get("approval_status") or "pending",
        }

    @staticmethod
    def human_route(state: dict[str, Any]) -> str:
        return "required" if state.get("approval_required") else "not_required"

    @staticmethod
    def after_create_route(state: dict[str, Any]) -> str:
        return "manual" if state.get("manual_intervention_required") else "submit"

    @staticmethod
    def _thread_id(state: dict[str, Any]) -> str:
        return f"{state.get('session_key')}:{state.get('request_id')}"

    @staticmethod
    def _agent_card_from_state(state: dict[str, Any], loader: AgentCardLoader | None = None) -> AgentCard | None:
        data = state.get("selected_agent_card")
        if isinstance(data, dict):
            return AgentCard(**data)
        selected_agent = state.get("selected_agent")
        if loader is not None and selected_agent:
            return loader.get_agent_card(str(selected_agent))
        return None

    async def _approval_request_from_state(self, state: dict[str, Any], approval_id: str | None) -> ApprovalRequest | None:
        if self.approval_service is not None and approval_id:
            return await self.approval_service.store.get(approval_id)
        return None

    @staticmethod
    def _skill_selection_from_subagent_result(state: dict[str, Any]) -> dict[str, Any]:
        result = state.get("subagent_result") if isinstance(state.get("subagent_result"), dict) else {}
        return {
            "selected_skill_id": result.get("selected_skill_id"),
            "selected_skill_metadata": result.get("selected_skill_metadata"),
            "skill_selection_score": result.get("skill_selection_score"),
            "skill_selection_reason": result.get("skill_selection_reason"),
        }

    @staticmethod
    def _build_resume_subagent_result(
        *,
        state: dict[str, Any],
        stopped_reason: str,
        final_answer: str,
        tool_calls: list[dict[str, Any]],
        needs_human_approval: bool,
        approval_payload: dict[str, Any] | None,
        pending_tool_call: dict[str, Any] | None,
        pending_messages: list[dict[str, Any]],
        pending_tools: list[dict[str, Any]],
        error: str | None,
    ) -> dict[str, Any]:
        skill_selection = ApprovalGraphHandler._skill_selection_from_subagent_result(state)
        return {
            "name": state.get("selected_agent") or "unknown",
            "agent_name": state.get("selected_agent") or "unknown",
            "task_id": ((state.get("subagent_result") or {}).get("task_id") if isinstance(state.get("subagent_result"), dict) else None),
            "answer": final_answer,
            "diagnosis": None,
            "evidence": [],
            "tool_calls": tool_calls,
            "recommendation": None,
            "responsibility": None,
            "confidence": 0.3 if needs_human_approval or error else 0.88,
            "needs_human_approval": needs_human_approval,
            "approval_payloads": [approval_payload] if approval_payload else [],
            "risk_level": "high" if needs_human_approval else "low",
            "metadata": {
                "tool_calling_runner": {
                    "stopped_reason": stopped_reason,
                    "iterations": None,
                    "error": error,
                    "pending_tool_call": pending_tool_call,
                    "pending_messages": pending_messages,
                    "pending_tools": pending_tools,
                },
                "approval_resume": True,
                "current_approval_id": state.get("current_approval_id") or state.get("approval_id"),
            },
            "selected_skill_id": skill_selection["selected_skill_id"],
            "selected_skill_metadata": skill_selection["selected_skill_metadata"],
            "skill_selection_score": skill_selection["skill_selection_score"],
            "skill_selection_reason": skill_selection["skill_selection_reason"],
        }
