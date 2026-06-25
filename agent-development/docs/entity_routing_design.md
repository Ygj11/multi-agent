# 实体路由与状态设计

本文按当前运行时代码说明实体从用户请求进入 Query Rewrite、Intent Recognition、Agent/Skill 选择，再到工具调用的真实生命周期。

本文回答：

1. 实体从哪里来，先用正则还是先用 LLM？
2. entity_bag、entities、ConversationWindow 分别是什么？
3. 同类实体出现多个值时，何时保留列表，何时要求澄清？
4. Intent、Agent 和 Skill 如何使用实体，又分别不应修改什么？

## 1. 核心结论

实体处理不是一个独立 Agent，也不是 Intent 节点的附带动作。当前主链如下：

~~~text
确定性规则抽取 + 历史候选
        ↓
Query Rewrite 解决上下文、继承和实体解析
        ↓
canonical entity_bag
        ↓
entities = entity_bag 的兼容投影
        ↓
Intent / Agent Selection / Skill Selection / Task 只读使用实体
~~~

核心约束：

~~~text
entity_bag 是内部唯一事实来源。
entities 是 entity_bag.to_compact_dict() 生成的兼容视图。
Intent Recognition 不新增、继承、覆盖或修复实体。
~~~

因此，实体状态只在 Query Rewrite 阶段收敛；后续节点可以读取，不应维护第二套实体状态。

## 2. 整体调用链

~~~mermaid
flowchart TD
    A["/api/chat: original_query"] --> B["load_session: 最近消息与短摘要"]
    B --> C["save_user_message"]
    C --> D["query_rewrite"]
    D --> E["EntityExtractor: 当前与历史规则实体"]
    E --> F["EntityResolver: 规范化、覆盖、集合或冲突"]
    F --> G{"LLM 改写可用且输出合法?"}
    G -->|"是"| H["LLM: 改写、追问判断、语义实体候选"]
    G -->|"否"| I["规则兜底: 引用判断、继承、澄清"]
    H --> J["EntityResolver: 最终 EntityBag"]
    I --> J
    J --> K["Graph: 同步 entity_bag 与 entities"]
    K --> L["intent_recognition: 只读实体"]
    L --> M["build_orchestrator_context"]
    M --> N["select_agent: 使用 compact entities"]
    N --> O["assemble_task"]
    O --> P["SkillContextResolver"]
    P --> Q["RequiredEntityChecker"]
    Q --> R["ToolCallingRunner: LLM 按 Tool Schema 调用工具"]
~~~

save_user_message 虽发生在 Query Rewrite 前，但当前轮输入一直取自 state.original_query。历史上下文来自之前已经持久化的消息；当前用户消息不会被重复当作历史消息读取。

## 3. 实体状态模型

### 3.1 EntityMention

app/schemas/entities.py 中的 EntityMention 表示一条实体提及：

| 字段 | 含义 |
| --- | --- |
| type | 内部实体类型，如 policy_no、apply_seq |
| value | 原始抽取值 |
| normalized_value | 规范化后的值，如 req_001 变为 REQ_001 |
| source | current_query、recent_turn、summary、llm 等来源 |
| confidence | 来源置信度 |
| turn_id | 历史消息轮次 |
| sensitive | 是否敏感 |
| metadata | 文本位置、否定、更正、继承、集合语义等 |

当前轮规则抽取会记录 span_start、span_end。实体前出现“不是、并非、非”会标记 negated=true；出现“改成、更正为、换成、应为”等会标记 correction=true。

### 3.2 EntityBag

EntityBag 是动态实体容器，不是固定字段 schema：

~~~python
EntityBag(
    entities={
        "policy_no": [EntityMention(...)],
        "apply_seq": [EntityMention(...)],
    }
)
~~~

它可容纳 YAML 中定义的实体，也可容纳 LLM 补充的动态类型，例如 hospital_name、document_type。

EntityBag.to_compact_dict() 生成下游常用的兼容视图：

~~~python
# 单值
{"policy_no": "9200100000458846"}

# 当前轮明确的多值集合
{"policy_no": ["9200100000458846", "9200100000458847"]}
~~~

### 3.3 entity_bag、entities 与 ConversationWindow

| 字段 | 定位 | 谁写入 | 主要消费者 |
| --- | --- | --- | --- |
| entity_bag | canonical 实体状态，保留来源、置信度和元数据 | Query Rewrite / EntityResolver | Query Rewrite、Intent、Skill Context |
| entities | entity_bag 的 compact 兼容视图 | build_entity_state_updates 同步生成 | ContextBuilder、Agent/Skill 选择、Task |
| ConversationWindow.entity_bag | 本轮改写时的会话候选快照 | Query Rewrite 构造 | Query Rewrite LLM、Intent 辅助上下文 |

Graph 不会分别手写两份实体。app/runtime/graph.py 在 Query Rewrite 后调用：

~~~python
entity_updates = build_entity_state_updates(EntityBag(**result.entity_bag))
# {
#   "entity_bag": canonical_bag.model_dump(),
#   "entities": canonical_bag.to_compact_dict(),
# }
~~~

## 4. 实体从哪里来：规则先行，LLM 补充

### 4.1 YAML 规则抽取

app/query/entity_patterns.yaml 是确定性抽取和值格式约束的单一配置来源。一个保单号规则的结构如下：

~~~yaml
- entity_type: policy_no
  regex:
    - "(?:保单号|保单|policy[_-]?no|policyNo)[:：=]?\\s*(920\\d{13})(?!\\d)"
  value_regex:
    - "^920\\d{13}$"
  sensitive: false
  confidence: 0.95
~~~

两个正则的输入和责任不同：

| 字段 | 输入 | 责任 |
| --- | --- | --- |
| regex | 完整自然语言 | 找到实体所在位置，并从捕获组取得值 |
| value_regex | 已独立出来的单个值 | 校验 LLM、历史 metadata、兼容字典等候选能否进入 canonical bag |

例如文本为“保单号 9200100000458846 没有更新”：

1. regex 匹配原始文本并提取 9200100000458846。
2. value_regex 校验这个裸值是否满足 920 开头 16 位数字。
3. EntityMention 带 source=current_query、confidence=0.95 进入 bag。

规则抽取发生在三个位置：

~~~text
original_query  -> source=current_query
short_summary   -> source=summary
recent_messages -> source=recent_turn，并附带 turn_id
~~~

当前轮实体是用户明确输入；历史实体只是候选，不能自动覆盖当前轮。

### 4.2 LLM 的位置

Query Rewrite 的顺序不是“先让 LLM 抽实体，再正则兜底”，而是：

~~~text
先规则抽取当前轮和历史候选
→ 构造 ConversationWindow
→ LLM 做改写、指代消解、追问判断和语义候选补充
→ EntityResolver 决定最终实体状态
~~~

LLM 输出的 entities 被构造成 source=llm、confidence=0.85 的候选。它不能通过字典展开直接覆盖规则实体。

例如 LLM 可补充 YAML 外实体：

~~~json
{"entities": {"document_type": "保全批文"}}
~~~

若值非空、置信度不低于 0.75，Resolver 可以保留该动态实体。没有配置 value_regex 的动态类型目前只要求值非空。

但影响 Tool 必填参数、权限、审批或关键写操作的实体，应配置 YAML 或接入可信结构化来源，不能只依赖 LLM 的临场语义判断。

## 5. EntityResolver：覆盖、集合与冲突

app/query/entity_resolver.py 中的 EntityResolver 不从文本找实体，只处理已经得到的候选。

### 5.1 处理步骤

~~~python
def resolve(base_bag, candidate_bag, stage, parallel_current_entity_types=None):
    # 1. 别名归一化：policyNo -> policy_no，applySeq -> apply_seq
    # 2. 规范化值：REQ、错误码、产品/险种编码、身份证等转大写
    # 3. 丢弃否定值、低置信 LLM 值、value_regex 不合法的值
    # 4. 按实体类型分组；同类型同值去重
    # 5. 按来源优先级选择，或保留当前轮明确的多值集合
    # 6. 无法安全选择时返回 conflicts 与 clarification_question
~~~

### 5.2 来源优先级

| 来源 | 优先级 | 说明 |
| --- | ---: | --- |
| current_query | 100 | 当前轮规则抽取的用户明确输入 |
| rule | 90 | 兼容规则路径构造的候选 |
| llm | 70 | LLM 语义候选 |
| recent_turn | 60 | 从历史消息规则抽取 |
| recent_turn + inherited=true | 55 | 被允许继承的历史候选 |
| summary | 40 | 短期摘要候选 |
| tool_result | 30 | 工具结果候选 |

所以当前轮保单号不会被 LLM 或历史保单号覆盖。

### 5.3 同类多值的三种语义

| 情况 | Resolver 行为 | 是否澄清 |
| --- | --- | --- |
| 同类型同值多处出现 | 去重，保留优先级/置信度更高的一条 | 否 |
| 当前用户明确输入多个同类值 | 保留为有序集合，metadata 标记 collection_semantics=explicit_current_values | 否 |
| 历史或其他候选同优先级出现多个不同值 | 生成 EntityConflict | 是 |

“不是 A，是 B”属于更正，不属于多值集合：否定的 A 被丢弃，correction=true 的 B 被保留。

## 6. Query Rewrite 的真实路径

QueryRewriteNode.rewrite 可概括为：

~~~python
current_raw = extractor.extract(original_query, source="current_query")
parallel_types = 当前轮中同类型值数量大于 1 的类型
current_bag = resolver.resolve(empty, current_raw, parallel_types)

summary_bag = extractor.extract_from_summary(short_summary)
recent_bag = extractor.extract_from_recent_turns(recent_messages)
history_bag = resolver.resolve(summary_bag, recent_bag)

window = ConversationWindow(summary, recent_messages, history_bag + current_bag)

result = await rewrite_with_llm(original_query, current_bag, window)
if result is None:
    result = rewrite_with_rules(original_query, current_bag, history_bag, window)
~~~

### 6.1 LLM 主路径

LLM 主路径只在以下条件均满足时启用：

~~~text
llm_provider 不为空；
InternalLLMProvider 已配置 base_url；
Provider 调用成功；
输出可解析为 QueryRewriteLLMOutput。
~~~

输入包括：

~~~text
original_query
current_entities（当前轮规则抽取后的 compact 值）
conversation_window（短摘要、最近消息、当前/历史候选实体）
~~~

LLM 严格 JSON 输出包含 rewritten_query、is_follow_up、rewrite_type、entities、inherited_entities、澄清信息等。

系统随后执行：

~~~python
inherited_bag = EntityBag.from_compact_dict(
    llm_output.inherited_entities,
    source="recent_turn",
)
llm_bag = EntityBag.from_compact_dict(
    llm_output.entities,
    source="llm",
    confidence=0.85,
)
final = resolver.resolve(
    base_bag=current_bag,
    candidate_bag=inherited_bag + llm_bag,
    parallel_current_entity_types=parallel_types,
)
~~~

重点：当前轮规则实体是 base_bag；LLM 只能提供 candidate_bag；最终状态只能由 Resolver 输出。

当前边界：LLM 说某个 inherited_entities 来自历史时，当前代码没有额外验证该值必然存在于 ConversationWindow.entity_bag。它仍会受到当前轮优先级、value_regex 和冲突策略约束。

### 6.2 规则 fallback 路径

以下情况进入规则路径：

~~~text
未配置 LLM；
Provider 异常或 response.error；
finish_reason=error；
输出不是 JSON；
JSON 不符合 QueryRewriteLLMOutput。
~~~

规则 fallback 不尝试泛化理解新的业务概念。它负责可预测的引用判断、历史继承、澄清和有限模板改写。

判断顺序：

1. 最近一条 assistant 消息 metadata.need_clarification=true：本轮为 clarification_reply。
2. 出现“第一个、第二个”等序号：本轮为追问，并尝试选中对应历史候选。
3. 出现“这个、刚才、上一轮、继续”等明确引用：本轮为追问。
4. 出现“为什么、怎么办、查一下”等弱追问信号，且没有强锚点：本轮为追问。
5. 没有实体且问题长度不超过 16：本轮为追问。
6. 当前轮出现保单号、受理号、请求号、理赔号等强锚点：本轮为 new_request。
7. 其余为 direct。

追问时，只有历史中存在唯一高置信值才允许继承。历史有多个候选、用户又没有明确序号时，必须澄清。

need_clarification=true 时，最终 rewrite_type 统一为 clarification_required，优先于 contextual_follow_up 或 clarification_reply。

## 7. Query Rewrite 后：Intent、Agent 与 Skill

### 7.1 Intent Recognition 只读实体

Intent 节点接收：

~~~text
original_query：辅助原始措辞
rewritten_query：主语义依据
entities / entity_bag：已经解析好的只读证据
conversation_window：辅助背景
intent taxonomy：合法 intent/sub_intent 值域
AgentCard 摘要：分类辅助证据
~~~

它不会重新调用 EntityExtractor.extract，也不会调用 EntityResolver.resolve 合并新候选。

Intent LLM 输出虽然包含 entities 字段，但它只是候选 echo。IntentResult 不包含 entities，Graph 也不会用它更新 entity_bag 或 entities。

Intent 只输出：

~~~text
intent
sub_intent
confidence
need_clarification
clarification_question
reason
~~~

Query Rewrite 或 Intent 已经澄清时，Graph 直接进入 build_clarification_answer，不会继续 Agent 和 Skill。

### 7.2 Agent Selection 和 Task

ContextBuilder.build_for_orchestrator 优先从 canonical entity_bag 重建 compact entities。

AgentCardLoader.match_candidates 用 compact entities 参与：

~~~text
required_entities 命中或缺失扣分
optional_entities 命中加分
结合 intent、sub_intent、capabilities、examples、keywords 形成候选
~~~

Agent Selection 不解析实体，不修正实体，也不绑定工具参数。

AgentTaskAssembler 只是把 rewritten_query、original_query、intent、selected agent、compact entities、会话与认证信息封装为 SubAgentTask。

### 7.3 Skill Selection 和必填实体

子 Agent 运行时，SkillContextResolver：

1. 从 parent_context.entity_bag 重建 canonical bag；只有兼容路径才从 compact entities 重建。
2. 构建 SkillSelectionContext，包含 entities、entity_bag、改写问题、intent、sub_intent、会话摘要。
3. 用 Skill metadata 的 intent、sub_intent、required_entities、optional_entities、关键词做规则评分；必要时做 LLM rerank。
4. 只加载最终选中的 SKILL.md 内容。
5. 对选中 Skill 执行 RequiredEntityChecker。

RequiredEntityChecker 的规则：

~~~text
compact entities 有非空值：满足，列表也是非空值。
compact entities 缺失，但 bag 中有唯一高置信值：补入该值。
compact entities 缺失，且 bag 中有多个值：澄清。
没有值：要求补充。
~~~

也就是说，Checker 本身并不根据 collection_semantics 区分“当前轮批量集合”和“历史歧义”；只要 compact entities 中已有非空列表，就会判为满足。

正常主链中，历史歧义会由 Query Rewrite 提前设置 need_clarification 并阻断 Graph，因此不会带着历史多值继续到 Skill。当前轮明确给出的多个保单号则以列表进入 entities，因此可满足 policy_no 必填条件。

### 7.4 Tool 调用边界

实体不会被系统自动绑定为工具参数。ToolCallingRunner 把任务、选中 Skill 内容、改写问题、实体、知识提示和可见 Tool Schema 交给子 Agent LLM。

LLM 根据 Tool Schema 发起调用，ToolExecutor 再做可见性、必填参数、权限、审批和执行检查。

若 MCP Schema 声明：

~~~json
{
  "policy_no": {
    "type": "array",
    "items": {"type": "string"}
  }
}
~~~

LLM 可以一次传入当前轮的保单号列表。当前没有 ToolParameterBinder：不会自动把 policy_no 改为 policyNo，也不会自动把列表拆成多次单值调用。

## 8. 详细案例

### 案例 A：单轮保全完成但保单未更新

用户：

~~~text
保全任务完成，受理号 930010412672222，保单 9200100000458846，保全项 001028 没有更新。
~~~

第一步，规则抽取：

~~~python
{
    "apply_seq": "930010412672222",
    "policy_no": "9200100000458846",
    "endorseType": "001028",
}
~~~

三者均为 source=current_query。不存在同类竞争值，Resolver 原样保留。

第二步，Query Rewrite：

- LLM 可用：LLM 将问题改写为包含完整业务目标和实体的自包含请求。
- LLM 不可用：规则 fallback 至少保留原问题和当前实体；对于 request_id + error_code 等已定义场景还能生成标准排查句。

第三步，Intent、Agent、Skill：

~~~python
intent = "troubleshooting"
sub_intent = "endo_completion_aftercare"
agent = "troubleshooting_agent"
skill = "troubleshooting_agent.endo_completion_aftercare"
~~~

该 Skill 要求 apply_seq、policy_no、endorseType，三者齐全，子 Agent 进入 ToolCallingRunner，可先查询 query_endo_task_record(apply_seq)。

### 案例 B：多轮澄清补受理号

第一轮：

~~~text
保全任务完成后保单 9200100000458846 没有更新，保全项是 001028。
~~~

抽取结果：

~~~python
{
    "policy_no": "9200100000458846",
    "endorseType": "001028",
}
~~~

Skill 检查发现缺少 apply_seq，于是澄清回答会被保存到 SQLite messages.metadata_json：

~~~python
{
    "need_clarification": true,
    "rewritten_query": "保全任务完成后保单未更新...",
    "entities": {
        "policy_no": "9200100000458846",
        "endorseType": "001028"
    },
    "missing_required_entities": ["apply_seq"]
}
~~~

第二轮用户只回复：

~~~text
930010412672222
~~~

步骤：

1. load_session 读取此前 assistant metadata。
2. 当前轮正则抽取 apply_seq=930010412672222。
3. Query Rewrite 优先发现上一轮 need_clarification=true，判定 clarification_reply。
4. 从上一任务 metadata 继承 policy_no、endorseType；当前轮 apply_seq 优先。
5. 所有必填实体齐全，形成自包含问题。

最终：

~~~python
{
    "apply_seq": "930010412672222",
    "endorseType": "001028",
    "policy_no": "9200100000458846",
}
need_clarification = False
rewrite_type = "clarification_reply"
~~~

### 案例 C：历史歧义，必须澄清

历史摘要：

~~~text
上一轮先查询保单 9200100000458846，后又查询保单 9200100000458847。
~~~

当前请求：

~~~text
继续查一下。
~~~

规则 fallback 步骤：

1. 当前轮无实体，“继续/查一下”是引用信号。
2. history_bag 的 policy_no 有两个值。
3. 用户未说“第一个”或“第二个”。
4. 系统不能默认任选其中一个。

结果：

~~~python
need_clarification = True
clarification_question = "上下文里有多个 policy_no，请明确你要继续处理哪一个。"
rewrite_type = "clarification_required"
~~~

这是“追问引用对象不明确”，不是“当前轮实体冲突”。

若用户改为：

~~~text
第二个保单的受理号 930010412672222 查一下。
~~~

系统按 ordinal_targets 选择第二个历史保单，再合并当前受理号：

~~~python
{
    "policy_no": "9200100000458847",
    "apply_seq": "930010412672222",
}
~~~

### 案例 D：当前轮明确给出多个保单，保留集合

用户：

~~~text
保单 9200100000458846 和 9200100000458847 的被保人是谁？
~~~

步骤：

1. 当前轮 regex 提取两个 policy_no，来源均为 current_query。
2. Query Rewrite 发现当前轮同类型值数量大于 1，将 policy_no 放入 parallel_current_entity_types。
3. Resolver 判断这是用户明确给出的对象集合，而不是待选择的竞争候选。
4. 按用户原文位置保留顺序，并标记 collection_semantics=explicit_current_values。

结果：

~~~python
entities = {
    "policy_no": [
        "9200100000458846",
        "9200100000458847",
    ]
}
need_clarification = False
rewrite_type = "new_request"
~~~

如果后续 MCP Tool Schema 的 policy_no 是 array<string>，LLM 可以一次传入整个列表。若工具只接受单值，当前系统不会自动拆分，必须由 Skill 指令或后续参数绑定能力处理。

## 9. LLM、规则与 fallback 的职责

| 环节 | LLM 做什么 | 规则/代码做什么 | LLM 不可用时 |
| --- | --- | --- | --- |
| 当前实体发现 | 补充语义候选 | YAML regex 确定性提取 | 仍能提取 YAML 实体 |
| 值合法性 | 不能决定 | value_regex、置信度、否定标记 | 一样执行 |
| 覆盖与冲突 | 提供候选 | EntityResolver 最终决定 | 一样执行 |
| 上下文改写 | 主路径判断追问、补参、新请求 | fallback 按引用策略判断 | 使用规则 fallback |
| Intent | 语义分类 | taxonomy 白名单、Schema 校验、规则 fallback | 使用 IntentFallbackPolicy |
| Agent 选择 | 候选接近时 rerank | AgentCard 召回、权限校验 | 规则 Top1 或澄清 |
| Skill 选择 | 必要时 rerank | metadata 评分、required entity 检查 | 规则评分或 no-skill 策略 |
| Tool 调用 | 提出调用及参数 | 可见性、必填参数、权限、审批、执行 | 不适用 |

## 10. 排查、测试与边界

实体相关 State 与 trace 字段：

~~~text
entity_bag
entities
query_rewrite_decision_trace
query_rewrite_llm_status
query_rewrite_fallback_reason
need_clarification
clarification_question
missing_required_entities
~~~

主要测试：

| 测试文件 | 覆盖内容 |
| --- | --- |
| tests/test_entity_patterns_loader.py | YAML、value_regex 编译和异常 |
| tests/test_entity_extractor.py | 规则抽取、敏感实体、更正标记 |
| tests/test_entity_resolver.py | 来源优先级、动态 LLM 实体、历史冲突、当前多值集合 |
| tests/test_query_rewrite_entity_inheritance.py | 追问、澄清补参、历史歧义、序号引用、批量保单 |
| tests/test_entity_state_sync.py | entities 与 entity_bag 同步 |
| tests/test_skill_required_entities.py | Skill 必填实体、歧义和列表实体 |
| tests/test_tool_schema_openai.py | MCP 数组参数 Schema 透传 |

当前已经实现：

~~~text
规则抽取、动态 LLM 候选、统一 Resolver、来源优先级、历史继承、
澄清恢复、当前轮多值集合、Intent 只读实体、Skill 必填校验。
~~~

当前尚未实现：

~~~text
ToolParameterBinder：实体自动映射为外部工具参数。
批量调用规划：列表自动拆分为多个单值工具调用。
LLM inherited_entities 与历史 EntityBag 的严格成员校验。
完整 JSON Schema 类型校验：当前工具层重点校验必填参数，
不会完整校验 array/string 等类型。
~~~
