# 保全实时查询智能体（pos_query_agent）实施任务

## 目标

新增一个子 Agent：

```text
agent_name: pos_query_agent
display_name: 保全实时查询智能体
```

该智能体负责通过实时 POS API 查询健康险保全业务信息，覆盖：

1. 线上可做保全项查询
2. 退保试算详情查询
3. 保全保单标准查询
4. 批文查询
5. 退保任务提交校验

接口来源：`api/onlineApi.md`。

本任务不使用 curl / shell。所有接口调用必须走 Python tool -> `ToolExecutor` -> `PosAPIClient` / `httpx.AsyncClient`，并继续受 ToolRegistry、AuthorizationService、VerificationService、ToolExecutionLogStore 约束。

## 设计结论

### 1. Agent 层不设置必需实体

`pos_query_agent` 覆盖多类查询，每类查询需要的参数不同，因此 AgentCard 层不设置全局 `required_entities`。

推荐：

```yaml
required_entities: []
optional_entities:
  - policy_no
  - customer_no
  - apply_seq
  - endorseType
  - applyDate
  - surDate
  - payMode
  - acceptDate
  - surrenderReason
  - taskSrc
  - operatorId
```

职责边界：

```text
AgentCard：粗粒度能力召回和路由
Skill：判断用户要查哪一类 POS 接口、缺哪些参数
Tool schema：单个工具的 required 参数兜底校验
ToolExecutor：权限、pre_tool verify、执行日志
VerificationService：最终回答前数据权限和合规过滤
```

### 2. 所有 POS 工具均为 read

本批接口语义是查询、校验、试算，不直接改变业务状态。

因此全部工具：

```text
is_write = false
operation = read
```

说明：`submitVerify` 虽然名字包含 submit，但当前业务定义为“任务提交前校验”，不是实际提交保全任务，因此按 read 处理。

### 3. 批文查询工具命名

批文查询统一命名为：

```text
pos_query_approval_text
```

对应接口：

```text
/epos/task/report/queryPreserveChangeDetail
```

### 4. 只新增一个 Skill

先放在一个 Skill 中：

```text
skill_id: pos_query_agent.realtime_query
```

Skill body 内部说明 5 类查询的工具选择规则、必要参数、默认值和返回口径。

### 5. 工具正常调用 PosAPIClient

工具不使用 mock 主链路，不使用 shell/curl。

生产链路：

```text
ToolCallingRunner
-> ToolExecutor
-> pos private tool
-> PosAPIClient
-> httpx.AsyncClient.post
-> ToolResult observation
-> LLM 读取接口返回关键节点组织回答
-> pre_answer_verify
```

测试中可注入 fake `PosAPIClient`。

## 实施步骤

## 1. 新增 POS API Client

新增文件：

```text
app/integrations/pos_api_client.py
```

建议接口：

```python
class PosAPIClient:
    def __init__(self, *, base_url: str, timeout: float = 10.0, enabled: bool = True) -> None:
        ...

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...
```

要求：

- 使用 `httpx.AsyncClient`
- 支持 timeout
- 支持 full URL 或 base_url + path
- `enabled=False` 时返回可控错误或抛出清晰异常，不静默伪造成功
- 记录最少必要日志：api_name/path、success、duration_ms、error
- 不在 client 中理解业务参数，只负责 HTTP 调用和基础错误归一化

建议返回结构：

```python
{
    "success": True,
    "path": "...",
    "request_payload": {...},
    "response": {...},
}
```

## 2. 新增配置

修改：

```text
app/config/settings.py
.env.example
```

建议新增：

```env
ENABLE_POS_API=false
POS_API_BASE_URL=http://ehis-epos-gateway.paic.com.cn
POS_API_TIMEOUT=10
```

说明：

- 本地默认可以关闭真实 POS API。
- 如果 `ENABLE_POS_API=true`，必须有 `POS_API_BASE_URL`。
- 测试使用 fake client，不依赖真实网络。

## 3. 注册 PosAPIClient 依赖

修改：

```text
app/main.py
```

建议：

```python
pos_api_client = PosAPIClient(
    base_url=settings.pos_api_base_url,
    timeout=settings.pos_api_timeout,
    enabled=settings.enable_pos_api,
)
```

然后传入工具注册函数。

如果当前 `register_agent_private_tools(registry)` 不支持注入 client，可改为：

```python
register_agent_private_tools(registry, pos_api_client=pos_api_client)
```

要求保持对现有测试兼容：`pos_api_client` 可选，未传时使用 disabled client 或构造默认 client。

## 4. 新增 POS private tools

修改：

```text
app/tools/agent_tools.py
```

新增 5 个工具，全部注册到：

```text
agent_name = pos_query_agent
```

### 4.1 pos_query_available_items

用途：查询线上可做保全项。

接口：

```text
POST /process/api/i/endotItemType/list
```

工具入参 schema：

```json
{
  "type": "object",
  "properties": {
    "policyNo": {
      "type": "string",
      "description": "保单号。"
    },
    "customerNo": {
      "type": "string",
      "description": "保单上的客户号。"
    },
    "src": {
      "type": "integer",
      "description": "来源，默认 16。"
    }
  },
  "required": ["policyNo", "customerNo"]
}
```

内部 payload：

```json
{
  "policyNo": "<policyNo>",
  "src": 16,
  "currentLoginUserInfo": {
    "customerNo": "<customerNo>"
  }
}
```

### 4.2 pos_calc_surrender_premium

用途：退保试算详情查询。

接口：

```text
POST /process/api/premium/calc
```

工具入参 schema：

```json
{
  "type": "object",
  "properties": {
    "applyDate": {
      "type": "integer",
      "description": "受理日期毫秒时间戳。"
    },
    "policyNo": {
      "type": "string",
      "description": "保单号。"
    },
    "endorseType": {
      "type": "string",
      "description": "保全项，默认 001028。"
    },
    "taskSrc": {
      "type": "string",
      "description": "任务来源，默认 01。"
    },
    "surrenderType": {
      "type": "string",
      "description": "退保类型，默认 1。"
    },
    "surDate": {
      "type": "integer",
      "description": "退保日期毫秒时间戳。"
    },
    "commission": {
      "type": "string",
      "description": "佣金标识，默认 1。"
    },
    "operatorId": {
      "type": "string",
      "description": "操作人，优先从 Principal.user_id 获取。"
    }
  },
  "required": ["applyDate", "policyNo", "surDate"]
}
```

工具内部：

- `endorseType` 默认 `001028`
- `taskSrc` 默认 `01`
- `surrenderType` 默认 `1`
- `commission` 默认 `1`
- `operatorId` 优先从 `auth_context.principal.user_id` 获取

### 4.3 pos_query_policy_standard

用途：保全保单标准查询。

接口：

```text
POST /epos/policy/standard/query
```

工具入参 schema：

```json
{
  "type": "object",
  "properties": {
    "policyNo": {
      "type": "string",
      "description": "保单号，工具内部映射为接口字段 polNo。"
    },
    "withInsureds": {
      "type": "string",
      "description": "是否携带被保人信息，默认 Y。"
    },
    "extensions": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "扩展信息，默认 pollist、assuredPolicyInfo、pollLock。"
    }
  },
  "required": ["policyNo"]
}
```

内部 payload：

```json
{
  "polNo": "<policyNo>",
  "withInsureds": "Y",
  "extensions": ["pollist", "assuredPolicyInfo", "pollLock"]
}
```

### 4.4 pos_query_approval_text

用途：通过受理号查询批文 / 保全变更详情。

接口：

```text
POST /epos/task/report/queryPreserveChangeDetail
```

工具入参 schema：

```json
{
  "type": "object",
  "properties": {
    "applySeq": {
      "type": "string",
      "description": "受理号。"
    },
    "pageSize": {
      "type": "integer",
      "description": "分页大小，默认 0。"
    },
    "pageNo": {
      "type": "integer",
      "description": "页码，默认 1。"
    },
    "operatorId": {
      "type": "string",
      "description": "操作人，优先从 Principal.user_id 获取。"
    }
  },
  "required": ["applySeq"]
}
```

### 4.5 pos_submit_verify

用途：退保任务提交前校验。

接口：

```text
POST /process/process/submitVerify
```

工具入参 schema 推荐扁平化，不直接暴露深层接口结构给 LLM：

```json
{
  "type": "object",
  "properties": {
    "policyNo": {
      "type": "string",
      "description": "保单号。"
    },
    "endorseType": {
      "type": "string",
      "description": "保全项，默认 001028。"
    },
    "payMode": {
      "type": "string",
      "description": "支付方式，默认 Y。"
    },
    "acceptDate": {
      "type": "integer",
      "description": "受理日期毫秒时间戳。"
    },
    "surrenderReason": {
      "type": "string",
      "description": "退费原因，默认 11。"
    },
    "taskSrc": {
      "type": "string",
      "description": "任务来源，默认 31。"
    },
    "operatorId": {
      "type": "string",
      "description": "操作人，优先从 Principal.user_id 获取。"
    }
  },
  "required": ["policyNo", "acceptDate"]
}
```

内部 payload：

```json
{
  "data": {
    "acceptInfo": {
      "acceptDate": "<acceptDate>",
      "endorseType": "<endorseType>",
      "surrenderReason": "<surrenderReason>",
      "taskSrc": "<taskSrc>"
    },
    "chargeRefundInfo": {
      "accountInfos": [
        {
          "payMode": "<payMode>"
        }
      ],
      "policyInfos": {
        "policyNo": "<policyNo>"
      }
    },
    "operatorId": "<operatorId>"
  }
}
```

## 5. operatorId 可信来源

实现原则：

```text
operatorId 优先取 auth_context.principal.user_id
其次才使用 LLM/tool arguments 传入的 operatorId
仍缺失时，如果该接口需要 operatorId，则返回 missing_required_argument:operatorId
```

不要优先信任 LLM 传入的 operatorId。

## 6. 新增 AgentCard

新增文件：

```text
app/agents/cards/pos_query_agent.yaml
```

建议内容：

```yaml
agent_name: pos_query_agent
display_name: 保全实时查询智能体
description: 负责健康险保全实时接口查询，包括可做保全项、退保试算详情、保全保单标准查询、批文查询和退保提交校验。
capabilities:
  - 保全实时查询
  - 可做保全项查询
  - 退保试算详情查询
  - 保全保单标准查询
  - 批文查询
  - 退保提交校验
supported_intents:
  - pos_query
  - pos_available_items
  - pos_surrender_premium_calc
  - pos_policy_standard_query
  - pos_approval_text_query
  - pos_submit_verify
required_entities: []
optional_entities:
  - policy_no
  - customer_no
  - apply_seq
  - endorseType
  - applyDate
  - surDate
  - payMode
  - acceptDate
  - surrenderReason
  - taskSrc
  - operatorId
private_tools:
  - pos_query_available_items
  - pos_calc_surrender_premium
  - pos_query_policy_standard
  - pos_query_approval_text
  - pos_submit_verify
public_tools_allowed: false
mcp_tools: []
mcp_tool_scopes: []
skills:
  - pos_query_agent.realtime_query
rag_namespaces: []
memory_policy:
  recent_turns: 8
enabled: true
version: "1.0.0"
```

如需要做 Agent 级鉴权，可加：

```yaml
access_policy:
  required_scopes:
    - pos:read
```

## 7. 新增子 Agent 类并注册

新增文件：

```text
app/subagents/pos_query_agent.py
```

建议：

```python
class PosQueryAgent(BaseSubAgent):
    name = "pos_query_agent"
```

只继承 `BaseSubAgent`，不自定义 `run`。

注册位置：

```text
app/bootstrap/agents.py::build_subagent_manager
```

新增：

```python
manager.register(
    "pos_query_agent",
    PosQueryAgent(
        context_builder=context_builder,
        tool_executor=tool_executor,
        tool_calling_runner=tool_calling_runner,
    ),
)
```

## 8. 新增 Skill

新增文件：

```text
app/skills/pos_query_agent/realtime_query/SKILL.md
```

metadata：

```yaml
---
skill_id: pos_query_agent.realtime_query
name: 保全实时查询
description: 用于实时查询可做保全项、退保试算详情、保全保单标准信息、批文信息和退保提交校验。
agent: pos_query_agent
intent_tags:
  - pos_query
  - pos_available_items
  - pos_surrender_premium_calc
  - pos_policy_standard_query
  - pos_approval_text_query
  - pos_submit_verify
required_entities: []
optional_entities:
  - policy_no
  - customer_no
  - apply_seq
  - endorseType
  - applyDate
  - surDate
  - payMode
  - acceptDate
  - surrenderReason
  - taskSrc
  - operatorId
private_tools:
  - pos_query_available_items
  - pos_calc_surrender_premium
  - pos_query_policy_standard
  - pos_query_approval_text
  - pos_submit_verify
enabled: true
is_default: true
business_domain:
  - health_insurance_pos
required_context: []
---
```

Skill body 必须写清楚：

1. 先判断用户要查哪一类 POS 接口。
2. 不要因为缺少所有可能参数而澄清。
3. 只针对当前查询类型澄清该工具必需参数。
4. 调用工具后，不要原样输出完整 JSON。
5. 根据用户问题读取接口返回中的关键节点组织回答。
6. 若结果包含敏感信息，最终仍由 VerificationService 做过滤。

推荐工具选择规则：

| 用户问题 | 工具 |
|---|---|
| 能做哪些保全项 / 可做保全项 | `pos_query_available_items` |
| 退保试算 / 试算详情 / 退保金额 | `pos_calc_surrender_premium` |
| 保单查询 / 保单标准查询 / 保单锁定 / 被保人扩展信息 | `pos_query_policy_standard` |
| 批文查询 / 保全批文 / 变更详情 / 受理号完成结果 | `pos_query_approval_text` |
| 退保提交校验 / 提交前校验 / 支付方式校验 | `pos_submit_verify` |

## 9. 实体抽取配置

修改：

```text
app/query/entity_patterns.yaml
```

确认或新增：

```text
policy_no
apply_seq
customer_no
endorseType
payMode
operatorId
```

建议支持中文提示词：

```text
保单号 -> policy_no
受理号 / applySeq / apply_seq -> apply_seq
客户号 / customerNo / customer_no -> customer_no
保全项 / endorseType -> endorseType
支付方式 / payMode -> payMode
操作人 / operatorId -> operatorId
```

日期字段如 `applyDate`、`surDate`、`acceptDate` 可以先由 LLM 根据用户输入补充；如需稳定抽取，再补日期解析策略。

## 10. Intent / Agent Selection

原则上不硬编码选择 `pos_query_agent`。

依赖：

```text
AgentCard.supported_intents
AgentCard.capabilities
AgentCard.examples
IntentRecognitionNode prompt
AgentSelection hybrid router
```

如现有 fallback 规则无法识别 POS 场景，可补充新架构下的 fallback 规则：

```text
保全 / 批文 / 试算 / 提交校验 / 可做保全项 -> pos_query
```

不要把 tool selection 放回 intent_recognition。

## 11. 权限设计

建议分三层：

### Agent 级

可选：

```yaml
access_policy:
  required_scopes:
    - pos:read
```

### Tool 级

建议每个 ToolDefinition 配置不同 scope：

```text
pos_query_available_items: pos:item:read
pos_calc_surrender_premium: pos:premium:calc
pos_query_policy_standard: pos:policy:read
pos_query_approval_text: pos:approval_text:read
pos_submit_verify: pos:submit_verify:read
```

### Result 级

最终回答仍走：

```text
pre_answer_verify -> VerificationService -> DataPermissionVerifier + ComplianceVerifier
```

敏感字段是否展示由 `Principal.data_permissions` 和 `field_visibility_policy.yaml` 决定。

## 12. 测试计划

### 12.1 AgentCard / Skill 校验

新增或更新：

```text
tests/test_pos_query_agent_card.py
```

覆盖：

- `pos_query_agent.yaml` 可以加载
- `AgentCard.skills` 中 `pos_query_agent.realtime_query` 存在
- AgentCard 声明的 private_tools 全部已注册
- Skill.private_tools 不越权
- `required_entities=[]`
- `is_default=true`

### 12.2 Tool schema 测试

新增：

```text
tests/test_pos_query_tools_schema.py
```

覆盖：

- 5 个 POS 工具均为 OpenAI function-calling schema
- required 参数正确
- `is_write` 不出现在 LLM schema
- 5 个 POS 工具全部 `is_write=False`

### 12.3 PosAPIClient 测试

新增：

```text
tests/test_pos_api_client.py
```

覆盖：

- 正常 POST payload
- base_url + path 拼接
- timeout 配置
- API 异常可控返回或抛出清晰错误
- 不依赖真实 POS API

使用 fake httpx 或 monkeypatch。

### 12.4 POS 工具执行测试

新增：

```text
tests/test_pos_query_tools.py
```

覆盖：

- `pos_query_available_items` payload 映射
- `pos_calc_surrender_premium` 默认值填充
- `pos_query_policy_standard` 将 `policyNo` 映射为 `polNo`
- `pos_query_approval_text` 使用 `applySeq`
- `pos_submit_verify` 扁平参数组装为深层 `data`
- `operatorId` 优先从 Principal.user_id 获取
- 缺 required 参数由 ToolExecutor 返回 missing_required_argument

### 12.5 子 Agent tool loop 测试

新增：

```text
tests/test_pos_query_agent_tool_loop.py
```

用 fake LLM 模拟：

1. 用户问“查保单可做哪些保全项”
2. LLM 调用 `pos_query_available_items`
3. fake PosAPIClient 返回结果
4. LLM 根据 observation 返回最终 answer
5. 最终经过 pre_answer_verify

### 12.6 主流程路由测试

新增或更新：

```text
tests/test_pos_query_agent_routing.py
```

覆盖：

- “保全批文查询，受理号 xxx” 能选择 `pos_query_agent`
- “退保试算详情” 能选择 `pos_query_agent`
- “可做保全项” 能选择 `pos_query_agent`
- 不应误路由到 `troubleshooting_agent`

## 13. 验收标准

必须满足：

- `/api/chat` 可以把 POS 查询类问题路由到 `pos_query_agent`
- `pos_query_agent` 通过一个 `realtime_query` Skill 执行
- Skill selection 阶段只读 metadata，不提前加载所有 Skill body
- 5 个 POS 工具都只对 `pos_query_agent` 可见
- 5 个 POS 工具 schema 完整，LLM 能看到 description 和 parameters
- 5 个 POS 工具均 `is_write=False`
- POS 工具不走 shell / curl
- POS 工具通过 `PosAPIClient` 调用 API
- operatorId 优先从 `auth_context.principal.user_id` 获取
- 工具返回后由 LLM 根据返回节点组织回答
- 最终回答进入 `pre_answer_verify`
- 全量 `uv run python -m compileall app tests` 通过
- 全量 `uv run pytest` 通过

## 14. 不做事项

本任务不要做：

- 不要让 LLM 生成 curl
- 不要使用 shell_exec 调接口
- 不要把 POS 工具注册为 public tools
- 不要把 POS 工具给所有 Agent
- 不要把 `submitVerify` 当写操作审批，除非后续确认它会产生业务状态变更
- 不要在 intent_recognition 中选择工具
- 不要把完整接口返回长期写入 memory
- 不要绕过 ToolExecutor
- 不要绕过 VerificationService

## 15. 推荐实施顺序

1. `PosAPIClient` + settings
2. POS private tools + schema
3. AgentCard + SubAgent 注册
4. 单个 realtime_query Skill
5. entity_patterns 补充
6. 路由 fallback 微调
7. 单元测试
8. 主流程集成测试
9. 全量 compileall / pytest

