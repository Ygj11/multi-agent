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
from app.schemas.enums.approval import ApprovalEventType, ApprovalStatus
from app.schemas.enums.graph import AfterApprovalCreateRoute, ApprovalRequiredRoute
from app.schemas.enums.tool import RiskLevel, ToolOperation, ToolStoppedReason
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
        # 审批恢复的核心背景：
        # 1. 触发场景：
        #    子 Agent 的 ToolCallingRunner 让 LLM 选择工具；当 ToolExecutor 发现工具是写操作、
        #    高风险操作、命中工具契约中的审批策略，或后续扩展的前置校验要求人工确认时，
        #    不会立即执行真实工具，而是返回 human_approval_required。Graph 随后走
        #    check_human_approval_required -> create_approval_request -> submit_approval_request
        #    -> pause_for_approval，/api/chat 同步返回“需要审批”的结果。
        # 2. 为什么要保存状态：
        #    审批中断发生在一次 LLM tool loop 的中间。此时不能等审批回来后从 load_session、
        #    query_rewrite、intent、select_agent 重新跑一遍，否则可能因为历史变化、LLM 随机性、
        #    Skill 重新选择或工具列表变化导致恢复执行偏离第一次决策。正确做法是保存“继续执行
        #    这个工具调用所需的最小现场”，审批通过后只恢复被暂停的工具调用，再把工具结果追加
        #    回同一轮 tool loop 的 messages，让 LLM 基于新 observation 继续判断下一步。
        # 3. create_approval_request 保存的关键字段含义：
        #    - resume_state：Graph 恢复所需的最小业务状态，如 request/session、query、intent、
        #      entities、selected_agent、selected_skill_id、审批链路深度等。它不是完整 checkpoint，
        #      只用于 route_entry 判断 approval_resume=True 后进入本节点。
        #    - pending_tool_call：被人工审批暂停的那一次工具调用，包含工具名、tool_call_id 和参数。
        #      审批通过后只能执行这一笔，不能让模型重新选择一个“看起来相似”的写工具。
        #    - pending_messages：暂停前已经发给 LLM 的消息上下文。审批工具执行完成后，工具结果会
        #      作为 role=tool 的 observation 追加进去，再次交给 ToolCallingRunner。
        #    - pending_tools：暂停前暴露给 LLM 的工具 schema。恢复时沿用同一工具集合，避免审批前后
        #      可见工具变化造成模型走到另一条执行路径。
        #    - auth_context_snapshot / principal_snapshot：审批恢复发生在另一个 HTTP callback 中，
        #      不能依赖当前请求体自证身份，因此要复用第一次请求时的可信身份快照。
        #    - result_callback_url：如果 /api/chat 调用方提供了最终结果回调地址，它随 resume_state
        #      保存；本节点只负责恢复执行，真正的最终结果通知由 ApprovalService 在 Graph 结束后发送。
        # 4. 本方法的恢复步骤：
        #    a. 读取 approval_id，并从 ApprovalStore 取回审批台账；
        #    b. 从 state / approval_request / resume_state 中恢复 pending_messages、pending_tools、
        #       pending_tool_call；
        #    c. 用审批台账中固定的 agent_name、tool_name、arguments 调用 execute_approved_tool；
        #    d. 把工具执行结果追加为 role=tool 消息；
        #    e. 如果工具失败，直接构造一次恢复后的 SubAgentResult；
        #    f. 如果工具成功，继续调用 ToolCallingRunner，让 LLM 根据工具 observation 判断是否还要
        #       调工具、是否再次触发审批，或是否可以生成最终答案；
        #    g. 返回 Graph 后续节点需要的 subagent_result、answer 和 approval_required。
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

        # 只执行审批记录里冻结的工具和参数。这里不读取 LLM 新输出，也不重新做 Agent/Skill 选择，
        # 是为了保证审批人批准的就是即将执行的那一次工具调用。
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
        # tool loop 语义要求：工具执行结果必须以 role=tool 且带 tool_call_id 的消息回填给 LLM。
        # 否则模型只知道“审批通过了”，但不知道工具真实返回了什么，也无法继续完成后续推理。
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
                stopped_reason=ToolStoppedReason.ERROR,
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
            # 审批通过只代表“允许执行被暂停的工具”，不代表整个用户任务已经完成。
            # 工具结果回填后仍要继续 tool loop：模型可能直接生成最终答案，也可能根据 SOP 再调用
            # 只读工具补证据，或者触发下一次写工具审批链。
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
            needs_approval = run_result.needs_human_approval or run_result.stopped_reason is ToolStoppedReason.HUMAN_APPROVAL_REQUIRED
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
                "approval_status": str(ApprovalStatus.MANUAL_INTERVENTION_REQUIRED),
                "manual_intervention_required": True,
                "answer": "连续写操作审批次数已超过上限，当前操作未执行，请人工接管后继续处理。",
                "error": str(ApprovalStatus.MANUAL_INTERVENTION_REQUIRED),
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

        # 审批创建时，把当前 Graph State 投影成一份最小恢复状态，保存进数据库
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
            operation_type=payload.get("operation_type") or str(ToolOperation.WRITE),
            risk_level=payload.get("risk_level") or str(RiskLevel.HIGH),
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
                parent.status = ApprovalStatus.COMPLETED
                parent.next_approval_id = approval_request.approval_id
                parent.error = None
                parent.result = {**(parent.result or {}), "next_approval_id": approval_request.approval_id}
                await self.approval_service.store.update(
                    parent,
                    event_type=str(ApprovalEventType.NEXT_APPROVAL_CREATED),
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
                    event_type=str(ApprovalEventType.SUBMIT_FAILED_ANSWER_PREPARED),
                    payload={"answer": answer, "error": approval_request.error},
                )
        else:
            answer = f"该操作需要人工审批，审批请求已提交，approval_id={approval_id}。当前操作尚未执行。"
        return {
            "answer": answer,
            "approval_status": state.get("approval_status") or str(ApprovalStatus.PENDING),
        }

    @staticmethod
    def human_route(state: dict[str, Any]) -> ApprovalRequiredRoute:
        return ApprovalRequiredRoute.REQUIRED if state.get("approval_required") else ApprovalRequiredRoute.NOT_REQUIRED

    @staticmethod
    def after_create_route(state: dict[str, Any]) -> AfterApprovalCreateRoute:
        return AfterApprovalCreateRoute.MANUAL if state.get("manual_intervention_required") else AfterApprovalCreateRoute.SUBMIT

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
        stopped_reason: ToolStoppedReason | str,
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
            "risk_level": str(RiskLevel.HIGH if needs_human_approval else RiskLevel.LOW),
            "metadata": {
                "tool_calling_runner": {
                    "stopped_reason": str(stopped_reason),
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
