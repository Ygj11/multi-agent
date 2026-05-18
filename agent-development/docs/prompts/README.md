# Prompt 文档索引

本目录用于盘点当前项目中的提示词、skill instruction、prompt-like context 和规则逻辑。这里的文档只是维护索引和改造建议，不是运行时 prompt 来源。

## 当前目录用途

- 说明当前项目里哪些内容可以被视为 prompt / instruction。
- 区分真实运行时使用的 `SKILL.md`、结构化上下文、规则逻辑和未来预留 LLM messages。
- 给后续 prompt 配置化、版本化、评估和回滚提供参考。
- 帮助开发者避免把架构文档里的未来设计误认为当前已经运行。

## 当前 Prompt 分类

| 分类 | 当前状态 | 说明 |
| --- | --- | --- |
| `SKILL.md` | 部分真实运行时使用 | 多 skill 目录下带 `skill_id` frontmatter 的 `SKILL.md` 会被 `SkillCatalog` 扫描，选中后加载正文进入 `SubAgentContext.skill_content`。 |
| Query rewrite prompt | 当前未使用 prompt | `QueryRewriteNode` 当前是规则实现；`app/skills/query_rewrite/SKILL.md` 是文档/skill 指令，不是运行时 prompt。 |
| Intent recognition prompt | 当前未使用 prompt | `IntentRecognitionNode` 当前是关键词规则实现。 |
| ContextBuilder prompt | 当前未拼接 system prompt | `ContextBuilder` 当前构建 Pydantic 上下文对象，不构造 LLM messages。 |
| LLM provider messages | 接口预留 | `FakeLLMProvider` 和 `OpenAICompatibleLLMProvider` 接收 `messages`，但主链路当前没有实际调用 LLM provider。 |
| Tool / MCP prompt | 当前未使用 prompt | 工具调用是结构化 `ToolCall`，经 `ToolBroker / PolicyGate` 执行。 |

## 哪些是真实运行时使用

当前真实运行时使用的是：

- `app/skills/*_agent/*/SKILL.md` 的 frontmatter metadata：用于 `SkillSelector` 匹配。
- 被选中的 `SKILL.md` 完整正文：由 `SkillCatalog.load_skill_content()` 加载，进入 `SubAgentContext.skill_content`。
- `ContextBuilder` 生成的结构化上下文：用于 skill selection 和子 Agent 执行。

但要注意：当前子 Agent 仍主要通过 Python 规则生成结果，并没有把 `skill_content` 发送给 LLM。

## 哪些只是文档索引

本目录下全部文件都是文档索引，不参与运行时：

- `docs/prompts/README.md`
- `docs/prompts/PROMPT_INVENTORY.md`
- `docs/prompts/QUERY_REWRITE_PROMPTS.md`
- `docs/prompts/INTENT_RECOGNITION_PROMPTS.md`
- `docs/prompts/CONTEXT_BUILDER_PROMPTS.md`
- `docs/prompts/LLM_PROVIDER_PROMPTS.md`
- `docs/prompts/TOOL_AND_MCP_PROMPTS.md`
- `docs/prompts/PROMPT_REFACTOR_SUGGESTIONS.md`

## 当前不要从 docs/prompts 读取 Prompt

当前项目运行时不要读取 `docs/prompts`：

- 不要把这些 Markdown 文件接入 `ContextBuilder`。
- 不要让 `SkillCatalog` 扫描 `docs/prompts`。
- 不要把这里的推荐 prompt 模板当成当前已生效逻辑。
- 不要修改现有测试来依赖本目录。

## 后续配置化建议

如果后续要把 prompt 配置化，建议分阶段做：

1. 先保持 `SKILL.md` 是子 Agent skill instruction 的 source of truth。
2. 新增 `PromptRegistry`，只负责读取明确的 prompt 配置目录，例如 `app/prompts` 或数据库配置。
3. 为 query rewrite、intent recognition、final answer 分别定义 prompt id、version、input schema、output schema。
4. 增加 prompt evaluation 测试集，先离线评估，再灰度启用。
5. 支持 prompt rollback，确保 prompt 改动不会破坏现有规则回归测试。

