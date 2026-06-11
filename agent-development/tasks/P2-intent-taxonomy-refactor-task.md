# P2 任务：引入 IntentTaxonomy，理清 intent / sub_intent / AgentCard / Skill 边界

## 任务背景

当前项目已经将 AgentCard 中的意图字段初步拆分为：

```text
supported_intents = 顶层业务意图
supported_sub_intents = 顶层意图下的细分场景
capabilities = 能力画像，仅作为分类和打分证据
```

这解决了 `capabilities`、`supported_intents`、`sub_intent` 混用的问题。但长期看，意图体系仍然分散在各个 AgentCard 中：

```text
AgentCard 自己声明 supported_intents
AgentCard 自己声明 supported_sub_intents
IntentRecognitionNode 从 AgentCard summaries 推导候选空间
Skill 通过 intent_tags 间接匹配 sub_intent
```

当后续重新增加 `claim_query`、`policy_query`、`compliance_review`、更多 POS 或排障场景时，容易再次出现：

```text
大类意图、小类意图、能力、Agent 名称、Skill 标签边界不清
```

本任务目标是引入全局 `IntentTaxonomy`，让系统认识哪些业务意图有唯一来源。

---

## 目标架构

长期边界如下：

```text
IntentTaxonomy:
  定义系统认识哪些业务意图和细分场景

AgentCard:
  定义哪个 agent 能处理哪些 intent/sub_intent

Skill:
  定义某个 agent 内部如何处理具体 sub_intent

Capabilities:
  描述 agent/skill 的能力画像，只辅助判断和打分
```

主流程应变为：

```text
用户 query
  -> query_rewrite 抽取 entities / conversation_window
  -> intent_recognition 根据 IntentTaxonomy 输出 intent/sub_intent
  -> agent_selection 根据 AgentCard.supported_routes 选择 agent
  -> skill_selection 根据 SkillMetadata.intent/sub_intents 选择 skill
  -> required entity check
  -> tool calling
```

---

## 设计原则

1. `intent` 和 `sub_intent` 的合法值只能来自全局 `IntentTaxonomy`。
2. AgentCard 不能创造新的 intent/sub_intent，只能引用 taxonomy 中已有值。
3. Skill 不能创造新的 intent/sub_intent，只能引用 taxonomy 中已有值。
4. `capabilities` 只作为描述、召回、打分和 LLM 分类证据，不作为合法分类值。
5. `agent_name` 不是 intent。
6. `skill_id` 不是 intent。
7. 支持一个 agent 覆盖多个顶层 intent，但 sub_intent 必须按 intent 分组，不能使用扁平列表造成归属不清。
8. LLM 输出非法 intent/sub_intent 时必须被校验拦截，并回退到规则或澄清。
9. 本任务不新增业务 agent，只重构意图体系的声明、加载、校验和消费方式。

---

## 目标数据结构

### 1. 新增 IntentTaxonomy

新增文件：

```text
app/config/intent_taxonomy.yaml
```

建议结构：

```yaml
intents:
  troubleshooting:
    display_name: 问题排查
    description: 诊断退保失败、保全完成后异常等生产问题。
    examples:
      - 退保失败，帮我排查
      - 保全任务完成了，但是保单信息没有更新
    sub_intents:
      refund_failure:
        display_name: 退保失败
        description: 退保未成功、退保任务失败、退保链路异常。
      endo_completion_aftercare:
        display_name: 保全完成后异常
        description: 保全任务完成后保单未更新、未解锁、未退费、未发短信。

  pos_query:
    display_name: 保全实时查询
    description: 查询可做保全项、退保试算、批文、保全保单标准信息和提交校验。
    sub_intents:
      pos_available_items:
        display_name: 可做保全项查询
        description: 查询保单线上可做保全项。
      pos_surrender_premium_calc:
        display_name: 退保试算详情
        description: 查询退保试算金额和明细。
      pos_policy_standard_query:
        display_name: 保全保单标准查询
        description: 查询保全保单标准信息。
      pos_approval_text_query:
        display_name: 保全批文查询
        description: 查询保全批文或保全变更详情。
      pos_submit_verify:
        display_name: 退保提交校验
        description: 退保任务提交前校验。
```

### 2. AgentCard 改为 supported_routes

当前结构：

```yaml
supported_intents:
  - troubleshooting
supported_sub_intents:
  - refund_failure
  - endo_completion_aftercare
```

目标结构：

```yaml
supported_routes:
  troubleshooting:
    - refund_failure
    - endo_completion_aftercare
```

POS Agent 示例：

```yaml
supported_routes:
  pos_query:
    - pos_available_items
    - pos_surrender_premium_calc
    - pos_policy_standard_query
    - pos_approval_text_query
    - pos_submit_verify
```

兼容策略：

- 第一阶段可以保留 `supported_intents` / `supported_sub_intents` 作为兼容字段。
- 新代码优先读取 `supported_routes`。
- 兼容期内，如果只配置旧字段，可转换为：

```text
supported_routes[first supported_intent] = supported_sub_intents
```

- 完成迁移后，再删除旧字段或标记 deprecated。

### 3. Skill 元数据绑定 intent/sub_intent

目标结构建议：

```yaml
skill_id: troubleshooting_agent.endo_completion_aftercare
agent: troubleshooting_agent
intent: troubleshooting
sub_intents:
  - endo_completion_aftercare
```

兼容策略：

- 当前已有 `intent_tags`，第一阶段保留。
- 新增 `intent` 和 `sub_intents` 字段。
- Skill selection 优先使用 `intent/sub_intents`，再兼容 `intent_tags`。

---

## 涉及文件

### 需要新增

- `app/config/intent_taxonomy.yaml`
- `app/schemas/intent_taxonomy.py`
- `app/query/intent_taxonomy_loader.py`
- `tests/test_intent_taxonomy_loader.py`

### 需要修改

- `app/schemas/agent_card.py`
- `app/agents/card_loader.py`
- `app/runtime/graph.py`
- `app/query/intent_recognition_node.py`
- `app/prompts/intent_recognition/system.md`
- `app/prompts/intent_recognition/user.md`
- `app/agents/llm_router.py`
- `app/skills/catalog.py`
- `app/schemas/skill.py`
- `app/skills/scorer.py`
- `app/skills/reranker.py`
- `app/agents/cards/troubleshooting_agent.yaml`
- `app/agents/cards/pos_query_agent.yaml`
- `app/skills/troubleshooting_agent/*/SKILL.md`
- `app/skills/pos_query_agent/*/SKILL.md`

### 需要更新测试

- `tests/test_agent_card_loader.py`
- `tests/test_agent_selection_hybrid_router.py`
- `tests/test_intent_recognition_llm_json.py`
- `tests/test_intent_recognition.py`
- `tests/test_prompt_templates.py`
- `tests/test_skill_catalog.py`
- `tests/test_skill_scoring_policy.py`
- `tests/test_skill_selector.py`
- `tests/test_skill_selector_llm_rerank.py`
- `tests/test_skill_selection_end_to_end.py`
- `tests/test_pos_query_agent.py`

---

## 详细实施步骤

### 1. 定义 IntentTaxonomy schema

新增：

```text
app/schemas/intent_taxonomy.py
```

建议模型：

```python
class SubIntentDefinition(BaseModel):
    display_name: str
    description: str
    examples: list[str] = Field(default_factory=list)

class IntentDefinition(BaseModel):
    display_name: str
    description: str
    examples: list[str] = Field(default_factory=list)
    sub_intents: dict[str, SubIntentDefinition] = Field(default_factory=dict)

class IntentTaxonomy(BaseModel):
    intents: dict[str, IntentDefinition]
```

验收：

- 能加载 `intent_taxonomy.yaml`。
- 空 `intents` 失败。
- 重复或空 key 失败。

### 2. 实现 IntentTaxonomyLoader

新增：

```text
app/query/intent_taxonomy_loader.py
```

职责：

```text
load()
list_allowed_intents()
list_candidate_sub_intents()
is_allowed_intent(intent)
is_allowed_sub_intent(intent, sub_intent)
summaries_for_prompt()
```

验收：

- `list_allowed_intents()` 返回 taxonomy 顶层 key。
- `list_candidate_sub_intents()` 返回 `{intent: [sub_intent...]}`。
- `is_allowed_sub_intent("troubleshooting", "endo_completion_aftercare") == True`。
- `is_allowed_sub_intent("pos_query", "endo_completion_aftercare") == False`。

### 3. AgentCard 支持 supported_routes

修改：

```text
app/schemas/agent_card.py
```

新增字段：

```python
supported_routes: dict[str, list[str]] = Field(default_factory=dict)
```

建议增加规范化属性：

```python
def normalized_supported_routes(self) -> dict[str, list[str]]:
    ...
```

兼容逻辑：

```text
如果 supported_routes 存在，使用 supported_routes。
如果不存在，则由 supported_intents + supported_sub_intents 转换。
```

验收：

- 新旧 AgentCard 都能加载。
- 新字段优先。
- `supported_routes` 中引用不存在的 intent/sub_intent 时，校验失败。

### 4. AgentCardLoader 校验 taxonomy

修改：

```text
app/agents/card_loader.py
```

新增或扩展校验：

```text
validate_with_intent_taxonomy(taxonomy)
```

校验内容：

- 每个 route intent 必须存在于 taxonomy。
- 每个 route sub_intent 必须属于对应 intent。
- AgentCard 的 examples.intent / examples.sub_intent 必须存在于 taxonomy。
- `capabilities` 不参与合法性校验，只做普通描述。

验收：

- 合法 AgentCard 通过。
- 将 `internal_log_analysis` 放进 supported_routes 时测试失败。
- 将 `endo_completion_aftercare` 配到 `pos_query` 下时测试失败。

### 5. IntentRecognitionNode 改为使用 taxonomy

修改：

```text
app/query/intent_recognition_node.py
```

当前候选空间来自 AgentCard summaries。目标改为：

```text
allowed_intents = taxonomy.list_allowed_intents()
candidate_sub_intents = taxonomy.list_candidate_sub_intents()
taxonomy_summaries = taxonomy.summaries_for_prompt()
agent_card_summaries = 只作为覆盖范围和能力证据
```

LLM 返回后校验：

```text
intent 必须在 taxonomy 中
sub_intent 必须属于 intent
```

验收：

- LLM 返回非法 intent 时丢弃并 fallback。
- LLM 返回合法 intent 但 sub_intent 归属错误时，sub_intent 置空或触发 fallback。
- LLM 返回 capability 作为 sub_intent 时不接受。
- fallback 规则输出也必须通过 taxonomy 校验。

### 6. Prompt 明确 taxonomy 是唯一合法来源

修改：

```text
app/prompts/intent_recognition/system.md
app/prompts/intent_recognition/user.md
```

Prompt 约束：

```text
IntentTaxonomy is the only source of legal intent and sub_intent values.
AgentCard summaries describe which agents can handle routes.
Capabilities are evidence only.
Do not invent intent/sub_intent.
Do not use agent_name, skill_id, or capability as intent/sub_intent unless present in taxonomy.
```

验收：

- prompt contract 测试覆盖上述关键语句。

### 7. Graph 注入 taxonomy summaries

修改：

```text
app/runtime/graph.py
```

目标：

```text
intent_recognition 节点调用时传入 taxonomy summaries
AgentCard summaries 继续传，但不再作为合法候选来源
```

验收：

- runtime flow 中 prompt 包含 taxonomy。
- AgentCard summary 中包含 supported_routes。

### 8. SkillMetadata 绑定 taxonomy

修改：

```text
app/schemas/skill.py
app/skills/catalog.py
```

新增字段：

```python
intent: str | None = None
sub_intents: list[str] = Field(default_factory=list)
```

兼容：

```text
旧 skill 的 intent_tags 保留。
新字段优先用于 scorer。
```

验收：

- SkillCatalog 能读取新字段。
- Skill 引用不存在的 intent/sub_intent 时校验失败。
- `intent_tags` 不再承担合法分类定义职责。

### 9. Skill scorer / reranker 改为使用 intent/sub_intents

修改：

```text
app/skills/scorer.py
app/skills/reranker.py
```

目标：

```text
context.intent == skill.intent -> 加分
context.sub_intent in skill.sub_intents -> 强加分
intent_tags / routing_keywords / capabilities -> 辅助打分
```

验收：

- `endo_completion_aftercare` 能稳定选中 `troubleshooting_agent.endo_completion_aftercare`。
- capability 命中只能加辅助分，不能覆盖明确 sub_intent 匹配。

### 10. 迁移 AgentCard 和 Skill

迁移：

```text
app/agents/cards/troubleshooting_agent.yaml
app/agents/cards/pos_query_agent.yaml
app/skills/troubleshooting_agent/*/SKILL.md
app/skills/pos_query_agent/*/SKILL.md
```

目标示例：

```yaml
agent_name: troubleshooting_agent
supported_routes:
  troubleshooting:
    - refund_failure
    - endo_completion_aftercare
```

Skill 示例：

```yaml
skill_id: troubleshooting_agent.endo_completion_aftercare
intent: troubleshooting
sub_intents:
  - endo_completion_aftercare
```

验收：

- AgentCard 中不再需要扁平 `supported_sub_intents`。
- Skill 中 `intent_tags` 可保留为兼容字段，但主链路不依赖它定义合法意图。

---

## 测试计划

### 单元测试

- `test_intent_taxonomy_loader_loads_valid_taxonomy`
- `test_intent_taxonomy_rejects_empty_intents`
- `test_intent_taxonomy_validates_sub_intent_parent`
- `test_agent_card_routes_validate_against_taxonomy`
- `test_skill_metadata_validates_against_taxonomy`
- `test_capability_is_not_accepted_as_sub_intent`

### 链路测试

- `退保失败，帮我排查`
  - intent = `troubleshooting`
  - sub_intent = `refund_failure`
  - selected_agent = `troubleshooting_agent`

- `保全任务完成，保单9200100000458846更新失败？`
  - intent = `troubleshooting`
  - sub_intent = `endo_completion_aftercare`
  - selected_agent = `troubleshooting_agent`

- `查询保单 9200130111869934 可以做哪些保全项`
  - intent = `pos_query`
  - sub_intent = `pos_available_items`
  - selected_agent = `pos_query_agent`

- LLM 返回：

```json
{"intent": "troubleshooting", "sub_intent": "internal_log_analysis"}
```

期望：

```text
sub_intent 不被接受，因为 internal_log_analysis 是 capability，不是 taxonomy sub_intent。
```

---

## 验收标准

1. 项目存在全局 `intent_taxonomy.yaml`。
2. `intent` / `sub_intent` 合法值只来自 `IntentTaxonomy`。
3. AgentCard 使用 `supported_routes` 声明覆盖范围。
4. Skill 使用 `intent/sub_intents` 绑定具体场景。
5. `capabilities` 不再参与候选合法值生成，只作为证据。
6. LLM prompt 明确 taxonomy 是唯一合法来源。
7. 非法 intent/sub_intent 有测试覆盖。
8. 现有主链路测试全部通过。
9. 新增 taxonomy、AgentCard route、Skill metadata 校验测试全部通过。
10. 文档说明清楚：

```text
IntentTaxonomy 定义系统认识什么
AgentCard 定义谁能处理什么
Skill 定义怎么处理具体场景
Capabilities 定义有什么能力
```

---

## 非目标

本任务不做以下事情：

- 不新增新的业务 Agent。
- 不恢复已删除的 policy / claim / compliance / document / change impact agents。
- 不重写 ToolExecutor。
- 不改变人工审批链路。
- 不改变实体抽取规则。
- 不接入真实外部 LLM 或知识库。

---

## 建议实施顺序

推荐拆成三次提交：

1. `IntentTaxonomy` schema / loader / yaml / 单测。
2. AgentCard `supported_routes` 迁移和路由校验。
3. IntentRecognition + SkillMetadata + Scorer 接入 taxonomy。

每次提交都必须保持：

```bash
uv run pytest
```

通过。
