from app.config.settings import Settings
from app.llm.internal_provider import InternalLLMProvider


def test_default_uses_internal_llm_model():
    provider = InternalLLMProvider(Settings(internal_llm_model="base"))

    assert provider.get_llm_model() == "base"


def test_scene_models_are_used():
    settings = Settings(
        internal_llm_model="base",
        query_rewrite_model="qr",
        intent_recognition_model="intent",
        agent_selection_model="select",
        subagent_reasoning_model="sub",
        final_compliance_model="compliance",
        summary_model="summary",
    )
    provider = InternalLLMProvider(settings)

    assert provider.get_llm_model(scene="query_rewrite") == "qr"
    assert provider.get_llm_model(scene="intent_recognition") == "intent"
    assert provider.get_llm_model(scene="agent_selection") == "select"
    assert provider.get_llm_model(scene="subagent_reasoning") == "sub"
    assert provider.get_llm_model(scene="final_compliance") == "compliance"
    assert provider.get_llm_model(scene="summary") == "summary"


def test_explicit_model_has_highest_priority():
    provider = InternalLLMProvider(Settings(internal_llm_model="base", query_rewrite_model="qr"))

    assert provider.get_llm_model(scene="query_rewrite", explicit_model="override") == "override"


def test_payload_does_not_hardcode_default_model():
    provider = InternalLLMProvider(Settings(internal_llm_model="not-1501"))
    payload = provider._build_payload(
        messages=[],
        tools=None,
        model=provider.get_llm_model(),
        temperature=None,
        max_tokens=None,
    )

    assert payload["model"] == "not-1501"

