# P1 平台瘦身任务

P1 目标：在 P0 主链路稳定后，继续拆清上下文、Skill、Verification、Evidence、配置和 integrations 的边界。P1 不抢在 P0 之前做大改，避免和核心链路 refactor 相互干扰。

## 完成状态

| 编号 | 任务 | 状态 | 本轮落地点 |
|---|---|---|---|
| 1 | 拆分 SkillSelector 为 Scorer / Reranker / Policy | 已完成 | 新增 `app/skills/scorer.py`、`app/skills/reranker.py`、`app/skills/selection_policy.py`，`SkillSelector` 保持 facade |
| 2 | 拆分 ContextBuilder 职责 | 已完成 | 新增 `app/runtime/context/knowledge_hint_builder.py`、`app/runtime/context/skill_context_resolver.py`，保留 `ContextBuilder.build_for_*` 外观 |
| 3 | 统一 Runtime Handler 层 | 已完成 | 新增 `MemoryCommitHandler`，`MessageCommitHandler` 只负责消息保存 |
| 4 | 规范 integrations 预留目录 | 已完成 | 新增 `app/integrations/README.md`，更新 `app/integrations/__init__.py` |
| 5 | 强化 Auth / Verification 边界 | 已完成 | 补充 `AuthorizationService`、`VerificationService` 职责说明，保持代码行为不变 |
| 6 | Evidence / Audit 职责收敛 | 已完成 | 明确 `ToolExecutionLogStore`、`ApprovalStore`、`EvidenceStore` 三者职责 |
| 7 | 配置分组整理 | 已完成 | 重建 `app/config/settings.py` 的分组和说明，补全 `.env.example` auth 配置 |
| 8 | 编码和中文文案清理 | 部分完成 | 清理本任务文档和本轮新增/重建文件说明；历史大范围 mojibake 不在本轮批量替换 |

## 验收标准

- Skill selection 阶段仍只读取 metadata，不读取所有 SKILL.md body。
- LLM rerank 只能从 Top-K metadata 候选中选择，非法 JSON / 非法 skill_id fallback 到规则 Top1。
- 只有 selected skill 后才加载完整 body。
- `ContextBuilder.build_for_orchestrator` 和 `ContextBuilder.build_for_subagent` 外部行为不变。
- 缺失 required entity 仍进入 clarification。
- Graph path 不变，`compress_short_memory` 节点仍在 `save_assistant_message` 后执行。
- integrations 目录明确为预留/示例，不被误认为主链路。
- `.env.example` 不漏当前 Settings 字段。
- 全量 `compileall` 和 `pytest` 通过。

## 后续注意

历史源码中仍有较多 mojibake 用户文案和测试字符串。它们牵涉断言、Skill 内容和运行时返回语义，应另开批次做“只改文案、不改行为”的专项清理。
