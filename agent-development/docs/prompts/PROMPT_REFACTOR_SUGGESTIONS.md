# Prompt Refactor Suggestions

本文给出后续 prompt 改造建议。当前项目仍应保持 MVP 稳定，不建议一次性把所有规则替换为 LLM prompt。

## 是否应该把 Query Rewrite 从规则改为 Prompt

建议：可以逐步改，但不要直接替换。

原因：

- 当前规则覆盖了 `REQ_xxx + E102` 和多轮追问两个核心验收场景，稳定且可测试。
- LLM 改写可能带来 requestId 编造、错误码丢失、输出不稳定等风险。

推荐路径：

1. 保留当前规则优先。
2. 对规则无法处理的复杂 query，引入 LLM rewrite fallback。
3. 使用 JSON schema 输出。
4. 增加 prompt evaluation 测试集。

## 是否应该把 Intent Recognition 从规则改为 Prompt 或分类器

建议：中期可以引入分类器，但当前规则仍应保留为 guardrail。

可选方案：

- 规则优先 + LLM fallback。
- 小模型文本分类器。
- LLM JSON 分类。

建议保留强规则：

- `REQ_` + `E102` -> `troubleshooting`
- 敏感信息 / token / password -> `compliance_review`
- `签名规则变更` / `字段变更` -> `change_impact_analysis`

## 是否应该把 ContextBuilder 的 System Prompt 模板配置化

建议：在真正接入 LLM runtime loop 前再做。

当前 `ContextBuilder` 只构建结构化上下文，不构造 system prompt。过早配置化会增加维护成本，但不会带来运行时收益。

建议未来拆分：

- main agent system prompt
- subagent system prompt
- final answer prompt
- tool selection prompt
- memory compression prompt

## 是否应该把 SKILL.md 作为真正的 Prompt Source of Truth

建议：是，但要明确边界。

`SKILL.md` 适合作为子 Agent 的任务级 instruction source of truth，尤其包含：

- 任务目标
- 使用场景
- 工具使用建议
- 输出结构
- 注意事项

但不建议把所有 prompt 都塞进 `SKILL.md`。例如 query rewrite、intent recognition、memory compression 更适合独立 prompt 模板。

## 是否应该新增 PromptRegistry

建议：后续需要。

`PromptRegistry` 可以负责：

- 按 `prompt_id` 和 `version` 读取 prompt。
- 校验输入变量。
- 渲染 prompt。
- 记录 prompt metadata。
- 支持启用/禁用和回滚。

但当前不要把 `docs/prompts` 作为 `PromptRegistry` 来源。

## 是否应该支持 Prompt Version

建议：需要。

至少应记录：

- `prompt_id`
- `version`
- `status`
- `owner`
- `created_at`
- `change_reason`
- `input_schema`
- `output_schema`
- `evaluation_set`

## 是否应该支持 Prompt Evaluation

建议：需要，而且应先于生产启用。

最小评估集应覆盖：

- `REQ_001 为什么返回 E102？`
- `REQ_002 的 E102 是谁的问题？`
- 多轮追问：`那这个一般是谁的问题？`
- 合规文本包含手机号/身份证/token。
- 文档解析 markdown/json/yaml。
- 签名规则变更影响分析。

评估指标：

- intent 准确率
- rewritten_query 是否保留 requestId/error_code
- selected_skill_id 是否正确
- 是否编造事实
- 输出 JSON 是否符合 schema

## 是否应该支持 Prompt Rollback

建议：需要。

Prompt 改动会影响路由、工具调用和回答质量，必须支持：

- 快速回滚到上一版本。
- 按 session 或 tenant 灰度。
- 保留 prompt version 到运行日志和 checkpoint。
- 与测试集结果绑定。

## 推荐分阶段改造路线

### 阶段 1：文档盘点

当前本目录就是阶段 1：

- 盘点现有 prompt-like 内容。
- 明确规则实现和 prompt 实现边界。
- 不影响运行时。

### 阶段 2：PromptRegistry 只读原型

新增 `PromptRegistry`，但不接主链路：

- 从独立配置目录读取 prompt。
- 支持 version。
- 支持渲染变量。
- 编写单元测试。

### 阶段 3：Query Rewrite LLM Fallback

保留当前规则，新增 LLM fallback：

- 规则命中时不调用 LLM。
- 规则不确定时调用 LLM。
- 输出必须 JSON schema 校验。

### 阶段 4：Intent Recognition 双跑评估

规则和 LLM 分类双跑：

- 线上仍用规则结果。
- 记录 LLM 分类结果和差异。
- 离线评估稳定后再灰度。

### 阶段 5：SubAgent Runtime Loop Prompt 化

让 selected `SKILL.md` 真正成为子 Agent prompt 的一部分：

- `ContextBuilder` 构造 subagent messages。
- 子 Agent 使用 LLM 生成结构化计划或回答。
- 工具调用仍必须经过 `ToolBroker / PolicyGate`。

### 阶段 6：Prompt Evaluation / Rollback

上线前补齐：

- prompt evaluation suite
- prompt version tracking
- prompt rollback
- prompt audit log

## 当前不要做

- 不要从 `docs/prompts` 读取运行时 prompt。
- 不要删除当前规则实现。
- 不要让 LLM 绕过 `ToolBroker / PolicyGate`。
- 不要把所有业务规则塞进单个大 system prompt。
- 不要一次性替换所有子 Agent 的规则逻辑。

