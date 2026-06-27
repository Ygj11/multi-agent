from app.llm.output_schemas import SCHEMA_REGISTRY
from app.prompts.loader import PromptLoader
from app.prompts.manifest import PromptManifest, PROMPTS_ROOT


def test_prompt_manifest_loads_and_validates_assets():
    manifest = PromptManifest.load()

    assert manifest.version == "1.0.0"
    assert not manifest.validate_assets(PROMPTS_ROOT)


def test_prompt_manifest_declares_required_scenes_and_schema_names():
    manifest = PromptManifest.load()
    required = {
        "query_rewrite",
        "intent_recognition",
        "agent_selection",
        "skill_selection",
        "subagent_reasoning",
        "memory_summary",
        "final_compliance",
    }

    assert required.issubset(manifest.scenes)
    for scene_name, scene in manifest.scenes.items():
        assert scene.scene == scene_name
        assert scene.version
        assert scene.eval_suite
        assert scene.output_schema in SCHEMA_REGISTRY or scene.output_schema in {
            "text",
            "SubAgentResult",
            "VerificationResult",
        }


def test_prompt_loader_renders_scene_templates_and_trace():
    loader = PromptLoader()

    rendered = loader.render_scene_user(
        "intent_recognition",
        original_query="保全任务完成但没有更新",
        rewritten_query="保全任务完成但没有更新",
        entities={"policy_no": "9200100000458846"},
        rewrite_type="new_request",
        conversation_window={},
        intent_taxonomy=[],
        allowed_intents=["troubleshooting"],
        candidate_sub_intents={"troubleshooting": ["endo_completion_aftercare"]},
        agent_card_summaries=[],
    )
    trace = loader.scene_trace("intent_recognition")

    assert "保全任务完成但没有更新" in rendered
    assert trace["prompt_scene"] == "intent_recognition"
    assert trace["prompt_version"]
    assert trace["output_schema"] == "IntentRecognitionLLMOutput"
    assert trace["eval_suite"] == "intent_taxonomy_v1"
