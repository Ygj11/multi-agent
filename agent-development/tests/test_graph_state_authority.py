from app.runtime.graph_state import AgentGraphState, GRAPH_STATE_FIELD_AUTHORITY


def test_graph_state_authority_table_covers_every_agent_graph_state_field():
    state_fields = set(AgentGraphState.__annotations__)

    assert state_fields.issubset(GRAPH_STATE_FIELD_AUTHORITY)
    for field in state_fields:
        metadata = GRAPH_STATE_FIELD_AUTHORITY[field]
        assert metadata["owner"]
        assert metadata["source"]
        assert metadata["kind"] in {"authoritative", "cache", "debug", "snapshot", "deprecated"}


def test_subagent_result_is_authoritative_for_skill_selection_cache():
    assert GRAPH_STATE_FIELD_AUTHORITY["subagent_result"]["owner"] == "execution_result"
    assert "selected_skill_id" not in AgentGraphState.__annotations__
    assert "selected_skill_metadata" not in AgentGraphState.__annotations__
    assert "skill_selection_score" not in AgentGraphState.__annotations__
    assert "skill_selection_reason" not in AgentGraphState.__annotations__
    assert "selected_skill_id" not in GRAPH_STATE_FIELD_AUTHORITY
    assert "selected_skill_metadata" not in GRAPH_STATE_FIELD_AUTHORITY
    assert "skill_selection_score" not in GRAPH_STATE_FIELD_AUTHORITY
    assert "skill_selection_reason" not in GRAPH_STATE_FIELD_AUTHORITY
    assert GRAPH_STATE_FIELD_AUTHORITY["pre_answer_verification_result"]["owner"] == "verification_route"
    assert GRAPH_STATE_FIELD_AUTHORITY["pre_answer_verification_result"]["kind"] == "authoritative"
    assert GRAPH_STATE_FIELD_AUTHORITY["verification_results"]["kind"] == "debug"
    assert "approval_request" not in AgentGraphState.__annotations__
    assert "approval_request" not in GRAPH_STATE_FIELD_AUTHORITY
    assert "target_subagent" not in AgentGraphState.__annotations__
    assert "target_subagent" not in GRAPH_STATE_FIELD_AUTHORITY
    assert GRAPH_STATE_FIELD_AUTHORITY["available_agents"]["kind"] == "debug"
    assert "principal" not in AgentGraphState.__annotations__
    assert "principal" not in GRAPH_STATE_FIELD_AUTHORITY
    assert GRAPH_STATE_FIELD_AUTHORITY["auth_context"]["kind"] == "authoritative"
