# P0/P1 企业级 Agent Harness 详细设计

> 适用范围：当前 `agent-development` 本地项目。  
> 依据：当前本地代码实现，以及 `docs/multi_agent_enterprise_harness_design.md` 中的企业级 Harness 目标。  
> 目标：以长期企业级架构为目标，设计 P0/P1 阶段需要补齐的身份、权限、数据过滤、验证、证据和知识检索边界。本文是设计文档，不代表当前代码已经全部实现。  
> 核心原则：LLM 负责语义理解和推理；Harness 负责可信身份、权限、工具安全、结果过滤、验证、审批、证据和可追溯。

---

## 1. 当前代码基线

当前项目已经具备多 Agent MVP 主干，但企业级安全和验证 Harness 仍不完整。

| 能力 | 当前实现位置 | 当前状态 |
|---|---|---|
| FastAPI 入口 | `app/main.py::create_app` | 已有 `/api/chat`、审批 callback、审批查询 |
| 请求适配 | `app/adapters/request_adapter.py::RequestAdapter.adapt` | 会生成 `request_id`、`trace_id`、`session_key`，但 `tenant_id/user_id` 仍主要来自 request body |
| LangGraph 主图 | `app/runtime/graph.py::AgentGraphFactory.build` | 已有 query rewrite、intent、agent selection、dispatch、approval、最终返回等节点 |
| AgentCard | `app/agents/cards/*.yaml` | 已用于 Agent 能力、工具、Skill、RAG namespace 声明 |
| Skill | `app/skills/*`、`app/runtime/context_builder.py` | 已实现 metadata-first、LLM rerank、selected skill body loading、required_entities 检查 |
| ToolRegistry | `app/tools/registry.py` | 已管理 public/private/MCP tools，并输出 OpenAI function-calling schema |
| ToolExecutor | `app/tools/executor.py::ToolExecutor.execute` | 已做 AgentCard 工具可见性、required 参数校验、写工具审批、执行日志 |
| Tool loop 安全 | `app/subagents/tool_calling_runner.py` | 已有 max iterations、重复工具调用、连续失败上限 |
| Approval | `app/approval/*`、`app/runtime/graph.py` | 已有审批表、pending/callback/resume、多轮审批链基础 |
| Knowledge | `app/knowledge/*`、`app/integrations/knowledge_api_client.py` | 已有 Disabled/API client factory、RAG public tool、ContextBuilder pre_search/search |
| 内容合规 | `app/compliance/final_checker.py` | 当前是独立最终检查实现；长期应收敛为 VerificationService 的 `pre_answer` verifier |
| Tool execution log | `app/tools/tool_execution_log_store.py` | 已有工具执行日志，但不是完整 EvidenceStore |

当前关键差距：

1. 没有可信 `Principal/AuthContext`；请求体中的 `tenant_id/user_id` 不应作为生产可信身份。
2. 没有 Agent 级访问控制：用户或机构是否能使用某个子 Agent，目前没有统一校验。
3. Tool 级权限仍主要是 AgentCard 可见性，不是用户/机构权限。
4. Result 级字段权限不足：同一个工具返回结果后，没有统一字段级过滤。
5. 没有统一 `VerificationService / VerifierRegistry`，校验逻辑分散在多个模块。
6. 当前合规检查是独立 final checker；长期应融入 `VerificationService(stage="pre_answer")`。
7. Evidence 目前多为临时 dict 或 tool log，缺少统一 Evidence schema/store。
8. Knowledge 的 `rag_namespaces` 尚未真正参与检索范围过滤和 citation evidence。

---

## 2. 长期权限模型

企业级权限不应该只挂在工具 schema 上，也不应该让 LLM 根据不同工具名判断敏感权限。长期模型分三层：

```text
Agent 级权限
  -> 能不能访问这个 multi-agent / 子 Agent / 业务能力域

Tool 级权限
  -> 能不能执行这个工具动作

Result 级权限
  -> 工具返回后，最终回答哪些字段能返回用户
```

### 2.1 Agent 级权限

Agent 级权限用于控制业务能力入口。

示例：

| 主体 | 可访问 Agent | 不可访问 Agent |
|---|---|---|
| 普通客服机构 | `policy_query_agent` | `troubleshooting_agent` 内部排障能力 |
| 理赔机构 | `claim_agent` | 核保专属 Agent |
| 运维/对接支持机构 | `troubleshooting_agent`、`document_parse_agent` | 无关业务 Agent |

建议校验点：

```text
AgentSelection 召回候选时先过滤无权限 Agent
或
select_agent 后、dispatch_agent 前执行 verify_agent_access
```

即使前面过滤了候选，`dispatch_agent` 前仍建议做二次校验，避免绕过 AgentSelection。

### 2.2 Tool 级权限

Tool 级权限用于控制动作本身，例如查询、修改、通知、恢复、查内部日志。

示例：

| 工具 | 权限含义 |
|---|---|
| `query_policy_info` | 查询保单信息这个动作 |
| `query_internal_log` | 查询内部日志，通常只允许排障/运维机构 |
| `update_policy_status` | 修改保单状态，必须具备写权限且进入人工审批 |
| `notice_finance` | 触发财务创单通知，属于有副作用业务动作 |

Tool 级权限必须在 `ToolExecutor` 做二次校验。LLM 看不到工具不等于安全，因为它仍可能伪造 tool_call。

### 2.3 Result 级权限

Result 级权限用于处理同一个工具返回不同字段可见性的问题。

这是保单查询类场景的核心：

```text
query_policy_info(policy_no)
  -> 内部返回完整保单对象
  -> LLM 基于工具结果做业务判断
  -> 最终 answer 进入 VerificationService(stage="pre_answer")
  -> DataPermissionVerifier / ComplianceVerifier 根据 AuthContext 过滤或改写最终输出
```

不建议为了字段权限拆成多个 LLM function，例如：

```text
query_policy_info
query_policy_sensitive_info
```

除非底层 API、操作语义、副作用、审批流程或风险等级确实不同。仅仅因为“同一个保单对象里部分字段敏感”，应该由 `VerificationService(stage="pre_answer")` 中的 `DataPermissionVerifier / ComplianceVerifier` 解决，而不是交给 LLM 选择不同工具。

注意：默认不在工具结果进入 LLM 前做字段级脱敏。原因是工具结果往往是 LLM 判断业务问题、生成诊断结论的依据，过早删除字段会影响推理质量。LLM 前只做两类服务端控制：

1. Tool/Resource 访问控制：用户或机构没有权限调用该工具或访问该资源时，工具不能执行。
2. 高危原文阻断：token、secret、密码、完整内部日志、超出安全域的原始报文等不应进入 LLM 的内容，可由 `post_tool` verifier 阻断或替换为安全摘要。

字段级可见性以最终 `pre_answer` 校验为准。

---

## 3. P0 任务一：可信 Principal / AuthContext

### 3.1 目标

让系统身份来自可信入口，例如 API Gateway、JWT、统一认证服务或受信 Header，而不是来自 `/api/chat` request body。

长期原则：

```text
Header/JWT/Auth Gateway claims 是唯一可信身份来源。
request body 不承载可信 tenant_id/user_id/org 权限信息。
```

如果历史请求体仍有 `tenant_id/user_id` 字段：

1. 生产模式下不使用它们做权限依据。
2. 可以校验它们和可信 Principal 是否一致，不一致拒绝。
3. 也可以逐步从 API schema 中移除，保留向后兼容期。

### 3.2 新增文件

```text
app/auth/principal.py
app/auth/auth_context.py
app/auth/dependencies.py
app/auth/errors.py
```

### 3.3 Principal schema

`Principal` 不只是“某个人”，而是一次请求的可信访问主体。它应该同时包含租户、机构、渠道、岗位、数据域等企业权限上下文。

```python
class Principal(BaseModel):
    tenant_id: str
    user_id: str | None = None
    subject: str
    org_id: str | None = None
    org_path: list[str] = []
    branch_code: str | None = None
    channel: str | None = None
    roles: list[str] = []
    scopes: list[str] = []
    data_permissions: list[str] = []
    resource_domains: list[str] = []
    attributes: dict[str, Any] = {}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `tenant_id` | 租户，必须可信 |
| `subject` | token subject，可是用户、服务账号或系统调用方 |
| `user_id` | 操作人，用于审计；权限不应只依赖个人 |
| `org_id/org_path/branch_code` | 机构维度权限核心 |
| `channel` | 渠道，如客服、运营、对接、后台 |
| `roles` | 岗位/角色 |
| `scopes` | 动作级权限，如 `policy:read`、`policy:update` |
| `data_permissions` | 字段/数据域权限，如 `policy.sensitive.read` |
| `resource_domains` | 可访问的资源域、产品线、机构域 |
| `attributes` | 扩展属性，如城市、团队、外包标识等 |

### 3.4 AuthContext schema

```python
class AuthContext(BaseModel):
    principal: Principal
    auth_source: Literal["gateway", "jwt", "dev_header", "service_account"]
    raw_claims: dict[str, Any] = {}
    authenticated_at: str | None = None
```

`raw_claims` 只用于审计和排障，不直接给 LLM。

### 3.5 FastAPI dependency

`app/auth/dependencies.py`：

```python
async def get_current_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_org_id: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_roles: Annotated[str | None, Header()] = None,
    x_user_scopes: Annotated[str | None, Header()] = None,
    x_data_permissions: Annotated[str | None, Header()] = None,
) -> Principal:
    ...
```

建议配置：

```text
AUTH_MODE=dev_header|jwt|required
ALLOW_REQUEST_BODY_IDENTITY_FALLBACK=false
```

长期生产模式：

```text
AUTH_MODE=required 或 jwt
ALLOW_REQUEST_BODY_IDENTITY_FALLBACK=false
```

### 3.6 `/api/chat` 接入方式

当前：

```python
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    inbound = request_adapter.adapt(request)
```

目标：

```python
@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    principal: Principal = Depends(get_current_principal),
) -> ChatResponse:
    inbound = request_adapter.adapt(request, principal=principal)
```

`session_key` 应由可信身份生成：

```text
session_key = tenant_id:channel:user_id_or_subject:session_id
```

不要让 body 覆盖可信身份。

### 3.7 Runtime state 扩展

修改：

```text
app/runtime/graph_state.py
app/schemas/message.py
app/schemas/runtime.py
app/schemas/agent_task.py
app/schemas/subagent.py
```

新增：

```python
principal: dict[str, Any] | None
auth_context: dict[str, Any] | None
```

传递链路：

```text
FastAPI dependency
-> RequestAdapter / InboundMessage
-> AgentOrchestrator initial state
-> AgentGraphState
-> OrchestratorContext
-> SubAgentTask
-> ToolExecutor
-> VerificationService
```

### 3.8 测试

新增：

```text
tests/test_auth_context.py
```

验收：

1. Header/JWT principal 能进入 graph state。
2. body 中 tenant/user 与 principal 冲突时拒绝或忽略，不能覆盖 principal。
3. 生产 required 模式下无身份返回 401。
4. `session_key` 使用可信 principal 生成。
5. LLM 无法通过用户文本伪造 principal。

---

## 4. P0 任务二：ToolDefinition 动作权限元数据

### 4.1 目标

ToolDefinition 只描述“这个工具动作需要什么权限、资源类型、风险等级、是否有副作用”。它不应该承载字段级返回权限的全部逻辑。

字段级返回权限由 `VerificationService(stage="pre_answer")` 统一处理。`post_tool` 阶段只负责结构校验、高危原文阻断和 evidence 记录，不默认对业务字段做脱敏。

### 4.2 修改文件

```text
app/tools/base.py
app/tools/registry.py
app/tools/public_tools.py
app/tools/agent_tools.py
app/mcp/schemas.py
tests/test_tool_schema_openai.py
```

### 4.3 ToolDefinition 扩展

当前 `ToolDefinition` 已有：

```python
name
callable
description
scope
source
agent_name
server_name
original_name
parameters
enabled
is_write
metadata
```

建议新增：

```python
operation: Literal["read", "write", "notify", "execute", "search"] = "read"
required_scopes: list[str] = Field(default_factory=list)
resource_type: str | None = None
resource_id_arg: str | None = None
pre_answer_filter_required: bool = True
data_domains: list[str] = Field(default_factory=list)
risk_level: Literal["low", "medium", "high"] = "low"
precondition_id: str | None = None
idempotency_required: bool = False
```

字段说明：

| 字段 | 说明 |
|---|---|
| `operation` | 动作类型，用于 Tool 级鉴权和审批 |
| `required_scopes` | 调用该工具动作需要的权限，如 `policy:read` |
| `resource_type` | 资源类型，如 `policy`、`claim`、`internal_log` |
| `resource_id_arg` | 从工具参数中取资源 ID 的字段，如 `policy_no` |
| `pre_answer_filter_required` | 最终回答是否必须做字段级权限过滤 |
| `data_domains` | 工具可能返回的数据域，如 `policy.basic`、`policy.sensitive` |
| `risk_level` | 风险等级 |
| `precondition_id` | 需要哪个 verifier 校验前置条件 |
| `idempotency_required` | 写/通知类工具是否要求幂等 |

### 4.4 不按敏感字段拆工具

保单查询应该保留一个业务工具：

```python
query_policy_info:
  operation="read"
  required_scopes=["policy:read"]
  resource_type="policy"
  resource_id_arg="policy_no"
  pre_answer_filter_required=True
  data_domains=["policy.basic", "policy.sensitive"]
```

不要仅因为不同用户能看到的字段不同，就拆成：

```text
query_policy_info
query_policy_sensitive_info
```

字段级差异由 `VerificationService(stage="pre_answer")` 中的 `DataPermissionVerifier` 处理。

只有以下情况才建议拆工具：

1. 底层 API 本来不同。
2. 业务动作不同，例如查询 vs 修改。
3. 副作用不同，例如查询 vs 导出敏感报告。
4. 审批流程不同。
5. 风险等级不同。

写工具示例：

```python
update_policy_status:
  operation="write"
  required_scopes=["policy:update"]
  resource_type="policy"
  resource_id_arg="policy_no"
  is_write=True
  risk_level="high"
  precondition_id="policy_update_precondition"
  idempotency_required=True
```

### 4.5 LLM schema 约束

新增内部字段必须只存在于 ToolDefinition，不允许暴露给 LLM。

验收：

```python
schema = registry.get_tool_schema("query_policy_info")
assert "required_scopes" not in str(schema)
assert "resource_type" not in str(schema)
assert "pre_answer_filter_required" not in str(schema)
assert "data_domains" not in str(schema)
```

LLM 只看到：

```text
type=function
function.name
function.description
function.parameters
```

### 4.6 测试

新增/更新：

```text
tests/test_tool_definition_permissions.py
tests/test_tool_schema_openai.py
```

验收：

1. 工具可注册动作权限元数据。
2. LLM schema 不暴露内部权限字段。
3. 同一个 `query_policy_info` 可以支持不同用户结果过滤。
4. 写工具仍保留 `is_write=True` 和幂等要求。

---

## 5. P0 任务三：Agent / Tool / Resource 访问控制

### 5.1 目标

补齐两个入口级权限：

```text
Agent 级权限：能不能用这个子 Agent / 业务能力域
Tool 级权限：能不能执行这个工具动作
```

资源级权限用于回答“某个机构能不能看某张保单、某个理赔案、某类内部日志”。

### 5.2 新增文件

```text
app/auth/authorization_service.py
app/auth/resource_access_service.py
app/auth/policy.py
app/auth/errors.py
```

### 5.3 AuthorizationService

```python
class AuthorizationDecision(BaseModel):
    allowed: bool
    reason: str | None = None
    missing_scopes: list[str] = []
    denied_by: str | None = None

class AuthorizationService:
    def check_agent_access(
        self,
        *,
        principal: Principal,
        agent_card: AgentCard,
    ) -> AuthorizationDecision:
        ...

    def check_tool_access(
        self,
        *,
        principal: Principal,
        tool_definition: ToolDefinition,
    ) -> AuthorizationDecision:
        ...
```

Agent 级策略建议来自 AgentCard 扩展字段：

```yaml
access_policy:
  required_roles:
    - operations_support
  required_scopes:
    - agent:troubleshooting:use
  allowed_org_types:
    - ops
    - integration_support
```

Tool 级策略来自 ToolDefinition。

### 5.4 ResourceAccessService

```python
class ResourceAccessService:
    async def check_access(
        self,
        *,
        principal: Principal,
        resource_type: str,
        resource_id: str,
        action: str,
    ) -> AuthorizationDecision:
        ...
```

长期应接企业资源权限服务或核心业务权限服务。MVP 可以先做本地策略：

```text
policy_no -> 所属机构/产品线/渠道
claim_no -> 所属机构/产品线/渠道
request_id -> 所属租户/系统/接口域
```

机构维度是核心：

```text
org_id / org_path / branch_code / channel
```

用户个人只作为审计和临时授权补充，不作为唯一权限依据。

### 5.5 接入点

```text
AgentSelection candidates
-> AuthorizationService.check_agent_access
-> 无权限 Agent 不进入候选或在 dispatch 前被拒绝

ToolExecutor.execute
-> AuthorizationService.check_tool_access
-> ResourceAccessService.check_access
-> pre_tool VerificationService
-> execute / approval
```

顺序建议：

```text
tool exists
-> AgentCard 工具可见性
-> required 参数校验
-> Tool 级权限校验
-> Resource 级权限校验
-> pre_tool verify
-> is_write approval
-> execute
```

### 5.6 测试

新增：

```text
tests/test_agent_authorization.py
tests/test_tool_authorization_scopes.py
tests/test_resource_access_service.py
```

验收：

1. 无权 Agent 不会被选择或不能 dispatch。
2. 无权工具即使被 LLM 伪造调用，也被 ToolExecutor 拒绝。
3. 某机构无权访问某 `policy_no` 时，查询被拒绝。
4. 鉴权失败返回结构化错误，不抛未捕获异常。

---

## 6. P0 任务四：ToolRegistry 按 Principal 过滤 LLM 可见工具

### 6.1 目标

减少 LLM 看到无权限工具的概率，但不把它当作唯一安全边界。

```text
ToolRegistry schema filtering 是体验和降噪。
ToolExecutor authorization 是安全边界。
```

### 6.2 修改文件

```text
app/tools/registry.py
app/subagents/base.py
app/runtime/context_builder.py
app/schemas/runtime.py
```

### 6.3 接口设计

```python
def get_available_tool_schemas_for_agent(
    self,
    *,
    agent_name: str,
    card: AgentCard,
    principal: Principal | None = None,
    authorization_service: AuthorizationService | None = None,
) -> list[dict[str, Any]]:
    ...
```

过滤规则：

1. 先按 AgentCard 控制 public/private/MCP 可见性。
2. 再按 `enabled` 过滤。
3. 再按 `AuthorizationService.check_tool_access` 过滤。
4. 最终输出 OpenAI function-calling schema。

### 6.4 注意事项

1. 不要把权限字段暴露给 LLM。
2. 不要因为 LLM 看不到某工具，就跳过 ToolExecutor 二次校验。
3. 如果权限服务不可用，生产模式应 fail-closed；开发模式可配置 fail-open。

### 6.5 测试

新增/更新：

```text
tests/test_tool_registry_visibility.py
tests/test_subagent_tool_visibility.py
```

验收：

1. 无权限工具不会进入 LLM tools。
2. 有权限工具仍按 OpenAI function schema 输出。
3. 内部字段不出现在 schema 中。
4. ToolExecutor 仍能拒绝伪造调用。

---

## 7. P0 任务五：DataPermissionVerifier 结果级权限过滤

### 7.1 目标

解决“同一个工具、不同机构/岗位/权限看到不同字段”的问题。

结果级权限过滤在最终回答返回用户前执行，属于 `VerificationService(stage="pre_answer")` 的职责。它不默认拦截或脱敏进入 LLM 的工具结果，以免影响 LLM 对业务事实的判断。

### 7.2 新增文件

```text
app/auth/data_policy.py
app/verification/verifiers/data_permission_verifier.py
tests/test_data_filter_service.py
tests/test_policy_sensitive_data_access.py
```

### 7.3 数据分类

建议用字段策略描述，而不是通过拆工具表达：

```python
class FieldPolicy(BaseModel):
    path: str
    classification: Literal["public", "internal", "confidential", "sensitive"]
    required_data_permissions: list[str] = []
    mask_strategy: Literal["drop", "mask", "hash", "partial"] = "mask"
```

保单字段示例：

| 字段 | 分类 | 需要权限 | 无权限处理 |
|---|---|---|---|
| `policy_no` | internal | `policy.basic.read` | 可部分展示 |
| `status` | internal | `policy.basic.read` | 可展示 |
| `product_name` | internal | `policy.basic.read` | 可展示 |
| `insured_name` | confidential | `policy.customer.read` | 脱敏 |
| `phone` | sensitive | `policy.sensitive.read` | 脱敏或删除 |
| `id_card` | sensitive | `policy.sensitive.read` | 脱敏或删除 |
| `bank_account` | sensitive | `policy.payment.read` | 脱敏或删除 |
| `health_notice` | sensitive | `policy.health.read` | 删除 |

### 7.4 DataPermissionVerifier 接口

```python
class DataPermissionVerifier:
    async def verify(
        self,
        *,
        input: VerificationInput,
    ) -> VerificationResult:
        ...
```

返回：

```python
class DataPermissionCheckResult(BaseModel):
    patched_answer: str | None = None
    redactions: list[RedactionEvent] = []
    blocked: bool = False
    reason: str | None = None
```

### 7.5 接入方式

目标流程：

```text
ToolExecutor.execute
-> Tool/Resource 权限校验通过
-> 执行 tool callable
-> 工具结果进入 ToolCallingRunner observation，供 LLM 判断
-> ToolExecutionLogStore / EvidenceStore 记录工具结果或摘要
-> 最终 answer 进入 VerificationService(stage="pre_answer")
-> DataPermissionVerifier 根据 principal/auth_context/evidence 做字段级过滤
-> 保存并返回 verified answer
```

注意：

1. LLM 前不默认做字段级脱敏，避免影响业务推理。
2. 如果工具结果包含 token、secret、密码、完整内部日志、超出安全域的原始报文等高危内容，`post_tool` verifier 可以阻断或替换为安全摘要。
3. 最终回答前必须由 `VerificationService(stage="pre_answer")` 做字段级权限过滤。
4. 审计中保存 raw result 时需要数据治理策略，可保存摘要、加密引用或受控 evidence。

### 7.6 测试

验收：

1. 普通机构用户最终回答看不到手机号、身份证、银行卡、健康告知。
2. 有敏感权限的用户最终回答可以包含授权字段。
3. LLM 前的工具结果不做默认字段脱敏，但高危原文会被 post_tool verifier 阻断或摘要化。
4. 最终 answer 不包含未授权字段。
5. pre_answer verifier 失败时生产模式 fail-closed。

---

## 8. P0 任务六：ApprovalRequest 绑定身份与权限快照

### 8.1 目标

写操作审批必须可追溯到可信主体、机构、权限快照和资源对象。

### 8.2 修改文件

```text
app/schemas/approval.py
app/approval/store.py
app/approval/service.py
app/approval/client.py
app/runtime/graph.py
```

### 8.3 ApprovalRequest 新增字段

```python
tenant_id: str | None = None
subject: str | None = None
user_id: str | None = None
org_id: str | None = None
org_path: list[str] = []
principal_snapshot: dict[str, Any] = {}
auth_context_snapshot: dict[str, Any] = {}
resource_type: str | None = None
resource_id: str | None = None
tool_operation: str | None = None
tool_required_scopes: list[str] = []
```

已有审批链字段继续保留：

```text
thread_id
checkpoint_id
parent_approval_id
root_approval_id
approval_depth
next_approval_id
idempotency_key
```

### 8.4 create_approval_request 接入

`AgentGraphFactory.create_approval_request` 从 state 中读取：

```text
principal
auth_context
current_approval_id
root_approval_id
approval_depth
```

并保存到 approval table。

### 8.5 外部审批 payload

提交审批系统时 payload 应包含：

```text
approval_id
tenant_id
subject
user_id
org_id
agent_name
tool_name
operation_type
risk_level
resource_type
resource_id
arguments
reason
callback_url
created_at
```

不要把完整敏感 raw result 发给审批系统，除非审批系统具备相同数据安全等级。

### 8.6 测试

新增/更新：

```text
tests/test_approval_identity_audit.py
tests/test_approval_full_flow.py
tests/test_approval_submit_client.py
```

验收：

1. approval_requests 保存可信 tenant/org/user/subject。
2. 审批 payload 包含机构和操作主体。
3. 重复 callback 不重复执行工具。
4. 审批链的 parent/root/depth/next 保持正确。

---

## 9. P1 任务一：Verification Framework 骨架

### 9.1 目标

建立统一验证框架，用于承载：

```text
request_access
agent_access
pre_skill
pre_tool
post_tool
pre_answer
```

长期架构中，Compliance 不再作为独立长期出口设计，而是 `VerificationService(stage="pre_answer")` 下的一个 verifier。

### 9.2 新增目录

```text
app/verification/
  __init__.py
  schemas.py
  base.py
  registry.py
  service.py
  verifiers/
    __init__.py
```

### 9.3 VerificationInput

```python
class VerificationInput(BaseModel):
    stage: Literal[
        "request_access",
        "agent_access",
        "pre_skill",
        "pre_tool",
        "post_tool",
        "pre_answer",
    ]
    request_id: str
    trace_id: str | None = None
    session_key: str | None = None
    principal: dict[str, Any] | None = None
    auth_context: dict[str, Any] = {}
    agent_name: str | None = None
    skill_id: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = {}
    tool_result: Any | None = None
    answer: str | None = None
    evidence: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
```

### 9.4 VerificationResult

```python
class VerificationResult(BaseModel):
    passed: bool
    stage: str
    verifier_name: str
    severity: Literal["info", "warning", "error", "blocking"] = "info"
    action: Literal["allow", "patch", "block", "manual", "retry"] = "allow"
    code: str | None = None
    reason: str | None = None
    patched_output: Any | None = None
    redactions: list[dict[str, Any]] = []
    evidence_ids: list[str] = []
```

### 9.5 BaseVerifier

```python
class BaseVerifier(Protocol):
    name: str
    stages: list[str]

    async def verify(self, input: VerificationInput) -> VerificationResult:
        ...
```

### 9.6 VerificationService

```python
class VerificationService:
    async def verify_all(self, input: VerificationInput) -> list[VerificationResult]:
        ...

    async def aggregate(self, results: list[VerificationResult]) -> VerificationResult:
        ...
```

聚合规则：

1. 任一 `blocking` 失败，最终 `action="block"`。
2. 任一 `manual`，最终 `action="manual"`。
3. 有 `patch` 时按 verifier 顺序应用 patch。
4. 所有 verifier 通过才 `allow`。

### 9.7 初始接入点

```text
Agent selection / dispatch 前 -> stage="agent_access"
ToolExecutor.execute -> stage="pre_tool"
ToolExecutor raw result 后 -> stage="post_tool"
最终返回前 -> stage="pre_answer"
```

不要让 LLM 执行或跳过 Verify；Verify 是服务端 Harness 逻辑。

### 9.8 测试

新增：

```text
tests/test_verification_service.py
```

验收：

1. registry 可注册多个 verifier。
2. `verify_all` 按 stage 执行匹配 verifier。
3. blocking/manual/patch 聚合结果正确。
4. verifier 异常生产模式 fail-closed，开发模式可配置。

---

## 10. P1 任务二：pre_tool verifier

### 10.1 目标

工具执行前统一验证：

1. 工具动作权限。
2. 资源权限。
3. 写工具前置证据。
4. 业务前置条件。
5. 审批前风险判断。

### 10.2 新增 verifier

```text
app/verification/verifiers/agent_access_verifier.py
app/verification/verifiers/tool_authorization_verifier.py
app/verification/verifiers/resource_access_verifier.py
app/verification/verifiers/tool_precondition_verifier.py
```

### 10.3 ToolPreconditionVerifier

示例：保全任务完成后异常处理。

```text
notice_policy_update
  必须已有 query_endo_task_record evidence
  evidence 中 task_type=9
  task_status=E
  response_body 包含“保单更新错误”

notice_customer_update
  必须已有 task_type=9
  task_status=E
  response_body 包含“调用新客户接口异常”

notice_period_update
  必须已有 task_type=9
  task_status=E
  response_body 包含“账单更新异常，失败”

notice_finance
  必须已有 task_type=10
  task_status=E

policy_suspendOrRecovery
  必须已有 task_type=11
  task_status=E
```

没有前置证据时：

```text
不执行工具
不创建审批
返回 verification_failed:missing_precondition_evidence
```

### 10.4 ToolExecutor 接入

```python
verification = await verification_service.verify_all(
    VerificationInput(
        stage="pre_tool",
        principal=...,
        agent_name=agent_name,
        tool_name=tool_name,
        tool_arguments=arguments,
        evidence=evidence,
    )
)
decision = verification_service.aggregate(verification)
if decision.action in {"block", "manual"}:
    return ToolResult(success=False, error=f"verification_failed:{decision.code}")
```

顺序：

```text
required args
-> agent/tool/resource authorization
-> pre_tool verification
-> write approval
-> execute
```

### 10.5 测试

新增：

```text
tests/test_pre_tool_verifier.py
```

验收：

1. 无证据时不能直接调用 notice/write 类工具。
2. 有匹配证据时允许进入审批或执行。
3. 证据不匹配时返回 blocking。
4. LLM 伪造参数无法绕过 verifier。

---

## 11. P1 任务三：pre_answer verifier 与 ComplianceVerifier

### 11.1 目标

最终返回前统一进入：

```text
VerificationService(stage="pre_answer")
```

这个阶段至少包含：

1. `ComplianceVerifier`：内容合规、敏感信息、内部日志、secret/token 等检查。
2. `DataPermissionVerifier`：根据 AuthContext 检查最终 answer 是否泄露无权字段。
3. `EvidenceConsistencyVerifier`：检查确定性结论是否有 evidence 支撑。
4. `RawToolResultLeakVerifier`：防止 raw tool result 或内部结构直接外发。

长期架构里不再把 Compliance 作为独立平级模块设计；它是 Verify 的一个 verifier。

### 11.2 新增文件

```text
app/verification/verifiers/compliance_verifier.py
app/verification/verifiers/data_permission_verifier.py
app/verification/verifiers/evidence_consistency_verifier.py
app/verification/verifiers/raw_tool_result_leak_verifier.py
```

`app/compliance/final_checker.py` 可以作为现有实现迁移来源，但长期架构边界是 `ComplianceVerifier`。

### 11.3 Graph 节点目标

长期节点语义：

```text
pre_answer_verify
-> save_assistant_message
-> compress_short_memory
-> finalize_response
```

目标流程：

```text
answer
-> VerificationService(stage="pre_answer")
   -> ComplianceVerifier
   -> DataPermissionVerifier
   -> EvidenceConsistencyVerifier
   -> RawToolResultLeakVerifier
-> if allow: save verified answer
-> if patch: save patched answer
-> if block: save safe fallback answer
-> if manual: return manual_intervention_required
```

### 11.4 ComplianceVerifier

```python
class ComplianceVerifier:
    name = "compliance"
    stages = ["pre_answer"]

    async def verify(self, input: VerificationInput) -> VerificationResult:
        ...
```

职责：

1. 手机号、身份证、银行卡脱敏。
2. token、secret、password、内部日志字段拦截。
3. raw tool output 泄露拦截。
4. 输出 patch 或 block，不直接绕过 VerificationService。

### 11.5 DataPermissionVerifier

职责：

1. 根据 `principal.data_permissions` 检查 answer。
2. 如果 answer 包含当前主体无权查看的字段，必须 patch/block。
3. 根据 evidence redaction events 检查最终回答是否重新泄露。

### 11.6 EvidenceConsistencyVerifier

职责：

1. 回答中出现“已完成、已失败、已通知、已恢复”等确定性结论时，需要 evidence 支撑。
2. 如果 evidence 不足，改写为“目前没有足够证据确认”。
3. 对 RAG 引用结论要求 citation 或 chunk evidence。

### 11.7 测试

新增：

```text
tests/test_pre_answer_verifier.py
tests/test_compliance_verifier.py
tests/test_data_permission_verifier.py
tests/test_evidence_consistency_verifier.py
```

验收：

1. pre_answer 统一执行多个 verifier。
2. 无敏感权限用户最终回答被脱敏。
3. 无 evidence 的确定性结论被 patch 或 block。
4. raw tool result 不会返回用户。
5. verifier 失败不会保存未验证 answer。

---

## 12. P1 任务四：Evidence Contract / EvidenceStore

### 12.1 目标

把工具结果、RAG chunk、业务诊断结论沉淀为可追溯 evidence，供 verifier、审计、badcase 学习使用。

### 12.2 新增文件

```text
app/evidence/schemas.py
app/evidence/store.py
app/evidence/builder.py
```

### 12.3 Evidence schema

```python
class Evidence(BaseModel):
    evidence_id: str
    request_id: str
    trace_id: str | None = None
    session_key: str
    source_type: Literal["tool", "knowledge", "user", "system", "approval"]
    source_name: str
    content: Any
    summary: str | None = None
    citations: list[dict[str, Any]] = []
    redactions: list[dict[str, Any]] = []
    created_at: str
```

### 12.4 EvidenceStore

SQLite MVP 表：

```text
evidence
  evidence_id
  request_id
  trace_id
  session_key
  source_type
  source_name
  content_json
  summary
  citations_json
  redactions_json
  created_at
```

### 12.5 接入点

```text
ToolExecutor post_tool
-> filtered tool result
-> EvidenceBuilder.from_tool_result
-> EvidenceStore.save

KnowledgeService search/pre_search
-> KnowledgeChunk
-> EvidenceBuilder.from_knowledge_chunk

ApprovalService
-> approval decision
-> EvidenceBuilder.from_approval
```

### 12.6 测试

新增：

```text
tests/test_evidence_store.py
tests/test_evidence_builder.py
```

验收：

1. 工具结果可生成 evidence。
2. RAG chunk 可生成 citation evidence。
3. pre_answer verifier 可读取 request_id 下 evidence。
4. evidence 不直接泄露未授权 raw sensitive fields。

---

## 13. P1 任务五：Knowledge namespace / citation

### 13.1 目标

让 AgentCard 的 `rag_namespaces` 真正影响知识检索范围，并把知识命中作为 evidence/citation。

### 13.2 修改文件

```text
app/knowledge/service.py
app/integrations/knowledge_api_client.py
app/knowledge/chunk_post_processor.py
app/runtime/context_builder.py
app/tools/public_tools.py
app/agents/cards/*.yaml
```

### 13.3 KnowledgeService 接口扩展

```python
class KnowledgeService(Protocol):
    async def search(
        self,
        query: str,
        top_k: int = 3,
        namespaces: list[str] | None = None,
    ) -> list[KnowledgeChunk]:
        ...

    async def pre_search(
        self,
        query: str,
        intent: str,
        top_k: int = 3,
        namespaces: list[str] | None = None,
    ) -> list[KnowledgeChunk]:
        ...
```

### 13.4 ContextBuilder 接入

```text
selected_agent.agent_card.rag_namespaces
-> ContextBuilder._build_subagent_knowledge_hint
-> knowledge_service.search(..., namespaces=rag_namespaces)
```

### 13.5 RAG public tool

`rag_search_tool` 可保留 `query/top_k` 给 LLM；namespace 不建议让 LLM 随意传。应由 Harness 根据当前 AgentCard 注入或限制。

```text
LLM tool args: query, top_k
Harness context: allowed_namespaces from AgentCard/AuthContext
```

### 13.6 Citation

`KnowledgeChunk` 建议包含：

```python
chunk_id: str | None
source: str
score: float
metadata: {
  "namespace": "...",
  "doc_id": "...",
  "title": "...",
  "section": "...",
}
```

pre_answer verifier 可以要求：

```text
涉及知识库规则的确定性回答必须带 citation evidence。
```

### 13.7 测试

新增：

```text
tests/test_knowledge_namespace.py
tests/test_knowledge_citation_evidence.py
```

验收：

1. AgentCard.rag_namespaces 会传入 KnowledgeService。
2. LLM 不能越权指定 namespace。
3. KnowledgeChunk 生成 evidence。
4. pre_answer 可检查知识引用。

---

## 14. P0/P1 汇总实施顺序

| 顺序 | 优先级 | 任务 | 原因 |
|---|---|---|---|
| 1 | P0 | Principal/AuthContext | 所有安全、审计、审批的可信身份基础 |
| 2 | P0 | Agent 级权限 | 防止无权限用户进入不该用的业务能力域 |
| 3 | P0 | ToolDefinition 动作权限元数据 | 为 ToolExecutor 和 Verify 提供动作权限基础 |
| 4 | P0 | ToolExecutor Tool/Resource 鉴权 | 防止 LLM 伪造或越权工具调用 |
| 5 | P0 | ToolRegistry 按 Principal 过滤 schema | 降低 LLM 看到无权限工具的概率 |
| 6 | P0 | DataPermissionVerifier | 防止最终回答泄露未授权字段 |
| 7 | P0 | ApprovalRequest 身份审计字段 | 写操作审批可追溯到机构/用户/权限快照 |
| 8 | P1 | VerificationService 骨架 | 为所有 verifier 提供统一入口 |
| 9 | P1 | pre_tool verifier | 保护写工具和业务前置条件 |
| 10 | P1 | pre_answer verifier + ComplianceVerifier | 统一最终出口校验 |
| 11 | P1 | EvidenceStore | 为 verifier、审计、badcase 提供事实依据 |
| 12 | P1 | Knowledge namespace/citation | RAG 进入权限范围和证据链 |

---

## 15. 第一批建议执行任务

如果只先做 3 到 5 个任务，建议：

1. **Principal/AuthContext**
   - 先把可信身份放进 state。
2. **Agent 级权限 + Tool 级权限骨架**
   - 立刻补最重要安全边界。
3. **ToolExecutor 接入 AuthorizationService / ResourceAccessService**
   - 确保 LLM 伪造工具调用也会被拒绝。
4. **DataPermissionVerifier MVP**
   - 解决“同一个工具不同机构看到不同字段”的核心问题。
5. **VerificationService 骨架**
   - 为后续 ComplianceVerifier、DataPermissionVerifier、EvidenceConsistencyVerifier 提供统一入口。

不建议把 EvidenceStore、Knowledge citation、所有 verifier 一次性全接入。它们依赖前面的 Auth/DataFilter/Verification 基础，适合第二批。

---

## 16. 不建议一次性做的内容

1. 不要让 LLM 判断用户权限。
2. 不要把敏感字段权限拆成多个相似 LLM function。
3. 不要把无权访问的资源结果给 LLM；但对于已授权执行的工具，不默认在 LLM 前做字段级脱敏。
4. 不要同时做 Auth、Verification、Evidence、Learning 全量闭环。
5. 不要立刻把所有 SubAgent 改成 SubAgentGraph。
6. 不要自动回灌 Skill 或规则，Badcase Learning 必须人工审核。
7. 不要把 `.env` 或真实密钥纳入任何设计样例。

---

## 17. 验收总表

| 能力 | 验收标准 |
|---|---|
| Principal | `/api/chat` state 中有 principal/auth_context |
| 可信身份 | Header/JWT/Auth Gateway claims 是生产唯一身份来源 |
| 身份冲突 | body tenant/user 与 principal 冲突时不能覆盖 principal |
| Agent 级权限 | 无权 Agent 不会被选择或 dispatch |
| Tool schema 过滤 | 无权限工具不出现在 LLM tools |
| ToolExecutor 鉴权 | LLM 伪造 tool_call 也会被拒绝 |
| Resource access | 机构无权访问某 policy_no/claim_no 时拒绝 |
| Result 级过滤 | 同一个 `query_policy_info` 对不同权限生成不同最终回答 |
| DataPermissionVerifier | 普通用户最终回答看不到手机号、身份证、健康告知、银行卡 |
| Approval audit | approval_requests 保存 tenant/org/user/principal snapshot |
| VerificationService | request/agent/pre_tool/post_tool/pre_answer stage 可注册 verifier |
| ComplianceVerifier | 合规检查作为 pre_answer verifier 执行 |
| pre_tool verifier | 无前置证据写工具不会进入审批 |
| pre_answer verifier | 无 evidence 的确定性结论会被 patch/block |
| EvidenceStore | 可按 request_id 查询工具/RAG/审批 evidence |
| Knowledge namespace | AgentCard.rag_namespaces 影响检索范围 |

---

## 18. 测试文件清单

建议新增：

```text
tests/test_auth_context.py
tests/test_agent_authorization.py
tests/test_tool_definition_permissions.py
tests/test_tool_authorization_scopes.py
tests/test_resource_access_service.py
tests/test_data_filter_service.py
tests/test_policy_sensitive_data_access.py
tests/test_approval_identity_audit.py
tests/test_verification_service.py
tests/test_pre_tool_verifier.py
tests/test_pre_answer_verifier.py
tests/test_compliance_verifier.py
tests/test_data_permission_verifier.py
tests/test_evidence_store.py
tests/test_evidence_builder.py
tests/test_evidence_consistency_verifier.py
tests/test_knowledge_namespace.py
tests/test_knowledge_citation_evidence.py
```

建议更新：

```text
tests/test_tool_schema_openai.py
tests/test_tool_executor_authorization.py
tests/test_approval_full_flow.py
tests/test_approval_submit_client.py
tests/test_subagent_tool_visibility.py
tests/test_tool_registry_visibility.py
```
