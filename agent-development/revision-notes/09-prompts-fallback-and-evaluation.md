# LLM Prompt、输出 Schema、Fallback 与 Eval

适用场景：修改 Query Rewrite、Intent、Agent 选择、Skill rerank、子 Agent reasoning、记忆摘要或合规 Prompt；新增 scene；修改 LLM JSON 字段；调整 LLM 不可用时行为。

## 当前 Prompt 机制

每个 scene 都由 `app/prompts/manifest.yaml` 声明：

```text
scene -> version -> system/user markdown -> output_schema -> eval_suite -> tools_allowed
```

加载和校验位于 `app/prompts/manifest.py` 与 `app/prompts/loader.py`。模型调用节点通过 `PromptLoader.render_scene_system/user()` 渲染，不应在业务代码里散落长 Prompt 字符串。

当前 scene 与调用方：

| scene | Prompt 文件 | 主要调用方 | 输出 |
| --- | --- | --- | --- |
| `query_rewrite` | `app/prompts/query_rewrite/*` | `QueryRewriteNode` | `QueryRewriteLLMOutput` |
| `intent_recognition` | `app/prompts/intent_recognition/*` | `IntentRecognitionNode` | `IntentRecognitionLLMOutput` |
| `agent_selection` | `app/prompts/agent_selection/*` | `LLMRouter` | `AgentSelectionLLMOutput` |
| `skill_selection` | `app/prompts/skill_selection/*` | `SkillLLMReranker` | `SkillSelectionLLMOutput` |
| `subagent_reasoning` | `app/prompts/subagent_reasoning/*` | `BaseSubAgent` / ToolCallingRunner | Tool calls 或文本答案 |
| `memory_summary` | `app/prompts/memory_summary/*` | `ShortTermMemoryManager` | text |
| `final_compliance` | `app/prompts/verification/*` | `ComplianceVerifier` | `VerificationResult` |

## 1. 修改已有 Prompt 的步骤

1. 先确认行为边界属于 LLM 语义，还是确定性代码。权限、实体 canonical 合并、工具执行、审批、taxonomy 合法值不能只靠 Prompt。
2. 修改对应 `system.md` 或 `user.md`；`user.md` 只能引用调用方实际传入的变量。
3. 在 `app/prompts/manifest.yaml` 提升该 scene 的 `version`；若改 output schema 或 eval suite 名称，同步更新 manifest。
4. 如果 JSON 字段、类型、合法值变化，修改 `app/llm/output_schemas.py` 中对应 Pydantic model，以及所有调用节点的消费逻辑。
5. 更新 `app/evaluation/cases/<suite>_cases.yaml`：至少包含正例、边界例、反例和 fallback 相关样例。
6. 补节点单测和 fixture load 测试。

## 2. 新增 Prompt scene

需要同时新增：

- `app/prompts/<scene>/system.md`，如果有用户变量则新增 `user.md`；
- `app/prompts/manifest.yaml` scene 声明，包含 version、system/user、output_schema、eval_suite、tools_allowed；
- 若 JSON 输出，`app/llm/output_schemas.py` 的 schema 与 `SCHEMA_REGISTRY`；
- 调用组件，明确 `scene="<scene>"`、传入变量、解析失败时的处理；
- `app/evaluation/cases/<scene>_cases.yaml`；
- `tests/test_prompt_manifest.py`、`tests/test_prompt_templates.py` 的覆盖或新断言。

没有独立业务调用点的 scene 不应先创建。Prompt manifest 不是自由的内容目录，它是运行时可验证契约。

## 3. LLM 输出失败的处理

对 JSON scene，节点一般遵循：

```text
provider disabled/error
  or JSON parse failed
  or Pydantic schema invalid
  or illegal taxonomy/candidate selection
-> 记录 LLMAttempt / decision trace
-> 进入该节点的确定性 fallback 或明确失败
```

| 领域 | fallback 主位置 |
| --- | --- |
| Query Rewrite | `QueryRewriteNode._rewrite_with_rules()` + `context_reference_policy.yaml` |
| Intent | `IntentRecognitionNode._recognize_with_rules()` + `intent_fallback_policy.yaml` |
| Agent selection | `AgentSelectionNode._rule_selection()`；LLM router 仅 rerank Top-K |
| Skill selection | `SkillSelectionPolicy` / rule scorer；no-skill policy 决定澄清或本地泛化 |
| Tool loop | ToolCallingRunner 的 iteration/duplicate/failure guard，不是 Prompt fallback |

改 fallback 时必须保留 `llm_status`、`fallback_used`、`fallback_reason` 与 decision trace，避免静默从 LLM 路径滑到规则路径。

## 4. Eval 的当前边界

`app/evaluation/runner.py` 默认运行 fixture 的结构、Prompt 渲染、expected schema 断言，不会默认调用真实 LLM。`run_with_provider()` 才会使用注入的 provider。

因此：

- 修改 Prompt 后，fixture 通过不等于真实模型质量已经验证；
- 真实模型评估需要显式提供 provider、固定模型版本和记录结果；
- 不要为了 fixture 通过而把业务节点写成识别固定保单号、固定 request_id 或 test 环境分支。

## 验证

```bash
uv run pytest tests/test_prompt_manifest.py tests/test_prompt_templates.py tests/test_evaluation_cases_load.py -q
uv run pytest tests/test_llm_strict_schema.py tests/test_llm_model_config.py -q
uv run pytest tests/test_query_rewrite.py tests/test_intent_recognition_llm_json.py -q
uv run python -c 'from app.evaluation.runner import PromptEvalRunner; print(PromptEvalRunner().run())'
```

最后一条命令执行的是 deterministic fixture eval，不会调用真实 LLM。真实模型评估应显式调用 `PromptEvalRunner.run_with_provider()` 并传入已配置 provider。
