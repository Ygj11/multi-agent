from app.runtime.state_projector import project_approval_resume_state, project_checkpoint_snapshot


def test_checkpoint_projection_excludes_runtime_only_fields_and_large_payloads():
    state = {
        "request_id": "req_1",
        "trace_id": "trace_1",
        "tenant_id": "tenant",
        "channel": "web",
        "user_id": "u1",
        "session_id": "s1",
        "session_key": "tenant:web:u1:s1",
        "thread_id": "tenant:web:u1:s1:req_1",
        "original_query": "保单更新失败",
        "rewritten_query": "保单 9200100000458846 更新失败",
        "intent": "troubleshooting",
        "sub_intent": "endo_completion_aftercare",
        "confidence": 0.95,
        "entities": {"policy_no": "9200100000458846", "token": "should_not_persist"},
        "selected_agent": "troubleshooting_agent",
        "agent_selection_summary": {
            "selected_agent": "troubleshooting_agent",
            "confidence": 0.95,
            "selection_method": "rule",
            "candidate_count": 2,
        },
        "conversation_window": {"raw": "large history"},
        "recent_messages": [{"role": "user", "content": "history"}],
        "entity_bag": {"policy_no": [{"value": "9200100000458846"}]},
        "available_agents": [{"agent_name": "troubleshooting_agent"}],
        "selected_agent_card": {"agent_name": "troubleshooting_agent", "large": True},
        "pending_tools": [{"type": "function", "function": {"name": "notice_policy_update"}}],
        "subagent_result": {
            "selected_skill_id": "troubleshooting_agent.endo_completion_aftercare",
            "tool_calls": [
                {
                    "name": "query_task_status",
                    "success": True,
                    "result": {"huge": "payload"},
                    "duration_ms": 10,
                }
            ],
            "evidence": [
                {
                    "type": "tool_observation",
                    "source": "query_task_status",
                    "tool_name": "query_task_status",
                    "summary": "done",
                    "result_preview": {"huge": "payload"},
                }
            ],
        },
        "answer": "已完成排查",
        "graph_path": ["route_entry", "finalize_response"],
    }

    snapshot = project_checkpoint_snapshot(state).model_dump(mode="json")

    for key in (
        "conversation_window",
        "recent_messages",
        "entity_bag",
        "available_agents",
        "selected_agent_card",
        "pending_tools",
        "subagent_result",
    ):
        assert key not in snapshot
    assert snapshot["entities"] == {"policy_no": "9200100000458846"}
    assert snapshot["agent_selection_summary"]["selected_agent"] == "troubleshooting_agent"
    assert "candidates" not in snapshot["agent_selection_summary"]
    assert snapshot["selected_skill_id"] == "troubleshooting_agent.endo_completion_aftercare"
    assert snapshot["tool_log_refs"] == [
        {
            "tool_name": "query_task_status",
            "tool_call_id": None,
            "execution_id": None,
            "status": "success",
            "approval_id": None,
            "error": None,
        }
    ]
    assert "result" not in snapshot["tool_log_refs"][0]
    assert snapshot["evidence_refs"][0]["summary"] == "done"
    assert "result_preview" not in snapshot["evidence_refs"][0]


def test_resume_projection_keeps_only_execution_resume_payload():
    state = {
        "request_id": "req_1",
        "trace_id": "trace_1",
        "session_key": "tenant:web:u1:s1",
        "thread_id": "tenant:web:u1:s1:req_1",
        "original_query": "保全任务完成但未更新",
        "rewritten_query": "保单 9200100000458846 受理 930021042875719 未更新",
        "intent": "troubleshooting",
        "sub_intent": "endo_completion_aftercare",
        "entities": {"policy_no": "9200100000458846", "apply_seq": "930021042875719"},
        "selected_agent": "troubleshooting_agent",
        "conversation_window": {"raw": "not persisted"},
        "auth_context": {"principal": {"tenant_id": "tenant", "user_id": "u1", "subject": "sub"}},
        "subagent_result": {
            "selected_skill_id": "troubleshooting_agent.endo_completion_aftercare",
            "selected_skill_metadata": {"name": "aftercare"},
            "skill_selection_score": 0.88,
            "skill_selection_reason": "matched",
        },
    }
    resume = project_approval_resume_state(
        state,
        pending_tool_call={
            "name": "notice_policy_update",
            "arguments": {"apply_seq": "930021042875719", "authorization": "should_not_persist"},
        },
        pending_messages=[{"role": "assistant", "content": "tool call"}],
        pending_tools=[{"type": "function", "function": {"name": "notice_policy_update"}}],
        approval_id="approval_1",
        approval_status="pending",
    ).model_dump(mode="json")

    assert "conversation_window" not in resume
    assert resume["approval_id"] == "approval_1"
    assert resume["pending_tool_name"] == "notice_policy_update"
    assert resume["pending_tool_arguments"] == {"apply_seq": "930021042875719"}
    assert resume["selected_skill_id"] == "troubleshooting_agent.endo_completion_aftercare"
    assert resume["auth_context_summary"] == {"tenant_id": "tenant", "user_id": "u1", "subject": "sub", "org_id": None}
