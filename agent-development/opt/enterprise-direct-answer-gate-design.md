# Enterprise Direct-Answer Gate Design

## 1. 设计背景

P4.1 已经把 no-skill 默认行为收敛为 `clarify`，解决了一个核心风险：

```text
没有匹配到 Skill 时，子 Agent 不再默认泛化执行工具调用。
```

但真实业务系统里，并不是所有问题都需要 Skill。很多问题只是概念解释、FAQ、通用规则说明或 SOP 咨询。如果所有未命中 Skill 的问题都澄清，用户体验会偏保守。

因此需要在进入子 Agent 之前增加一个明确的 `direct-answer gate`：

```text
能直接回答的轻量知识问题，直接回答。
需要查询、判断、处理具体业务对象的问题，继续进入 agent/skill。
无法判断的问题，澄清。
```

这个 gate 的目标不是绕过 Agent 架构，而是把“直接回答”和“业务执行”两条边界显式化。

## 2. 核心原则

### 2.1 Skill 不是所有回答的前置条件

以下问题可以不依赖 Skill：

- 概念解释：`保全任务完成是什么意思？`
- FAQ：`受理号是什么？`
- 固定规则说明：`保全项 001028 代表什么？`
- 通用 SOP 咨询：`保全任务完成后保单没更新，一般怎么排查？`

这类问题只需要知识，不需要真实系统状态。

### 2.2 Skill 是具体业务处理的前置条件

以下问题必须进入 agent/skill：

- 查询具体状态：`受理号 930021042875719 现在处理到哪一步？`
- 判断具体失败原因：`保单 9200100000458846 为什么没有更新？`
- 处理具体业务：`帮我重试回调。`
- 调用工具或真实接口：`REQ_001 为什么返回 E102？`

这类问题需要真实状态、工具结果、业务 SOP 和审批边界，不能让 LLM 仅凭常识回答。

### 2.3 FAQ 命中不等于直接返回

FAQ 或知识检索命中只是一个信号，不是最终决策。

例如：

```text
保全任务完成，保单 9200100000458846 为什么没更新？
```

即使命中 FAQ `保全任务完成是什么意思？`，也不能直接返回 FAQ。因为用户真正诉求是具体保单异常排查。

正确逻辑是：

```text
知识命中 + 问题类型允许直接回答 -> direct answer
知识命中 + 具体业务处理诉求 -> agent/skill
```

## 3. 架构位置

建议在 `intent_recognition` 之后、`discover_agents/select_agent` 之前增加节点：

```text
route_entry
 -> load_session
 -> save_user_message
 -> query_rewrite
 -> intent_recognition
 -> direct_answer_gate
      -> direct_answer_finalize
      -> agent/skill 主流程
      -> clarification_finalize
```

更完整的主干流程：

```text
用户请求
 -> query 改写
 -> 上下文引用判断
 -> 实体抽取
 -> 意图识别
 -> direct-answer gate
      -> FAQ/知识检索
      -> 类型判断
      -> route 决策
 -> direct_answer: 直接生成安全答案
 -> agent_skill: discover_agents -> select_agent -> assemble_task -> dispatch_agent
 -> clarify: 返回澄清问题
```

## 4. Gate 输出模型

`direct-answer gate` 不应该只返回 true/false，而应该返回结构化决策。

建议新增模型：

```python
class DirectAnswerDecision(BaseModel):
    route: Literal["direct_answer", "agent_skill", "clarify"]
    answer_type: Literal[
        "faq",
        "explanation",
        "sop_guidance",
        "business_execution",
        "clarification_reply",
        "follow_up",
        "unknown",
    ]
    confidence: float
    reason: str
    answer: str | None = None
    matched_faq_id: str | None = None
    knowledge_refs: list[dict[str, Any]] = []
    inherited_context_used: bool = False
    required_route_reason: str | None = None
    allowed_actions: list[str] = []
    forbidden_actions: list[str] = []
    decision_trace: dict[str, Any] = {}
```

字段含义：

- `route=direct_answer`：直接返回答案，不进入子 Agent。
- `route=agent_skill`：继续进入 agent/skill。
- `route=clarify`：当前类型或上下文不明确，需要用户补充。
- `answer_type`：当前问题类型。
- `allowed_actions`：本轮允许动作，例如 `answer_only`。
- `forbidden_actions`：本轮禁止动作，例如 `tool_call`、`claim_execution`。
- `knowledge_refs`：FAQ 或知识来源，用于审计。
- `decision_trace`：记录规则、FAQ 分数、LLM 分类结果和最终原因。

## 5. 类型判断依赖的信号

### 5.1 会话状态信号

会话状态优先级最高。

如果上一轮 assistant 返回：

```json
{
  "need_clarification": true,
  "missing_required_entities": ["endorseType"],
  "pending_task": "troubleshooting_agent.endo_completion_aftercare"
}
```

用户本轮输入：

```text
001028
```

这不是 FAQ，也不是解释 `001028`，而是澄清回复。

决策：

```json
{
  "route": "agent_skill",
  "answer_type": "clarification_reply",
  "inherited_context_used": true,
  "reason": "当前消息补充了上一轮缺失实体 endorseType"
}
```

### 5.2 强业务实体信号

强业务实体通常意味着问题可能涉及具体业务处理：

- `policy_no`
- `apply_seq`
- `request_id`
- `phone`
- `id_card`
- `endorseType`
- `product_code`
- `plan_code`

但有实体不一定必须进入 agent/skill，关键看问法。

直接回答示例：

```text
受理号是什么？
```

业务处理示例：

```text
受理号 930021042875719 为什么失败？
```

判断边界：

```text
实体被询问含义 -> direct_answer
实体被用于查询、判断、处理具体对象 -> agent_skill
```

### 5.3 动词和意图词信号

可直接回答的典型问法：

- `是什么`
- `什么意思`
- `有什么区别`
- `一般原因`
- `一般怎么处理`
- `有哪些步骤`
- `规则是什么`
- `需要哪些材料`

需要 agent/skill 的典型问法：

- `查一下`
- `帮我看`
- `为什么没更新`
- `为什么失败`
- `现在状态`
- `处理一下`
- `提交`
- `通知`
- `修改`
- `回调`
- `重试`
- `核对`

### 5.4 FAQ/知识命中信号

FAQ 命中应包含：

```json
{
  "faq_id": "faq_endo_done_meaning",
  "score": 0.93,
  "answer_type": "faq",
  "direct_answer_allowed": true
}
```

建议阈值：

- `score >= 0.85`：高置信 FAQ 命中。
- `0.65 <= score < 0.85`：可作为辅助信号，需要类型判断或 LLM 分类确认。
- `score < 0.65`：不直接使用。

### 5.5 IntentTaxonomy 策略信号

建议在 `intent_taxonomy.yaml` 中增加 direct answer 策略。

示例：

```yaml
intents:
  troubleshooting:
    description: 问题排查
    direct_answer_policy:
      faq:
        allowed: true
        requires_no_specific_business_object: true
      explanation:
        allowed: true
        requires_no_specific_business_object: true
      sop_guidance:
        allowed: true
        must_include_boundary_notice: true
      business_execution:
        allowed: false
        requires_skill: true
    sub_intents:
      endo_completion_aftercare:
        requires_skill_for_execution: true
        execution_entities:
          - policy_no
          - apply_seq
          - endorseType
        direct_answer_allowed:
          - faq
          - explanation
          - sop_guidance
```

含义：

- 可以回答概念和通用 SOP。
- 不能直接判断具体保单、受理号、request_id 的真实状态。
- 如果是具体执行类问题，必须进入 skill。

### 5.6 是否需要真实工具状态

这是最终硬边界。

只要回答需要真实系统状态，就不能 direct answer：

- `这个保单现在为什么没更新？`
- `这个受理号处理到哪一步了？`
- `REQ_001 为什么返回 E102？`
- `这个保单能不能退保？`

可以 direct answer 的是：

- `保全任务完成是什么意思？`
- `保全任务完成后一般为什么还没更新？`
- `遇到回调失败一般怎么排查？`

但 SOP 指导必须带边界：

```text
这是通用排查思路。若要判断某个具体保单或受理号，需要进入业务排查流程并查询真实系统状态。
```

## 6. 推荐决策顺序

必须按优先级执行，不建议把所有信号简单打分后平均。

```text
1. 是否是上一轮澄清回复
   是 -> agent_skill

2. 是否是追问上一轮具体业务处理
   是 -> agent_skill

3. 是否包含强业务实体 + 查询/失败/状态/处理类动作
   是 -> agent_skill

4. 是否高置信命中 FAQ，且没有具体业务处理诉求
   是 -> direct_answer

5. 是否是通用概念解释
   是 -> direct_answer

6. 是否是通用 SOP 咨询
   是 -> direct_answer，但只能给指导，不能声称已查询或已处理

7. 是否低置信或混合意图
   是 -> clarify
```

伪代码：

```python
async def decide_direct_answer(state: AgentGraphState) -> DirectAnswerDecision:
    if is_clarification_reply(state):
        return agent_skill("clarification_reply", "当前消息补充上一轮缺失信息")

    if is_follow_up_of_business_execution(state):
        return agent_skill("follow_up", "当前消息追问上一轮具体业务处理")

    if has_strong_business_object(state) and has_execution_action(state):
        return agent_skill("business_execution", "具体业务对象需要真实状态或工具结果")

    faq_match = await faq_matcher.match(state.rewritten_query)
    if faq_match.high_confidence and not has_specific_business_processing_intent(state):
        return direct_answer("faq", faq_match.answer, faq_match)

    if is_concept_explanation_question(state):
        return direct_answer("explanation", build_explanation_answer(state))

    if is_general_sop_question(state):
        return direct_answer("sop_guidance", build_sop_guidance_answer(state))

    return clarify("当前问题是想了解概念，还是要排查某个具体业务单据？")
```

## 7. FAQ 模块设计

FAQ 不建议先做成独立 Agent，也不建议先做复杂模型。

推荐初始实现：

```text
YAML FAQ + 规则匹配 + 可选 LLM 分类辅助
```

示例文件：

```yaml
faqs:
  - id: faq_endo_done_meaning
    intent: troubleshooting
    answer_type: faq
    direct_answer_allowed: true
    question_patterns:
      - 保全任务完成是什么意思
      - 什么叫保全任务完成
      - 保全任务完成代表什么
    keywords:
      - 保全任务完成
      - 什么意思
    forbidden_when_entities_present:
      - policy_no
      - apply_seq
    answer: >
      保全任务完成表示保全流程在任务侧已经完成，但不等于所有下游系统都已同步完成。
      如果是具体保单未更新，需要结合保单号、受理号和保全项进入排查流程。
```

匹配规则：

- pattern 精确或近似命中。
- keyword 覆盖核心概念。
- 如果出现强业务实体和处理动词，即使 FAQ 命中也降级为 `agent_skill`。
- FAQ answer 可以由 LLM 润色，但不能改变事实边界。

后续升级路径：

```text
YAML FAQ
 -> BM25/关键词检索
 -> embedding 语义检索
 -> LLM rerank
 -> FAQ 版本治理和评测集
```

## 8. LLM 在 Gate 中的角色

LLM 可以参与类型分类，但不能单独决定最终路线。

建议 LLM 只输出候选分类：

```json
{
  "answer_type": "sop_guidance",
  "confidence": 0.82,
  "reason": "用户询问一般排查步骤，没有具体保单或受理号"
}
```

然后由硬规则校验：

- 如果有 pending clarification，强制 `agent_skill`。
- 如果有强业务实体和处理动词，强制 `agent_skill`。
- 如果 taxonomy 禁止 direct answer，强制 `agent_skill` 或 `clarify`。
- 如果 FAQ 分数低，不能直接返回 FAQ。

也就是说：

```text
LLM 负责语义理解。
规则和 taxonomy 负责安全边界。
```

## 9. 与现有 P4.1 No-Skill Policy 的关系

P4.1 的 `NO_SKILL_POLICY` 仍然保留。

它负责的是：

```text
已经进入子 Agent 后，如果 Skill 没有命中，应该怎么办？
```

direct-answer gate 负责的是：

```text
进入子 Agent 之前，这个问题是否根本不需要 agent/skill？
```

二者边界：

```text
direct-answer gate 命中 -> 不进入子 Agent
direct-answer gate 未命中 -> 进入 agent/skill 主流程
进入子 Agent 后 Skill 未命中 -> 按 NO_SKILL_POLICY 处理
```

因此即使新增 direct-answer gate，也不能删除 `NO_SKILL_POLICY`。

## 10. 状态和观测

建议在 `AgentGraphState` 中增加临时 trace 字段：

```python
direct_answer_route: str | None
direct_answer_type: str | None
direct_answer_confidence: float | None
direct_answer_reason: str | None
direct_answer_decision_trace: dict[str, Any]
```

建议日志事件：

- `direct_answer_gate_started`
- `faq_candidates_loaded`
- `direct_answer_decided`
- `direct_answer_returned`
- `direct_answer_bypassed`
- `direct_answer_clarification_required`

日志中必须包含：

- route
- answer_type
- confidence
- reason
- matched_faq_id
- blocked_by_business_entity
- blocked_by_pending_clarification
- taxonomy_policy

## 11. 示例场景

### 11.1 FAQ 直接回答

用户：

```text
保全任务完成是什么意思？
```

决策：

```json
{
  "route": "direct_answer",
  "answer_type": "faq",
  "confidence": 0.93,
  "reason": "高置信命中 FAQ，且没有具体业务处理实体",
  "allowed_actions": ["answer_only"],
  "forbidden_actions": ["tool_call", "claim_execution"]
}
```

### 11.2 通用 SOP 指导

用户：

```text
保全任务完成后保单没更新，一般怎么排查？
```

决策：

```json
{
  "route": "direct_answer",
  "answer_type": "sop_guidance",
  "confidence": 0.82,
  "reason": "用户询问通用排查步骤，没有要求判断具体保单",
  "allowed_actions": ["answer_only"],
  "forbidden_actions": ["tool_call", "claim_execution"]
}
```

回答边界：

```text
这是通用排查思路，不代表已经查询某个具体保单。
```

### 11.3 具体业务处理

用户：

```text
保全任务完成，保单 9200100000458846，受理号 930021042875719，为什么没更新？
```

决策：

```json
{
  "route": "agent_skill",
  "answer_type": "business_execution",
  "confidence": 0.94,
  "reason": "包含具体 policy_no 和 apply_seq，且询问具体失败原因，需要真实系统状态"
}
```

### 11.4 澄清回复

上一轮：

```text
请补充保全项。
```

用户：

```text
001028
```

决策：

```json
{
  "route": "agent_skill",
  "answer_type": "clarification_reply",
  "confidence": 0.96,
  "reason": "当前消息补充上一轮缺失实体 endorseType",
  "inherited_context_used": true
}
```

## 12. 实施建议

### 阶段 1：最小可控版本

- 新增 `app/direct_answer/` 模块。
- 新增 `DirectAnswerDecision` schema。
- 新增 YAML FAQ loader。
- 在 graph 中增加 `direct_answer_gate` 节点。
- 实现规则优先判断：
  - pending clarification
  - strong entity + execution action
  - FAQ high confidence
  - explanation question
  - SOP guidance question
- 不接 embedding。
- 不让 direct-answer 调用业务工具。

### 阶段 2：LLM 分类辅助

- 新增 `direct_answer_classifier` prompt。
- LLM 输出 answer_type 和 reason。
- 规则/taxonomy 对 LLM 结果做 hard guard。
- 增加 fallback observability，避免 silent fallback。

### 阶段 3：知识检索升级

- FAQ 从 YAML 升级到 BM25 或 embedding。
- 引入 `knowledge_refs`。
- 增加 FAQ 命中率、误拦截率、误直答率评测。

### 阶段 4：治理和评测

- 为 direct-answer gate 建立 eval set。
- 覆盖 FAQ、SOP、具体业务、澄清回复、追问、多实体混合场景。
- 上线前要求：
  - 具体业务误直答率为 0。
  - 澄清回复误判 FAQ 为 0。
  - FAQ 高置信命中可解释。

## 13. 测试用例建议

必须覆盖：

- `保全任务完成是什么意思？` -> direct_answer/faq
- `受理号是什么？` -> direct_answer/faq
- `保全任务完成后保单没更新，一般怎么排查？` -> direct_answer/sop_guidance
- `保全任务完成，保单 9200100000458846 为什么没更新？` -> agent_skill/business_execution
- `受理号 930021042875719 为什么失败？` -> agent_skill/business_execution
- 上一轮缺 `endorseType`，本轮 `001028` -> agent_skill/clarification_reply
- 上一轮具体排查回答后，本轮 `那一般是谁的问题？` -> agent_skill/follow_up 或 clarify，不能 FAQ 直答
- FAQ 命中但含强业务实体 -> agent_skill
- FAQ 低置信命中 -> 不 direct answer
- LLM classifier 输出 direct_answer，但规则判断需要真实状态 -> agent_skill

## 14. 最终边界总结

一句话规则：

```text
只需要知识的，direct answer。
需要真实状态、工具执行、业务判断的，agent/skill。
上下文处于澄清或追问中的，先尊重会话状态。
不确定的，澄清。
```

这套设计可以在不破坏 P4.1 安全基线的前提下，让系统恢复轻量问答能力，同时避免“没有 Skill 也泛化执行”的企业级风险。
