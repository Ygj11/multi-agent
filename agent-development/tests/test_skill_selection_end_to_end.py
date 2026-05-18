from app.adapters.request_adapter import RequestAdapter
from app.schemas.message import ChatMessage, ChatRequest


async def test_troubleshooting_req_001_selects_signature_error_skill(app_factory):
    """REQ_001 端到端应选择 troubleshooting.signature_error。"""
    app = app_factory("skill-e2e.sqlite3")
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="pingan_health",
            channel="web",
            user_id="u001",
            session_id="s001",
            messages=[ChatMessage(role="user", content="REQ_001 为什么返回 E102？")],
        )
    )

    state = await app.state.orchestrator.run(inbound)

    assert state["intent"] == "troubleshooting"
    assert state["selected_skill_id"] == "troubleshooting.signature_error"
    assert state["subagent_result"]["selected_skill_id"] == "troubleshooting.signature_error"
    assert "E102" in state["answer"]


async def test_change_impact_selects_signature_rule_change_skill(app_factory):
    """签名规则变更影响分析应选择 signature_rule_change skill。"""
    app = app_factory("skill-change.sqlite3")
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="pingan_health",
            channel="web",
            user_id="u001",
            session_id="s-change",
            messages=[
                ChatMessage(
                    role="user",
                    content="签名规则变更：timestamp 必须加入签名原文。请分析影响哪些接口、错误码和测试。",
                )
            ],
        )
    )

    state = await app.state.orchestrator.run(inbound)

    assert state["intent"] == "change_impact_analysis"
    assert state["selected_skill_id"] == "change_impact.signature_rule_change"
    assert state["subagent_result"]["selected_skill_id"] == "change_impact.signature_rule_change"
