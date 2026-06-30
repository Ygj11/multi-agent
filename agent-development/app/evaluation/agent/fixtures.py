from __future__ import annotations

"""Agent Eval fixture 注入工具。

Fixture 可以理解成：测试用例事先准备好的输入、返回值和环境配置。

Agent Eval 的测试夹具注入：不改主流程，只把外部审批、真实工具、真实业务状态查询替换成可控的假实现，用来稳定复现评测场景，给 Agent Eval 构造一个可控的测试环境。

它不会把整个 Agent 系统都 Mock 掉，而是保留真实的：
    LangGraph 主流程；
    Agent 选择；
    Skill 选择；
    ToolCallingRunner；
    ToolExecutor；
    权限检查；
    审批判断；
    Verify-Repair Loop；
    日志和状态更新。

整体流程：
    读取 Eval Case
        ↓
    解析 tool_fixtures / approval_fixture / business_state_fixtures
        ↓
    AgentEvalFixtureApplier.apply()
        ↓
    替换隔离容器中的外部依赖
        ↓
    运行真实 Agent Graph
        ↓
    收集工具调用、审批提交、验证结果
        ↓
    和 Eval Case 预期结果比较

"""

from typing import Any

from app.evaluation.agent.schemas import (
    AgentEvalApprovalFixture,
    AgentEvalBusinessStateFixture,
    AgentEvalToolFixture,
)
from app.schemas.approval import ApprovalSubmitResult
from app.verification.task_completion.schemas import TaskCompletionVerificationContext, VerificationEvidence


class AgentEvalApprovalClient:
    """替代外部审批系统，仅返回配置化 submit 结果。"""

    def __init__(self, fixture: AgentEvalApprovalFixture) -> None:
        self.fixture = fixture
        self.submissions: list[dict[str, Any]] = []

    async def submit_approval_request(self, request):
        self.submissions.append(request.model_dump(mode="json"))
        return ApprovalSubmitResult(
            accepted=self.fixture.accepted,
            external_approval_id=f"ext_{request.approval_id}" if self.fixture.accepted else None,
            status=self.fixture.status,  # type: ignore[arg-type]
            error=self.fixture.error,
        )


class AgentEvalFakeTool:
    """被 ToolRegistry 持有的 fake callable。"""

    def __init__(
        self,
        fixture: AgentEvalToolFixture,
        *,
        records: list[dict[str, Any]],
        errors: list[str],
    ) -> None:
        self.fixture = fixture
        self.records = records
        self.errors = errors
        self._call_count = 0

    async def __call__(self, **kwargs: Any) -> Any:
        self._call_count += 1
        arguments = dict(kwargs)
        self.records.append({"tool_name": self.fixture.tool_name, "arguments": arguments})
        self._check_expected_arguments(arguments)
        if self.fixture.raise_error:
            raise RuntimeError(self.fixture.raise_error)
        if self.fixture.results:
            index = min(self._call_count - 1, len(self.fixture.results) - 1)
            return self.fixture.results[index]
        return self.fixture.result

    def _check_expected_arguments(self, arguments: dict[str, Any]) -> None:
        expected = self.fixture.expected_arguments
        if expected is None:
            return
        for key, value in expected.items():
            if arguments.get(key) != value:
                self.errors.append(
                    f"{self.fixture.tool_name}.{key} expected {value!r}, got {arguments.get(key)!r}"
                )


class AgentEvalBusinessStateProbe:
    """按 fixture 返回只读业务状态证据。"""

    def __init__(self, fixture: AgentEvalBusinessStateFixture) -> None:
        self.fixture = fixture

    async def supports(self, context: TaskCompletionVerificationContext) -> bool:
        return not self.fixture.supports_skill_id or context.selected_skill_id == self.fixture.supports_skill_id

    async def collect(self, context: TaskCompletionVerificationContext) -> list[VerificationEvidence]:
        return [VerificationEvidence(**item) for item in self.fixture.evidence]


class AgentEvalFixtureApplier:
    """把 case fixture 注入真实 AppContainer。

    注入只发生在 eval 隔离容器内。工具仍经过 ToolExecutor；这里仅替换已注册
    ToolDefinition.callable，避免绕过可见性、参数、审批和日志。
    """

    def __init__(self, container: Any) -> None:
        self.container = container
        self.errors: list[str] = []
        self.tool_records: list[dict[str, Any]] = []
        self.approval_client: AgentEvalApprovalClient | None = None

    def apply(
        self,
        *,
        tool_fixtures: list[AgentEvalToolFixture],
        approval_fixture: AgentEvalApprovalFixture | None,
        business_state_fixtures: list[AgentEvalBusinessStateFixture],
    ) -> None:
        for fixture in tool_fixtures:
            self._replace_tool_callable(fixture)
        if approval_fixture is not None:
            self.approval_client = AgentEvalApprovalClient(approval_fixture)
            self.container.approval_service.client = self.approval_client
        if business_state_fixtures:
            probes = list(getattr(self.container.task_completion_evidence_collector, "probes", []) or [])
            probes.extend(AgentEvalBusinessStateProbe(fixture) for fixture in business_state_fixtures)
            self.container.task_completion_evidence_collector.probes = probes

    def _replace_tool_callable(self, fixture: AgentEvalToolFixture) -> None:
        definition = self.container.tool_registry.get_definition(fixture.tool_name)
        if definition is None:
            self.errors.append(f"tool fixture references unknown tool: {fixture.tool_name}")
            return
        updates: dict[str, Any] = {
            "callable": AgentEvalFakeTool(fixture, records=self.tool_records, errors=self.errors),
        }
        if fixture.is_write is not None:
            updates["is_write"] = fixture.is_write
        if fixture.operation is not None:
            updates["operation"] = fixture.operation
        if fixture.risk_level is not None:
            updates["risk_level"] = fixture.risk_level
        # Eval 内部替换已注册定义，保留参数 schema、Agent 可见性和静态 contract。
        self.container.tool_registry._tools[fixture.tool_name] = definition.model_copy(update=updates)
