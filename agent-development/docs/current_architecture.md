# Current Architecture

This MVP now uses a task-level main Agent orchestration flow.

## Main Flow

The LangGraph flow is:

```text
load_session
-> save_user_message
-> query_rewrite
-> intent_recognition
-> build_orchestrator_context
-> discover_agents
-> select_agent
-> assemble_task
-> dispatch_agent
-> final_compliance_check
-> save_assistant_message
-> compress_short_memory
-> finalize_response
```

`session_key` is still used as LangGraph `thread_id`.

## Agent Discovery

Sub agents are described by AgentCard YAML files in:

```text
app/agents/cards/
```

`AgentCardLoader` loads cards, filters `enabled=false`, performs rule-based candidate matching, and validates card declarations against `SkillCatalog` during app startup.

## Tools

The main execution path uses:

```text
ToolRegistry + ToolExecutor
```

Tool availability is card-driven:

- private tools must appear in `AgentCard.private_tools`
- public tools are available only when `public_tools_allowed=true`
- unauthorized calls return `tool_not_available_for_agent`
- all ToolExecutor calls write `tool_execution_logs`

The old tool broker and policy gate path has been removed. Restricted tools now keep their own explicit disable/allowlist checks, and all sub-agent tool calls still go through `ToolExecutor`.

## Skills

New skills follow:

```text
app/skills/{agent_name}/{skill_name}/SKILL.md
```

`SkillCatalog` scans only this three-level layout and ignores one-level legacy skills. Each active AgentCard skill id must exist in `SkillCatalog`.

## Compliance

All outbound answers pass through `final_compliance_check`. The checker redacts common sensitive values and can force retry/fallback when raw tool output is detected.
