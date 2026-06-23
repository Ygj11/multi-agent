# 新增或修改 Skill SOP

适用场景：增加业务 SOP、拆分一个 Skill、修改 Skill 必需实体、工具步骤、关键词、LLM rerank 行为或 no-skill 策略。

## 当前真实机制

`SkillCatalog` 启动时只扫描每个 `SKILL.md` 的 frontmatter metadata；选中后才读取完整 Markdown 正文。选择路径是：

```text
BaseSubAgent
  -> ContextBuilder.build_for_subagent()
  -> SkillContextResolver.build_selection_context()
  -> SkillCatalog.list_skills(agent)
  -> SkillSelector: rule score -> optional LLM rerank
  -> RequiredEntityChecker
  -> SkillCatalog.load_skill_content(selected_skill_id)
```

不要把所有 Skill 正文放进 Prompt，也不要把 Skill 当成可独立路由的 Agent。

## 1. 新增 Skill

### 文件位置和命名

创建：`app/skills/<agent_name>/<skill_name>/SKILL.md`。

`SkillCatalog.scan()` 只识别三层目录下的 `SKILL.md`，即 `<agent>/<skill>/SKILL.md`；`deprecated/` 下内容不参与扫描。

### 必填 frontmatter

实际解析/校验在 `app/skills/metadata.py` 和 `app/schemas/skill.py`。最小模板：

```markdown
---
skill_id: agent_name.skill_name
name: 面向用户和澄清的名称
description: 用于规则打分和 LLM rerank 的业务边界描述
agent: agent_name
intent: some_intent
sub_intents:
  - some_sub_intent
intent_tags:
  - some_intent
required_entities: []
optional_entities: []
private_tools: []
enabled: true
business_domain: []
required_context: []
routing_keywords: []
routing_negative_keywords: []
---

# SOP 正文
```

约束：

- `skill_id` 必须是 `<agent>.<skill>` 且以 `agent` 字段开头。
- `intent_tags`、`required_entities`、`optional_entities`、`private_tools` 是必填 list；`intent_tags` 不能为空。
- `intent` 和每个 `sub_intent` 必须存在于 taxonomy。
- `private_tools` 必须被所属 AgentCard 的 `private_tools` 声明。
- 不使用 `is_default`；没有匹配 Skill 的行为由 `NO_SKILL_POLICY` 控制。

### 同步 AgentCard

在 `app/agents/cards/<agent>.yaml`：

1. 把 `skill_id` 加进 `skills`。
2. 若 Skill 引入新工具，将工具加到 Card `private_tools`。
3. 确认 Skill 的 `intent/sub_intents` 属于 Card 的 `supported_routes`。

`AgentCardLoader.validate_with_skill_catalog()` 在 container build 时会检查这些约束；不要跳过。

## 2. 修改 Skill 的不同层

| 想改什么 | 修改文件 | 影响 |
| --- | --- | --- |
| 工具步骤、判断分支、回答结构 | `SKILL.md` 正文 | 仅选中该 Skill 后的 subagent prompt；补 Tool Loop/业务回归。 |
| 是否会被选中 | frontmatter 的 intent_tags、description、routing_keywords、negative keywords、business_domain、required_context | 影响规则 scorer 和 LLM rerank。 |
| 必需实体 | frontmatter `required_entities` | `RequiredEntityChecker` 基于 resolved EntityBag 澄清；先确认实体可被公共 extractor/resolver 产生。 |
| 可使用工具 | frontmatter `private_tools` + AgentCard | 还必须存在 ToolRegistry 注册和实际 handler。 |
| 规则分数权重 | `app/skills/scoring_policy.yaml` | 影响所有 Skill，需对全体 skill fixture 回归。 |
| 选择阈值/no-skill 判定 | `app/skills/selection_policy.py`、`app/skills/selector.py` | 全局行为变化，不能只测一个 Skill。 |
| LLM rerank 条件和输出 | `app/skills/reranker.py`、`app/prompts/skill_selection/*`、`app/llm/output_schemas.py` | 必须更新 prompt eval。 |

## 3. required_entities 的真实含义

`RequiredEntityChecker` 读取 `task.entities` 与 canonical `EntityBag`：如果实体在 compact view 缺失，但 bag 中只有一个高置信候选，会补入执行上下文；多候选时返回澄清；完全缺失也返回澄清。

因此：

- required entity 是“执行这个 SOP 的最小前置条件”，不是“所有可能有用参数”。
- 工具参数可能比 Skill required entities 更多；应由 Skill 正文在确定具体工具后再要求对应参数。
- 不要在 `SkillContextResolver` 再写私有 regex。已存在实体要通过 `EntityExtractor + EntityResolver` 获得。

## 4. no-skill 策略

配置来源：`.env` -> `app/config/settings.py` -> `ContextBuilder`。

| `NO_SKILL_POLICY` | 当前行为 |
| --- | --- |
| `clarify` | 默认。没有可信 Skill 时返回澄清，不进入 ToolCallingRunner。 |
| `answer_no_skill` | 支持的受控策略值；应只用于明确无 SOP 也可回答的场景，并补回归。 |
| `generic_dev_only` | 仅 `APP_ENV=local` 可用，用于本地调试；非 local 配置会被拒绝。 |

不要为了让某个请求“先跑起来”把业务 Agent 改为 `generic_dev_only`。

## 测试

```bash
uv run pytest tests/test_skill_catalog.py tests/test_skill_required_entities.py -q
uv run pytest tests/test_skill_selector.py tests/test_skill_selector_llm_rerank.py tests/test_skill_scoring_policy.py -q
uv run pytest tests/test_skill_context_builder.py tests/test_skill_selection_end_to_end.py tests/test_no_skill_policy.py -q
```

如修改 Skill Prompt 或 rerank，还要读并执行 [09-prompts-fallback-and-evaluation.md](09-prompts-fallback-and-evaluation.md)。
