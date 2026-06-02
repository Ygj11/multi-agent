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
    assert GRAPH_STATE_FIELD_AUTHORITY["selected_skill_id"]["source"] == "subagent_result"
    assert GRAPH_STATE_FIELD_AUTHORITY["selected_skill_id"]["kind"] == "cache"
    assert GRAPH_STATE_FIELD_AUTHORITY["selected_skill_metadata"]["kind"] == "cache"
    assert GRAPH_STATE_FIELD_AUTHORITY["skill_selection_score"]["kind"] == "cache"
    assert GRAPH_STATE_FIELD_AUTHORITY["skill_selection_reason"]["kind"] == "cache"
    assert GRAPH_STATE_FIELD_AUTHORITY["pre_answer_verification_result"]["owner"] == "verification_route"
    assert GRAPH_STATE_FIELD_AUTHORITY["pre_answer_verification_result"]["kind"] == "authoritative"
    assert GRAPH_STATE_FIELD_AUTHORITY["verification_results"]["kind"] == "debug"
    assert GRAPH_STATE_FIELD_AUTHORITY["approval_request"]["source"] == "ApprovalStore"
    assert GRAPH_STATE_FIELD_AUTHORITY["approval_request"]["kind"] == "snapshot"
    assert GRAPH_STATE_FIELD_AUTHORITY["available_agents"]["kind"] == "debug"
    assert GRAPH_STATE_FIELD_AUTHORITY["principal"]["kind"] == "cache"
