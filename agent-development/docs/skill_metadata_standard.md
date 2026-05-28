# Skill Metadata Standard

本项目只允许企业级完整 Skill metadata。所有参与运行时选择的 Skill 必须位于：

```text
app/skills/<agent_name>/<skill_name>/SKILL.md
```

`app/skills/deprecated/**/SKILL.md` 可以保留历史材料，但 `SkillCatalog` 不扫描，也不参与 AgentCard 校验和 SkillSelector 选择。

## 必填 Frontmatter

每个 active `SKILL.md` 必须包含完整 YAML frontmatter：

```yaml
---
skill_id: <agent_name>.<skill_name>
name: <中文名称>
description: <使用场景描述>
agent: <agent_name>
intent_tags:
  - <intent>
required_entities: []

private_tools: []
enabled: true
is_default: false
---
```

允许保留可选增强字段：

```yaml
business_domain:
  - health_insurance_onboarding
required_context:
  - request_id
```

## 校验规则

- `skill_id` 全局唯一。
- `skill_id` 必须使用 `<agent_name>.<skill_name>` 格式。
- `skill_id` 必须以 `agent` 字段开头。
- `agent` 必须对应真实 `AgentCard.agent_name`。
- `AgentCard.skills` 中声明的 skill 必须能在 `SkillCatalog` 中找到。
- `skill.private_tools` 必须是该 AgentCard `private_tools` 的子集。
- 每个 AgentCard 对应的 enabled skill 中至少有一个 `is_default=true`。
- 只有 `name/description` 的旧格式会校验失败。
- 没有 frontmatter 的 `SKILL.md` 会校验失败。
- `deprecated` 目录不参与扫描。

## 代码位置

- Schema: `app/schemas/skill.py::SkillMetadata`
- Parser: `app/skills/metadata.py::metadata_from_skill_file`
- Required fields: `app/skills/metadata.py::REQUIRED_SKILL_METADATA_FIELDS`
- Catalog scan: `app/skills/catalog.py::SkillCatalog.scan`
- AgentCard 校验: `app/agents/card_loader.py::AgentCardLoader.validate_with_skill_catalog`
