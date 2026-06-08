# Entity Routing Design

This document records the current code-level design for query rewrite, intent recognition, entity extraction, and agent selection.

## Current Architecture

The main agent does not naturally know every business entity. It uses a three-layer design:

1. Generic extraction: `app/query/entity_extractor.py::EntityExtractor` loads `app/query/entity_patterns.yaml` and extracts common entities from the current query, summary, and recent turns.
2. Agent routing needs: `app/agents/cards/*.yaml` declares each AgentCard's `required_entities` and `optional_entities` for coarse recall and scoring.
3. Skill execution needs: `app/skills/*/*/SKILL.md` declares `required_entities` and `optional_entities` for a concrete workflow. Missing required skill entities trigger clarification before tool calls.

`app/schemas/entities.py::EntityBag` is the dynamic entity container. It can hold any entity type, such as `policy_no`, `request_id`, `error_code`, `claim_no`, `interface_name`, `hospital_name`, `document_type`, `phone_number`, and `id_card`. `ConversationWindow` carries an `EntityBag`; it should not gain top-level fields like `last_policy_no`.

## Query Rewrite

`app/query/query_rewrite_node.py::QueryRewriteNode.rewrite`:

- extracts entities from the current query with `EntityExtractor`
- extracts historical entities from `short_summary` and `recent_messages`
- merges them into `EntityBag`
- inherits only a unique high-confidence historical entity for follow-up questions
- returns clarification when a follow-up has multiple candidates or no safe inherited entity
- calls `LLMProvider.chat(scene="query_rewrite")` for JSON rewrite when available
- falls back to EntityBag-based deterministic rewrite when JSON is invalid or model use is unavailable

The old fixed follow-up marker path is not the main path. Markers can only be weak signals.

## Intent Recognition

`app/query/intent_recognition_node.py::IntentRecognitionNode.recognize` takes:

- `original_query`
- `rewritten_query`
- current dynamic entities
- `conversation_window`
- lightweight AgentCard summaries

It expects LLM JSON with `intent`, `sub_intent`, `confidence`, dynamic `entities`, `missing_required_entities`, and clarification fields. It must not output tools. If JSON is invalid or model use is unavailable, it uses the new entity-aware rule fallback.

Intent boundaries are explicit:

- `app/config/intent_taxonomy.yaml` is the only source of legal `intent` and `sub_intent` values.
- `AgentCard.supported_routes` declares which taxonomy routes an agent can handle.
- `SkillMetadata.intent/sub_intents` declares which taxonomy routes a skill handles inside one agent.
- `capabilities` is evidence for classification and scoring, not an allowed `intent` or `sub_intent` value.

## Hybrid Agent Selection

`app/agents/card_loader.py::AgentCardLoader.match_candidates` produces deterministic candidates using:

- enabled status
- intent and sub_intent matches
- required entity presence or missing entity penalties
- optional entity matches
- capability, description, example, and query keyword matches

`app/agents/selection.py::AgentSelectionNode.select` then decides:

- choose rule Top1 directly when score and margin are confident
- call `app/agents/llm_router.py::LLMAgentRouter` when scores are close, intent confidence is low, query is a follow-up, or the query is semantically complex
- validate that the LLM-selected agent is one of the Top-K candidates
- fall back to rule Top1 or clarification when JSON is invalid, the selected agent is illegal, or confidence is too low

The LLM Router receives only Top-K AgentCard summaries. It does not receive all tools, all Skill bodies, or internal sub-agent prompts.

## Skill Required Entity Check

`app/runtime/context_builder.py::ContextBuilder.build_for_subagent` selects a skill and then calls `app/skills/required_entities.py::RequiredEntityChecker`.

If all required entities are present, the selected skill body is loaded and the sub agent can proceed to `ToolCallingRunner`. If a required entity is missing, `BaseSubAgent.run` returns a clarification `SubAgentResult` and does not call tools. Optional entities improve selection but do not block execution.

## Clarification Flow

Clarification can be produced by query rewrite, intent recognition, agent selection, or skill required entity checking. In the graph this must avoid `dispatch_agent` when clarification is already known:

```text
query_rewrite / intent_recognition / select_agent
-> build_clarification_answer
-> pre_answer_verify
-> save_assistant_message
-> compress_short_memory
-> finalize_response
```

Skill-level clarification happens inside `BaseSubAgent.run`, then continues through `pre_answer_verify` like any other answer. `pre_answer_verify` calls `VerificationService(stage="pre_answer")`; compliance redaction is now implemented as a verifier, not as a separate graph node.

## Tests

Relevant tests:

- `tests/test_entity_patterns_loader.py`
- `tests/test_entity_extractor.py`
- `tests/test_entity_bag.py`
- `tests/test_query_rewrite_entity_inheritance.py`
- `tests/test_intent_recognition_llm_json.py`
- `tests/test_agent_selection_hybrid_router.py`
- `tests/test_skill_required_entities.py`
- `tests/test_clarification_flow.py`
- `tests/test_architecture_acceptance.py`
