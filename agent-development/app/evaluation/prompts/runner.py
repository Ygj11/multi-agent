from __future__ import annotations

"""Deterministic prompt evaluation fixture loader and runner."""

import json
from pathlib import Path
from typing import Any

import yaml

from app.agents.card_loader import AgentCardLoader
from app.evaluation.prompts.schemas import (
    PromptEvalCase,
    PromptEvalCaseResult,
    PromptEvalReport,
    PromptEvalSuite,
    PromptEvalSuiteResult,
)
from app.llm.base import LLMProvider
from app.llm.output_schemas import SCHEMA_REGISTRY, parse_llm_json_schema
from app.prompts.manifest import PromptManifest
from app.prompts.loader import PromptLoader
from app.query.intent_taxonomy_loader import IntentTaxonomyLoader


PROMPT_EVALUATION_ROOT = Path(__file__).resolve().parent
EVALUATION_ROOT = PROMPT_EVALUATION_ROOT.parent
APP_ROOT = EVALUATION_ROOT.parent
DEFAULT_CASES_ROOT = PROMPT_EVALUATION_ROOT / "cases"


class PromptEvalRunner:
    """Load and execute deterministic prompt eval fixtures.

    This runner intentionally does not call a real LLM. It validates that each
    suite maps to a manifest scene and that each fixture declares expected
    outputs. Real model scoring can plug in behind the same suite/case schema.
    """

    def __init__(
        self,
        *,
        cases_root: Path = DEFAULT_CASES_ROOT,
        manifest: PromptManifest | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.cases_root = Path(cases_root)
        self.manifest = manifest or PromptManifest.load()
        self.prompt_loader = prompt_loader or PromptLoader(manifest=self.manifest)

    def load_suites(self) -> list[PromptEvalSuite]:
        suites: list[PromptEvalSuite] = []
        for path in sorted(self.cases_root.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"eval suite root must be a mapping: {path}")
            suites.append(PromptEvalSuite(**raw))
        if not suites:
            raise ValueError(f"no eval suites found under {self.cases_root}")
        return suites

    def run(self, suite_name: str | None = None) -> PromptEvalReport:
        suites = self.load_suites()
        if suite_name:
            suites = [suite for suite in suites if suite.suite == suite_name]
            if not suites:
                raise ValueError(f"eval suite not found: {suite_name}")
        results = [self._run_suite(suite) for suite in suites]
        total = sum(result.total for result in results)
        passed = sum(result.passed for result in results)
        failed = sum(result.failed for result in results)
        return PromptEvalReport(total=total, passed=passed, failed=failed, suites=results)

    def _run_suite(self, suite: PromptEvalSuite) -> PromptEvalSuiteResult:
        scene = self.manifest.scene(suite.scene)
        case_results: list[PromptEvalCaseResult] = []
        for case in suite.cases:
            errors = self._validate_case(case.expected, scene.output_schema)
            case_results.append(
                PromptEvalCaseResult(
                    id=case.id,
                    passed=not errors,
                    reason="; ".join(errors),
                )
            )
        passed = sum(1 for result in case_results if result.passed)
        failed = len(case_results) - passed
        return PromptEvalSuiteResult(
            suite=suite.suite,
            scene=suite.scene,
            total=len(case_results),
            passed=passed,
            failed=failed,
            cases=case_results,
        )

    async def run_with_provider(
        self,
        llm_provider: LLMProvider,
        suite_name: str | None = None,
    ) -> PromptEvalReport:
        """Run eval fixtures against an injected real or fake LLM provider."""
        suites = self.load_suites()
        if suite_name:
            suites = [suite for suite in suites if suite.suite == suite_name]
            if not suites:
                raise ValueError(f"eval suite not found: {suite_name}")
        results = [await self._run_suite_with_provider(suite, llm_provider) for suite in suites]
        total = sum(result.total for result in results)
        passed = sum(result.passed for result in results)
        failed = sum(result.failed for result in results)
        return PromptEvalReport(total=total, passed=passed, failed=failed, suites=results)

    async def _run_suite_with_provider(
        self,
        suite: PromptEvalSuite,
        llm_provider: LLMProvider,
    ) -> PromptEvalSuiteResult:
        self.manifest.scene(suite.scene)
        case_results = [
            await self._run_case_with_provider(suite, case, llm_provider)
            for case in suite.cases
        ]
        passed = sum(1 for result in case_results if result.passed)
        failed = len(case_results) - passed
        return PromptEvalSuiteResult(
            suite=suite.suite,
            scene=suite.scene,
            total=len(case_results),
            passed=passed,
            failed=failed,
            cases=case_results,
        )

    async def _run_case_with_provider(
        self,
        suite: PromptEvalSuite,
        case: PromptEvalCase,
        llm_provider: LLMProvider,
    ) -> PromptEvalCaseResult:
        scene = self.manifest.scene(suite.scene)
        try:
            variables = self._prompt_variables(suite.scene, case)
            messages = [
                {
                    "role": "system",
                    "content": self.prompt_loader.render_scene_system(suite.scene, **variables),
                }
            ]
            if scene.user:
                messages.append(
                    {
                        "role": "user",
                        "content": self.prompt_loader.render_scene_user(suite.scene, **variables),
                    }
                )
            response = await llm_provider.chat(messages=messages, tools=None, scene=suite.scene)
        except Exception as exc:
            return PromptEvalCaseResult(id=case.id, passed=False, reason=f"provider_error: {exc}")
        if response.finish_reason == "error" or response.error:
            return PromptEvalCaseResult(id=case.id, passed=False, reason=response.error or "llm_error")

        errors = self._validate_provider_output(
            content=response.content or "",
            output_schema=scene.output_schema,
            expected=case.expected,
        )
        return PromptEvalCaseResult(id=case.id, passed=not errors, reason="; ".join(errors))

    def _prompt_variables(self, scene: str, case: PromptEvalCase) -> dict[str, Any]:
        payload = dict(case.input)
        query = str(
            payload.get("original_query")
            or payload.get("current_query")
            or payload.get("rewritten_query")
            or payload.get("query")
            or ""
        )
        rewritten_query = str(payload.get("rewritten_query") or payload.get("query") or query)
        entities = payload.get("entities") if isinstance(payload.get("entities"), dict) else {}

        if scene == "query_rewrite":
            return {
                **payload,
                "original_query": query,
                "current_entities": payload.get("current_entities") or entities,
                "conversation_window": payload.get("conversation_window") or self._conversation_window(payload),
            }
        if scene == "intent_recognition":
            return {
                **payload,
                "original_query": query,
                "rewritten_query": rewritten_query,
                "entities": entities,
                "rewrite_type": payload.get("rewrite_type") or "direct",
                "conversation_window": payload.get("conversation_window") or self._conversation_window(payload),
                "intent_taxonomy": payload.get("intent_taxonomy") or self._intent_taxonomy(),
                "allowed_intents": payload.get("allowed_intents") or self._allowed_intents(),
                "candidate_sub_intents": payload.get("candidate_sub_intents") or self._candidate_sub_intents(),
                "agent_card_summaries": payload.get("agent_card_summaries") or self._agent_card_summaries(),
            }
        if scene == "agent_selection":
            return {
                **payload,
                "query": payload.get("query") or rewritten_query,
                "intent": payload.get("intent") or "unknown",
                "sub_intent": payload.get("sub_intent"),
                "intent_confidence": payload.get("intent_confidence", 1.0),
                "entities": entities,
                "candidates": payload.get("candidates") or [],
            }
        if scene == "skill_selection":
            return {
                **payload,
                "agent_name": payload.get("agent_name") or self._agent_name(payload),
                "original_query": query,
                "rewritten_query": rewritten_query,
                "intent": payload.get("intent") or "unknown",
                "sub_intent": payload.get("sub_intent"),
                "entities": entities,
                "candidates": payload.get("candidates") or [],
            }
        if scene == "subagent_reasoning":
            return {
                **payload,
                "agent_name": payload.get("agent_name") or self._agent_name(payload),
                "agent_description": payload.get("agent_description") or "",
                "skill_content": payload.get("skill_content") or json.dumps(payload, ensure_ascii=False, indent=2),
                "original_query": query,
                "rewritten_query": rewritten_query,
                "intent": payload.get("intent") or "unknown",
                "entities": entities,
                "short_summary": payload.get("short_summary") or "",
                "lightweight_hints": payload.get("lightweight_hints") or [],
            }
        if scene == "memory_summary":
            return {
                **payload,
                "previous_summary": payload.get("previous_summary") or "",
                "current_turn": payload.get("current_turn") or query,
            }
        return payload

    @staticmethod
    def _conversation_window(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": payload.get("short_summary"),
            "recent_turns": payload.get("recent_messages") or [],
            "entity_bag": payload.get("entity_bag") or {},
        }

    @staticmethod
    def _agent_name(payload: dict[str, Any]) -> str:
        selected_skill_id = str(payload.get("selected_skill_id") or "")
        if "." in selected_skill_id:
            return selected_skill_id.split(".", 1)[0]
        return "unknown_agent"

    @staticmethod
    def _intent_taxonomy() -> list[dict[str, Any]]:
        return IntentTaxonomyLoader().summaries_for_prompt()

    @staticmethod
    def _allowed_intents() -> list[str]:
        return IntentTaxonomyLoader().list_allowed_intents()

    @staticmethod
    def _candidate_sub_intents() -> dict[str, list[str]]:
        return IntentTaxonomyLoader().list_candidate_sub_intents()

    @staticmethod
    def _agent_card_summaries() -> list[dict[str, Any]]:
        loader = AgentCardLoader(APP_ROOT / "agents" / "cards")
        return [
            {
                "agent_name": card.agent_name,
                "description": card.description,
                "supported_routes": card.normalized_supported_routes(),
                "capabilities": card.capabilities,
                "required_entities": card.required_entities,
                "optional_entities": card.optional_entities,
                "examples": card.examples,
            }
            for card in loader.list_available_agents()
        ]

    @staticmethod
    def _validate_provider_output(
        *,
        content: str,
        output_schema: str,
        expected: dict[str, Any],
    ) -> list[str]:
        errors: list[str] = []
        if output_schema in SCHEMA_REGISTRY:
            parsed = parse_llm_json_schema(content, SCHEMA_REGISTRY[output_schema])
            if not parsed.success:
                return [f"{parsed.error_code}: {parsed.error_detail}"]
            output_payload = parsed.data.model_dump() if parsed.data is not None else {}
            searchable = json.dumps(output_payload, ensure_ascii=False)
        else:
            output_payload = {}
            searchable = content

        ignored_expected_keys = {"output_schema", "must_include", "must_not_include"}
        for key, expected_value in expected.items():
            if key in ignored_expected_keys:
                continue
            if output_payload.get(key) != expected_value:
                errors.append(f"{key} expected {expected_value!r}, got {output_payload.get(key)!r}")
        for token in expected.get("must_include") or []:
            if str(token) not in searchable:
                errors.append(f"missing expected token: {token}")
        for token in expected.get("must_not_include") or []:
            if str(token) in searchable:
                errors.append(f"unexpected token present: {token}")
        return errors

    @staticmethod
    def _validate_case(expected: dict[str, Any], output_schema: str) -> list[str]:
        errors: list[str] = []
        if expected.get("output_schema") and expected["output_schema"] != output_schema:
            errors.append(
                f"expected output_schema {expected['output_schema']} does not match manifest {output_schema}"
            )
        if "must_include" in expected and not isinstance(expected["must_include"], list):
            errors.append("must_include must be a list when present")
        if "must_not_include" in expected and not isinstance(expected["must_not_include"], list):
            errors.append("must_not_include must be a list when present")
        return errors
