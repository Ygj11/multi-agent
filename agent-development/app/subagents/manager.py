from __future__ import annotations

"""固定子 Agent catalog。"""

from app.observability.logger import log_event
from app.schemas.runtime import OrchestratorContext
from app.schemas.skill import SkillMetadata
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.skills.catalog import SkillCatalog
from typing import Protocol


class RunnableSubAgent(Protocol):
    """固定 catalog 中子 Agent 需要满足的最小运行协议。"""

    async def run(self, task: SubAgentTask, parent_context: OrchestratorContext) -> SubAgentResult:
        """执行子 Agent 任务并返回统一结果。"""
        ...


class SubAgentManager:
    """注册并按名称调用子 Agent。"""

    def __init__(self, skill_catalog: SkillCatalog | None = None) -> None:
        """初始化固定 catalog。"""
        self._catalog: dict[str, RunnableSubAgent] = {}
        self.skill_catalog = skill_catalog

    def register(self, name: str, agent: RunnableSubAgent) -> None:
        """注册一个子 Agent。"""
        self._catalog[name] = agent

    def list_agents(self) -> list[str]:
        """列出当前可用子 Agent 名称。"""
        return sorted(self._catalog)

    def list_skill_candidates(self, agent_name: str) -> list[SkillMetadata]:
        """列出某个子 Agent 的候选 skill metadata。"""
        if self.skill_catalog is None:
            return []
        return self.skill_catalog.list_skills(agent_name)

    async def call_subagent(
        self,
        name: str,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
    ) -> SubAgentResult:
        """按名称调用子 Agent，并在不存在时明确报错。"""
        agent = self._catalog.get(name)
        if agent is None:
            log_event(
                "subagent_selected",
                level="ERROR",
                session_key=task.session_key,
                node="subagent_manager",
                message="Subagent not found",
                data={"subagent_name": name, "intent": task.intent},
            )
            raise ValueError(f"subagent not found: {name}")
        log_event(
            "subagent_selected",
            request_id=task.metadata.get("request_id"),
            trace_id=task.metadata.get("trace_id"),
            session_key=task.session_key,
            node="subagent_manager",
            message="Subagent selected",
            data={"subagent_name": name, "intent": task.intent},
        )
        return await agent.run(task, parent_context)
