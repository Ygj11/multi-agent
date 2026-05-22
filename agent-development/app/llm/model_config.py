from __future__ import annotations

"""Model selection helpers for scene-aware LLM calls."""

from app.config.settings import Settings


SCENE_MODEL_FIELDS = {
    "query_rewrite": "query_rewrite_model",
    "intent_recognition": "intent_recognition_model",
    "agent_selection": "agent_selection_model",
    "subagent_reasoning": "subagent_reasoning_model",
    "final_compliance": "final_compliance_model",
    "summary": "summary_model",
}


def get_llm_model(settings: Settings, scene: str | None = None, explicit_model: str | None = None) -> str:
    """Resolve model by explicit override, scene model, then default internal model."""
    if explicit_model:
        return explicit_model
    if scene:
        field_name = SCENE_MODEL_FIELDS.get(scene)
        if field_name:
            scene_model = getattr(settings, field_name, None)
            if scene_model:
                return scene_model
    return settings.internal_llm_model

