import pytest

from app.adapters.request_adapter import RequestAdapter
from app.query.intent_recognition_node import IntentRecognitionNode
from app.schemas.entities import ConversationWindow, EntityBag
from app.schemas.enums.query import RewriteType
from app.schemas.message import ChatMessage, ChatRequest


def _window(entities: dict | None = None) -> dict:
    bag = EntityBag.from_compact_dict(entities or {}, source="current_query", confidence=0.9)
    return ConversationWindow(session_key="test-session", entity_bag=bag).model_dump()


async def test_graph_final_state_keeps_entities_and_entity_bag_synchronized(app_factory):
    app = app_factory("entity-sync.sqlite3")
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="pingan_health",
            channel="web",
            user_id="u001",
            session_id="s-entity-sync",
            messages=[
                ChatMessage(
                    role="user",
                    content="保全任务完成，受理号930010412672222，保单9200100000458846没有更新？",
                )
            ],
        )
    )

    state = await app.state.container.orchestrator.run(inbound)

    assert state["entities"] == EntityBag(**state["entity_bag"]).to_compact_dict()
    assert state["entities"] == {
        "apply_seq": "930010412672222",
        "policy_no": "9200100000458846",
    }


async def test_query_rewrite_result_entities_are_projected_from_entity_bag(app_factory):
    app = app_factory("entity-rewrite-sync.sqlite3")
    inbound = RequestAdapter().adapt(
        ChatRequest(
            tenant_id="pingan_health",
            channel="web",
            user_id="u001",
            session_id="s-entity-rewrite-sync",
            messages=[ChatMessage(role="user", content="REQ_001 为什么返回 E102？")],
        )
    )

    state = await app.state.container.orchestrator.run(inbound)

    assert "query_rewrite" in state["graph_path"]
    assert state["entities"] == EntityBag(**state["entity_bag"]).to_compact_dict()
    assert state["entities"]["request_id"] == "REQ_001"
    assert state["entities"]["error_code"] == "E102"


async def test_intent_recognition_result_does_not_expose_entities():
    class JsonLLM:
        async def chat(self, *args, **kwargs):
            from app.llm.schemas import LLMResponse

            return LLMResponse(
                content=(
                    '{"intent":"troubleshooting","sub_intent":"refund_failure","confidence":0.91,'
                    '"need_clarification":false}'
                ),
                finish_reason="stop",
                model="fake",
            )

    result = await IntentRecognitionNode(llm_provider=JsonLLM()).recognize(
        original_query="退保失败，保单号9200100000458846",
        rewritten_query="退保失败，保单号9200100000458846",
        entities={"policy_no": "9200100000458846"},
        rewrite_type=RewriteType.DIRECT,
        conversation_window=_window({"policy_no": "9200100000458846"}),
    )

    assert result.intent == "troubleshooting"
    assert "entities" not in result.model_dump()
    assert "missing_required_entities" not in result.model_dump()
    assert "is_follow_up" not in result.model_dump()


async def test_intent_recognition_requires_entities_projection():
    with pytest.raises(ValueError, match="intent_recognition_requires_entities_projection"):
        await IntentRecognitionNode(llm_provider=None).recognize(
            original_query="退保失败，保单号9200100000458846",
            rewritten_query="退保失败，保单号9200100000458846",
            rewrite_type=RewriteType.DIRECT,
            conversation_window=_window({"policy_no": "9200100000458846"}),
        )


async def test_intent_recognition_requires_conversation_window():
    with pytest.raises(ValueError, match="intent_recognition_requires_conversation_window"):
        await IntentRecognitionNode(llm_provider=None).recognize(
            original_query="退保失败，保单号9200100000458846",
            rewritten_query="退保失败，保单号9200100000458846",
            entities={"policy_no": "9200100000458846"},
            rewrite_type=RewriteType.DIRECT,
        )


async def test_intent_recognition_requires_rewrite_type():
    with pytest.raises(ValueError, match="intent_recognition_requires_rewrite_type"):
        await IntentRecognitionNode(llm_provider=None).recognize(
            original_query="退保失败，保单号9200100000458846",
            rewritten_query="退保失败，保单号9200100000458846",
            entities={"policy_no": "9200100000458846"},
            conversation_window=_window({"policy_no": "9200100000458846"}),
        )
