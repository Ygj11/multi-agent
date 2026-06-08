from __future__ import annotations

"""Schemas for the global intent taxonomy."""

from typing import Any

from pydantic import BaseModel, Field, model_validator


class SubIntentDefinition(BaseModel):
    """One supported sub-intent under a top-level intent."""

    display_name: str
    description: str
    examples: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_text(self) -> "SubIntentDefinition":
        if not self.display_name.strip():
            raise ValueError("sub_intent display_name is required")
        if not self.description.strip():
            raise ValueError("sub_intent description is required")
        return self


class IntentDefinition(BaseModel):
    """One top-level business intent."""

    display_name: str
    description: str
    examples: list[str] = Field(default_factory=list)
    sub_intents: dict[str, SubIntentDefinition] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_text(self) -> "IntentDefinition":
        if not self.display_name.strip():
            raise ValueError("intent display_name is required")
        if not self.description.strip():
            raise ValueError("intent description is required")
        return self


class IntentTaxonomy(BaseModel):
    """Global source of legal intent and sub_intent values."""

    intents: dict[str, IntentDefinition]

    @model_validator(mode="after")
    def validate_intents(self) -> "IntentTaxonomy":
        if not self.intents:
            raise ValueError("intent taxonomy must declare at least one intent")
        for intent, definition in self.intents.items():
            if not intent.strip():
                raise ValueError("intent key must not be empty")
            for sub_intent in definition.sub_intents:
                if not sub_intent.strip():
                    raise ValueError(f"{intent} sub_intent key must not be empty")
        return self

    def allowed_intents(self) -> list[str]:
        """Return sorted legal top-level intent values."""
        return sorted(self.intents)

    def candidate_sub_intents(self) -> dict[str, list[str]]:
        """Return sorted legal sub-intents grouped by parent intent."""
        return {
            intent: sorted(definition.sub_intents)
            for intent, definition in sorted(self.intents.items())
        }

    def is_allowed_intent(self, intent: str) -> bool:
        """True when `intent` is a legal top-level intent."""
        return intent in self.intents

    def is_allowed_sub_intent(self, intent: str, sub_intent: str) -> bool:
        """True when `sub_intent` belongs to the provided top-level intent."""
        definition = self.intents.get(intent)
        return bool(definition and sub_intent in definition.sub_intents)

    def summaries_for_prompt(self) -> list[dict[str, Any]]:
        """Return compact taxonomy summaries for LLM prompts."""
        summaries: list[dict[str, Any]] = []
        for intent, definition in sorted(self.intents.items()):
            summaries.append(
                {
                    "intent": intent,
                    "display_name": definition.display_name,
                    "description": definition.description,
                    "examples": definition.examples,
                    "sub_intents": [
                        {
                            "sub_intent": sub_intent,
                            "display_name": sub_definition.display_name,
                            "description": sub_definition.description,
                            "examples": sub_definition.examples,
                        }
                        for sub_intent, sub_definition in sorted(definition.sub_intents.items())
                    ],
                }
            )
        return summaries
