from __future__ import annotations

"""Model selection helpers for scene-aware LLM calls."""

from app.config.settings import Settings
from app.schemas.enums.llm import LLMScene


SCENE_MODEL_FIELDS = {
    LLMScene.QUERY_REWRITE: "query_rewrite_model",
    LLMScene.INTENT_RECOGNITION: "intent_recognition_model",
    LLMScene.AGENT_SELECTION: "agent_selection_model",
    LLMScene.SUBAGENT_REASONING: "subagent_reasoning_model",
    LLMScene.TASK_COMPLETION_VERIFIER: "task_completion_model",
    LLMScene.FINAL_COMPLIANCE: "final_compliance_model",
    LLMScene.SUMMARY: "summary_model",
}


def get_llm_model(settings: Settings, scene: str | LLMScene | None = None, explicit_model: str | None = None) -> str:
    """Resolve model by explicit override, scene model, then default internal model."""
    if explicit_model:
        return explicit_model
    if scene:
        try:
            scene_key = LLMScene(scene)
        except ValueError:
            scene_key = None
        field_name = SCENE_MODEL_FIELDS.get(scene_key)
        if field_name:
            scene_model = getattr(settings, field_name, None)
            if scene_model:
                return scene_model
    return settings.internal_llm_model
