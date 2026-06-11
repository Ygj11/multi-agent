# Architecture Acceptance Checklist

## Stage 1: AgentCard Foundation

- [x] AgentCard schema exists.
- [x] AgentCard YAML files exist for troubleshooting, claim, policy query, compliance, document parse, and change impact agents.
- [x] AgentCardLoader loads and validates card shape.
- [x] AgentCard tests cover required fields, disabled cards, matching, and key card fields.

## Stage 2: Intent And Entity Recognition

- [x] IntentRecognitionNode outputs `intent`, `entities`, and `confidence`.
- [x] IntentRecognitionNode no longer binds tools or selected sub agents.

## Stage 3: Dynamic Agent Orchestration

- [x] LangGraph includes `discover_agents`, `select_agent`, `assemble_task`, and `dispatch_agent`.
- [x] Fixed `route_intent/call_xxx_agent` is no longer in the main graph.

## Stage 4: ToolExecutor

- [x] ToolRegistry supports public and private tools.
- [x] ToolExecutor enforces AgentCard tool availability.
- [x] SQLite includes `tool_execution_logs`.
- [x] Tool authorization tests cover successful and denied executions.

## Stage 5: Sub Agent Protocol

- [x] BaseSubAgent centralizes AgentCard reading, tool visibility, skill context construction, and tool calling.
- [x] troubleshooting_agent and pos_query_agent use BaseSubAgent.
- [x] SubAgentResult includes agent name, task id, evidence, tool calls, confidence, approval flag, risk level, and metadata.

## Stage 6: Pre-answer Verification

- [x] All main graph responses pass through `pre_answer_verify`.
- [x] `pre_answer_verify` calls `VerificationService(stage="pre_answer")`.
- [x] Compliance redaction is provided by `ComplianceVerifier` inside VerificationService.
- [x] Sensitive values are redacted.
- [x] Raw tool output can trigger retry/fallback routing.
- [x] Retry routing is limited to one retry.

## Stage 7: Skills And Acceptance Tests

- [x] SkillCatalog scans only `skills/{agent_name}/{skill_name}/SKILL.md`.
- [x] AgentCard skills are validated against SkillCatalog.
- [x] Skill private tools must be a subset of AgentCard private tools.
- [x] Skill selection may return no skill when no candidate matches confidently.
- [x] Full architecture acceptance test covers the refund failure flow.

## Stage 8: Runtime State Governance

- [x] `AgentGraphState` is not persisted directly as checkpoint payload.
- [x] `CheckpointSnapshot` is the explicit durable checkpoint contract.
- [x] `AgentResumeState` is the explicit approval resume contract.
- [x] SQLite `graph_checkpoints` stores `schema_version` and `snapshot_json`, not full `state_json`.
- [x] Approval resume storage uses `resume_state_json`, not full `pending_state_json`.
- [x] Runtime-only fields such as `conversation_window`, `recent_messages`, `entity_bag`, full `subagent_result`, and full tool schemas are excluded from checkpoint snapshots.
- [x] `GRAPH_STATE_FIELD_AUTHORITY` declares `owner`, `source`, `kind`, and `persistence` for every graph state field.
- [x] State size inspection is available through `scripts/audit_graph_state_size.py`.
