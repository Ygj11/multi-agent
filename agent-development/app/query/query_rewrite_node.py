from __future__ import annotations

"""实体感知的 Query Rewrite 节点。

Query Rewrite 的目标不是美化用户措辞，而是把依赖上下文的追问、澄清补参
或省略主语的问题改写成后续节点可独立理解的业务问题。当前轮规则实体、
历史实体候选、LLM 返回候选都必须进入 EntityResolver 后，才能成为
canonical entity_bag。
"""

from dataclasses import dataclass
from typing import Any

from app.llm.base import LLMProvider
from app.llm.output_schemas import QueryRewriteLLMOutput, parse_llm_json_schema
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.query.context_reference_policy import QueryContextReferencePolicy
from app.query.entity_extractor import EntityExtractor
from app.query.entity_resolver import EntityResolver
from app.runtime.decision_trace import LLMAttempt
from app.runtime.failure_codes import (
    LLM_DISABLED,
    LLM_JSON_PARSE_FAILED,
    LLM_PROVIDER_ERROR,
    LLM_SCHEMA_VALIDATION_FAILED,
    LLM_STATUS_DISABLED,
    LLM_STATUS_INVALID_OUTPUT,
    LLM_STATUS_PARSE_FAILED,
    LLM_STATUS_PROVIDER_ERROR,
    LLM_STATUS_SUCCESS,
)
from app.schemas.enums.llm import LLMScene
from app.schemas.enums.query import RewriteType
from app.schemas.entities import ConversationWindow, EntityBag, EntityMention
from app.schemas.query_rewrite import QueryRewriteResult


@dataclass(frozen=True)
class ContextReferenceResult:
    """当前轮是否引用历史上下文的规则判断结果。"""

    is_reference: bool
    reason: str
    turn_type: str
    target_index: int | None = None
    target_hint: str | None = None


class QueryRewriteNode:
    """结合动态实体与会话记忆进行查询改写。

    本节点是实体状态收敛的入口：它可以提取、继承和解析实体；后续 Intent
    Recognition 只能读取解析后的实体，不应再维护第二套实体状态。
    """

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        entity_extractor: EntityExtractor | None = None,
        entity_resolver: EntityResolver | None = None,
        prompt_loader: PromptLoader | None = None,
        context_reference_policy: QueryContextReferencePolicy | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.entity_resolver = entity_resolver or EntityResolver(
            entity_type_registry=self.entity_extractor.entity_type_registry
        )
        self.prompt_loader = prompt_loader or default_prompt_loader
        self.context_reference_policy = context_reference_policy or QueryContextReferencePolicy.load()

    async def rewrite(
        self,
        original_query: str,
        recent_messages: list[dict[str, Any]] | None = None,
        short_summary: str | None = None,
        session_key: str = "",
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> QueryRewriteResult:
        """
        Rewrite the query and return dynamic entities plus clarification state.
        查询改写采用“LLM 优先、确定性规则兜底”的双层策略。

        第一层先从当前问题、短摘要和最近消息中通过 EntityExtractor 提取
        可确定识别的实体，并由 EntityResolver 统一处理别名、覆盖优先级和冲突。
        当前轮明确实体优先于历史实体，多个同优先级候选不能静默选择。

        随后将原问题、当前实体和 ConversationWindow 交给 LLM。LLM 的职责是：
        解决指代、判断新请求/追问/澄清补参，并把依赖上下文的问题改写为自包含问题。

        若 LLM 未启用、调用异常、返回非 JSON 或不满足 QueryRewriteLLMOutput，
        则不使用不可信结果，而是进入规则改写。llm_attempt 仅记录本次尝试状态，
        用于生成 fallback_reason 和 decision_trace，便于排查降级原因。
        """
        extracted_current_bag = self.entity_extractor.extract(original_query, source="current_query")
        parallel_current_entity_types = self._parallel_current_entity_types(extracted_current_bag)
        current_bag = self.entity_resolver.resolve(
            base_bag=EntityBag(),
            candidate_bag=extracted_current_bag,
            stage="query_rewrite_current",
            parallel_current_entity_types=parallel_current_entity_types,
        ).entity_bag
        summary_bag = self.entity_extractor.extract_from_summary(short_summary)
        recent_bag = self.entity_extractor.extract_from_recent_turns(recent_messages or [])

        # 最近消息的优先级高于摘要
        history_bag = self.entity_resolver.resolve(
            base_bag=summary_bag,
            candidate_bag=recent_bag,
            stage="query_rewrite_history",
        ).entity_bag
        window_bag = EntityBag().merge(history_bag).merge(current_bag)
        window = ConversationWindow(
            session_key=session_key,
            summary=short_summary,
            recent_turns=recent_messages or [],
            entity_bag=window_bag,
        )

        llm_result, llm_attempt = await self._rewrite_with_llm(
            original_query,
            current_bag,
            window,
            request_id,
            trace_id,
            session_key,
            parallel_current_entity_types,
        )
        if llm_result is not None:
            return llm_result

        return self._rewrite_with_rules(
            original_query,
            current_bag,
            history_bag,
            window,
            llm_attempt,
            parallel_current_entity_types,
        )

    async def _rewrite_with_llm(
        self,
        original_query: str,
        current_bag: EntityBag,
        window: ConversationWindow,
        request_id: str | None,
        trace_id: str | None,
        session_key: str | None,
        parallel_current_entity_types: set[str],
    ) -> tuple[QueryRewriteResult | None, LLMAttempt]:
        """
        LLM 改写路径：
        1. 输入原问题、当前轮确定性实体和会话窗口，不提供工具调用能力；
        2. 强制要求返回 QueryRewriteLLMOutput JSON；
        3. LLM 返回的 entities 只表示当前轮补充候选，inherited_entities 只表示历史继承候选；
        4. 若模型仍把继承值 echo 到 entities，先过滤掉，避免继承来源 metadata 被改成 llm；
        5. 当前轮规则实体作为 base_bag，LLM 当前轮候选和继承候选作为 candidate_bag，
            必须经过 EntityResolver 后才形成 canonical entity_bag。
        """

        """
        当前用户问题
          ↓ 规则实体提取
        extracted_current_bag
          ↓ Resolver 规范化
        current_bag
        
        短期摘要 ──规则提取──→ summary_bag
        最近对话 ──规则提取──→ recent_bag
                                  ↓ Resolver
                              history_bag
        
        history_bag + current_bag
                  ↓
        ConversationWindow
                  ↓
                 LLM
                  ↓
        rewritten_query
        entities
        inherited_entities
                  ↓
        llm_bag + inherited_bag
                  ↓
        current_bag 作为 base
                  ↓ EntityResolver
        最终 canonical entity_bag
        """
        prompt_trace = self.prompt_loader.scene_trace(str(LLMScene.QUERY_REWRITE))
        if not self._should_use_llm_json():
            return None, LLMAttempt(
                llm_status=LLM_STATUS_DISABLED,
                fallback_reason=LLM_DISABLED,
                extra=prompt_trace,
            )
        try:
            response = await self.llm_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": self.prompt_loader.render_scene_system(str(LLMScene.QUERY_REWRITE)),
                    },
                    {
                        "role": "user",
                        "content": self.prompt_loader.render_scene_user(
                            str(LLMScene.QUERY_REWRITE),
                            original_query=original_query,
                            current_entities=current_bag.to_compact_dict(),
                            conversation_window=window.model_dump(),
                        ),
                    },
                ],
                tools=None,
                scene=LLMScene.QUERY_REWRITE,
                request_id=request_id,
                trace_id=trace_id,
                session_key=session_key,
            )
        except Exception as exc:
            return None, LLMAttempt(
                llm_status=LLM_STATUS_PROVIDER_ERROR,
                fallback_reason=LLM_PROVIDER_ERROR,
                detail=str(exc),
                extra=prompt_trace,
            )
        if response.finish_reason == "error" or response.error:
            return None, LLMAttempt(
                llm_status=LLM_STATUS_PROVIDER_ERROR,
                fallback_reason=LLM_PROVIDER_ERROR,
                detail=response.error or "llm_error",
                extra={
                    **prompt_trace,
                    "finish_reason": response.finish_reason,
                    "model": response.model,
                },
            )
        parsed = parse_llm_json_schema(response.content, QueryRewriteLLMOutput)
        parse_trace = {
            **prompt_trace,
            "finish_reason": response.finish_reason,
            "model": response.model,
            "parse_status": parsed.parse_status,
            "schema_status": "valid" if parsed.success else "invalid",
            "schema_name": parsed.schema_name,
        }
        if not parsed.success:
            return None, LLMAttempt(
                llm_status=LLM_STATUS_PARSE_FAILED
                if parsed.error_code == LLM_JSON_PARSE_FAILED
                else LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=LLM_JSON_PARSE_FAILED
                if parsed.error_code == LLM_JSON_PARSE_FAILED
                else LLM_SCHEMA_VALIDATION_FAILED,
                detail=parsed.error_detail,
                extra=parse_trace,
            )
        output = parsed.data
        if not isinstance(output, QueryRewriteLLMOutput):
            return None, LLMAttempt(
                llm_status=LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=LLM_SCHEMA_VALIDATION_FAILED,
                detail="schema result type mismatch",
                extra=parse_trace,
            )
        rewritten_query = output.rewritten_query or original_query
        # 明确表示从历史上下文继承过来的，不是当前用户明确输入的
        inherited_bag = self._inherited_bag_from_compact(output.inherited_entities)

        llm_bag = self._llm_candidate_bag_from_compact(
            output.entities,
            current_bag=current_bag,
            inherited_bag=inherited_bag,
        )
        candidate_bag = EntityBag().merge(inherited_bag).merge(llm_bag)

        # LLM 输出 entities 和 inherited_entities，代码将其转换为 llm_bag 和 inherited_bag，
        # 最后以 current_bag 为 base，经 EntityResolver 统一规范化、去重、择优和冲突判断，得到最终 canonical entity_bag
        resolution = self.entity_resolver.resolve(
            base_bag=current_bag,
            candidate_bag=candidate_bag,
            stage="query_rewrite_llm",
            parallel_current_entity_types=parallel_current_entity_types,
        )
        request_bag = resolution.entity_bag
        return QueryRewriteResult(
            original_query=original_query,
            rewritten_query=rewritten_query,
            is_follow_up=output.is_follow_up,
            rewrite_type=output.rewrite_type,
            entities=request_bag.to_compact_dict(),
            inherited_entities=self.entity_resolver.normalize_bag(inherited_bag, stage="query_rewrite_llm_inherited").to_compact_dict(),
            missing_required_entities=[str(item) for item in output.missing_required_entities],
            need_clarification=output.need_clarification or resolution.need_clarification,
            clarification_question=output.clarification_question or resolution.clarification_question,
            confidence=output.confidence,
            reason=output.reason,
            entity_bag=request_bag.model_dump(),
            conversation_window=window.model_dump(),
            llm_status=LLM_STATUS_SUCCESS,
            fallback_used=False,
            fallback_source=None,
            fallback_reason=None,
            decision_trace={
                "source": "query_rewrite",
                "method": "llm_json",
                **self.context_reference_policy.trace(),
                "llm_status": LLM_STATUS_SUCCESS,
                "entity_conflicts": [conflict.__dict__ for conflict in resolution.conflicts],
                **parse_trace,
            },
        ), LLMAttempt(
            llm_status=LLM_STATUS_SUCCESS,
            extra=parse_trace,
        )

    def _rewrite_with_rules(
        self,
        original_query: str,
        current_bag: EntityBag,
        history_bag: EntityBag,
        window: ConversationWindow,
        llm_attempt: LLMAttempt,
        parallel_current_entity_types: set[str],
    ) -> QueryRewriteResult:
        """
        规则兜底改写路径不是通用语义理解，而是可预测的上下文拼装。

        1. 若上一轮 assistant 正在等待澄清，则把本轮视为补参；
            继承上一任务已有实体，合并本轮实体，并检查剩余必填实体。
        2. 否则根据“继续、上一轮、第二个”等引用信号判断是否追问；
            只有历史中存在唯一高置信候选时才允许继承，多候选时要求澄清。
        3. 当前轮出现强锚点时默认视为新请求，避免误继承旧任务实体。
        4. 对 request_id + error_code 等已知确定场景生成标准排查语句；
            普通追问则拼接上一轮业务背景、回答摘要、当前追问和已知实体。

        因此，规则路径可以稳定处理已配置实体和明确引用关系，
        但不会识别 YAML 未定义的全新语义实体。
        """
        pending_clarification = self._detect_pending_clarification(window.recent_turns)
        reference = self._detect_context_reference(original_query, current_bag, pending_clarification)
        is_follow_up = reference.turn_type in {"clarification_reply", "follow_up_question"}
        inherited_bag = EntityBag()
        need_clarification = False
        clarification_question: str | None = None
        missing_required_entities: list[str] = []

        if pending_clarification is not None:
            inherited_bag = self._inherit_pending_clarification_entities(
                current_bag=current_bag,
                pending_metadata=pending_clarification,
            )
            resolution = self.entity_resolver.resolve(
                base_bag=inherited_bag,
                candidate_bag=current_bag,
                stage="query_rewrite_pending_clarification",
                parallel_current_entity_types=parallel_current_entity_types,
            )
            effective_bag = resolution.entity_bag
            missing_required_entities = self._remaining_required_entities(
                pending_clarification.get("missing_required_entities"),
                effective_bag,
            )
            if missing_required_entities:
                need_clarification = True
                clarification_question = self._missing_required_question(missing_required_entities)
            elif resolution.need_clarification:
                need_clarification = True
                clarification_question = resolution.clarification_question
        else:
            inherited_bag, clarification_question = self._inherit_context_entities(
                current_bag=current_bag,
                history_bag=history_bag,
                reference=reference,
            )
            need_clarification = clarification_question is not None
            resolution = self.entity_resolver.resolve(
                base_bag=inherited_bag,
                candidate_bag=current_bag,
                stage="query_rewrite_rule",
                parallel_current_entity_types=parallel_current_entity_types,
            )
            effective_bag = resolution.entity_bag
            if resolution.need_clarification and not need_clarification:
                need_clarification = True
                clarification_question = resolution.clarification_question

        entities = effective_bag.to_compact_dict()
        rewrite_type = self._rewrite_type(reference, need_clarification)
        if reference.turn_type == "clarification_reply":
            rewritten_query = self._build_clarification_reply_query(
                original_query=original_query,
                current_entities=current_bag.to_compact_dict(),
                entities=entities,
                pending_metadata=pending_clarification or {},
            )
        else:
            rewritten_query = self._build_rewritten_query(original_query, entities, is_follow_up, window)

        return QueryRewriteResult(
            original_query=original_query,
            rewritten_query=rewritten_query,
            is_follow_up=is_follow_up,
            rewrite_type=rewrite_type,
            entities=entities,
            inherited_entities=inherited_bag.to_compact_dict(),
            missing_required_entities=missing_required_entities,
            need_clarification=need_clarification,
            clarification_question=clarification_question,
            confidence=0.82 if not need_clarification else 0.4,
            reason="entity_bag_rule_rewrite",
            entity_bag=effective_bag.model_dump(),
            conversation_window=window.model_dump(),
            llm_status=llm_attempt.llm_status,
            fallback_used=True,
            fallback_source="query_rewrite",
            fallback_reason=llm_attempt.fallback_reason or LLM_DISABLED,
            decision_trace={
                "source": "query_rewrite",
                "method": "rule_fallback",
                **self.context_reference_policy.trace(),
                "reference_reason": reference.reason,
                "turn_type": reference.turn_type,
                "entity_conflicts": [conflict.__dict__ for conflict in resolution.conflicts],
                **llm_attempt.trace(source="query_rewrite"),
            },
        )

    def _detect_context_reference(
        self,
        query: str,
        current_bag: EntityBag,
        pending_clarification: dict[str, Any] | None = None,
    ) -> ContextReferenceResult:
        """判断当前轮是否需要引用历史上下文。

        会触发继承的典型场景：
        1. 澄清补参：上一轮 assistant metadata.need_clarification=true，
           例如上一轮问“还缺少保全项”，本轮用户只答“001028”。
        2. 显式追问：用户说“这个、刚才、继续、上一轮、第二个”等，
           例如“那这个一般是谁的问题？”需要继承上一轮 REQ_001/E102。
        3. 弱追问且无强锚点：用户说“为什么、怎么办、状态呢”，且本轮没有
           policy_no/apply_seq/request_id 等新强锚点。
        4. 短句无锚点：例如“状态呢？”、“继续看”，且本轮没有新实体。

        不触发继承的典型场景：
        1. 当前轮出现新的强锚点，例如“保单 9200100000458847 查一下”，默认新请求；
        2. 历史有多个候选但用户没有序号或明确指代，例如“继续查一下”，后续转澄清。
        """
        if pending_clarification is not None:
            return ContextReferenceResult(
                is_reference=True,
                reason="pending_clarification",
                turn_type="clarification_reply",
            )
        target_index, target_hint = self.context_reference_policy.ordinal_target(query)
        if target_index is not None:
            return ContextReferenceResult(
                is_reference=True,
                reason="ordinal_reference",
                turn_type="follow_up_question",
                target_index=target_index,
                target_hint=target_hint,
            )
        if self.context_reference_policy.has_explicit_reference(query):
            return ContextReferenceResult(is_reference=True, reason="explicit_reference", turn_type="follow_up_question")
        has_strong_anchor = self.context_reference_policy.has_strong_anchor(current_bag)
        if self.context_reference_policy.has_weak_follow_up(query) and not has_strong_anchor:
            return ContextReferenceResult(is_reference=True, reason="weak_follow_up", turn_type="follow_up_question")
        if self.context_reference_policy.is_short_query_without_anchor(query, current_bag):
            return ContextReferenceResult(is_reference=True, reason="short_query_without_anchor", turn_type="follow_up_question")
        if has_strong_anchor:
            return ContextReferenceResult(is_reference=False, reason="new_anchor_present", turn_type="new_request")
        return ContextReferenceResult(is_reference=False, reason="standalone_or_unknown", turn_type="direct_standalone")

    def _parallel_current_entity_types(self, bag: EntityBag) -> set[str]:
        """识别本轮明确给出的同类多值，供 Resolver 保留为并行查询集合。"""
        return {
            self.entity_resolver.canonical_type(entity_type)
            for entity_type in bag.entities
            if len(bag.get_values(entity_type)) > 1
        }

    @staticmethod
    def _detect_pending_clarification(recent_messages: list[dict[str, Any]] | None) -> dict[str, Any] | None:
        # 澄清状态来自上一轮 assistant message 的 metadata，而不是模型隐式记忆。
        # 这样无状态 Agent 在下一轮也能判断“用户是在补缺失实体”。
        for turn in reversed(recent_messages or []):
            if turn.get("role") != "assistant":
                continue
            metadata = turn.get("metadata") if isinstance(turn.get("metadata"), dict) else {}
            return metadata if metadata.get("need_clarification") else None
        return None

    def _inherit_pending_clarification_entities(
        self,
        *,
        current_bag: EntityBag,
        pending_metadata: dict[str, Any],
    ) -> EntityBag:
        """继承上一轮澄清等待中的任务实体。

        案例：
        - 上一轮用户：“保单 9200100000458846 保全任务完成后没更新”
        - Agent：“还缺少保全项 endorseType，请补充”
        - 本轮用户：“001028”
        此时继承上一轮 policy_no，把本轮 endorseType 作为当前实体，形成完整任务。

        如果本轮用户明确给了同类型实体，例如“不是 9200100000458846，是
        9200100000458847”，当前轮实体优先，不继承旧值。
        """
        previous_bag = EntityBag.from_compact_dict(
            self._compact_dict(pending_metadata.get("entities")),
            source="recent_turn",
            confidence=0.9,
        )
        inherited = EntityBag()
        current_types = set(current_bag.entities)
        # 当前轮用户补充的实体优先级更高，不能被上一轮 pending metadata 覆盖。
        for entity_type in sorted(previous_bag.entities):
            if entity_type in current_types:
                continue
            best = previous_bag.get_best(entity_type)
            if best:
                inherited.add(self._as_inherited(best))
        return inherited

    def _inherit_context_entities(
        self,
        *,
        current_bag: EntityBag,
        history_bag: EntityBag,
        reference: ContextReferenceResult,
    ) -> tuple[EntityBag, str | None]:
        """根据追问信号从历史中继承实体。

        案例 A，唯一高置信历史实体可继承：
        - 上一轮：“REQ_001 为什么返回 E102？”
        - 本轮：“那这个一般是谁的问题？”
        继承 request_id=REQ_001、error_code=E102。

        案例 B，序号引用可在多候选中选择：
        - 历史有“第一个保单 9200100000458846”和“第二个保单 9200100000458847”
        - 本轮：“第二个保单的受理号 930010412672222 查一下”
        根据“第二个”继承 policy_no=9200100000458847。

        案例 C，多候选且无明确指代必须澄清：
        - 历史有两个 policy_no
        - 本轮：“继续查一下”
        不能静默选择，返回澄清问题。

        案例 D，当前轮已有同类型强锚点时不继承历史同类型实体：
        - 历史 policy_no=9200100000458846
        - 本轮：“保单 9200100000458847 查一下”
        当前轮保单优先，旧保单不继承。
        """
        inherited = EntityBag()
        if not reference.is_reference:
            return inherited, None
        if not history_bag.to_compact_dict():
            return inherited, "请补充要处理的保单号、理赔号、请求流水号或错误码。"

        current_types = set(current_bag.entities)
        for entity_type in sorted(history_bag.entities):
            if entity_type in current_types:
                continue
            values = history_bag.get_values(entity_type)
            # 历史实体只有唯一且高置信时才能自动继承；多候选必须由用户澄清，
            # 避免把上一轮另一个保单号误带入当前工具调用。
            if len(values) == 1 and history_bag.has_unique_high_confidence(entity_type):
                best = history_bag.get_best(entity_type)
                if best:
                    inherited.add(self._as_inherited(best))
                continue
            if len(values) > 1:
                selected = self._select_ordinal_mention(history_bag, entity_type, reference.target_index)
                if selected is not None:
                    inherited.add(self._as_inherited(selected))
                    continue
                return inherited, f"上下文里有多个 {entity_type}，请明确你要继续处理哪一个。"

        if not inherited.to_compact_dict() and not current_bag.to_compact_dict():
            return inherited, "请补充要处理的保单号、理赔号、请求流水号或错误码。"
        return inherited, None

    @staticmethod
    def _as_inherited(entity: EntityMention) -> EntityMention:
        return EntityMention(
            type=entity.type,
            value=entity.value,
            normalized_value=entity.normalized_value,
            confidence=entity.confidence,
            source=entity.source,
            turn_id=entity.turn_id,
            sensitive=entity.sensitive,
            metadata={**entity.metadata, "inherited": True},
        )

    @staticmethod
    def _select_ordinal_mention(history_bag: EntityBag, entity_type: str, target_index: int | None) -> EntityMention | None:
        if target_index is None:
            return None
        values = history_bag.get_values(entity_type)
        if target_index < 0 or target_index >= len(values):
            return None
        target_value = values[target_index]
        for mention in history_bag.entities.get(entity_type) or []:
            if mention.effective_value == target_value:
                return mention
        return None

    def _remaining_required_entities(self, raw_required: Any, bag: EntityBag) -> list[str]:
        return self.context_reference_policy.remaining_required_entities(raw_required, bag)

    @staticmethod
    def _missing_required_question(missing: list[str]) -> str:
        display = "、".join(missing)
        return f"还缺少 {display}，请补充后我再继续处理。"

    @staticmethod
    def _rewrite_type(reference: ContextReferenceResult, need_clarification: bool) -> RewriteType:
        if need_clarification:
            return RewriteType.CLARIFICATION_REQUIRED
        if reference.turn_type == "clarification_reply":
            """表示上一轮 assistant 明确在等用户补实体，本轮用户是在回答这个澄清问题。"""
            return RewriteType.CLARIFICATION_REPLY
        if reference.turn_type == "follow_up_question":
            """表示普通追问，需要沿用上一轮上下文，但不是补缺失实体。"""
            return RewriteType.CONTEXTUAL_FOLLOW_UP
        if reference.turn_type == "new_request":
            """表示当前轮出现了新的强锚点，默认开启一个新请求帧，不继承历史实体。"""
            return RewriteType.NEW_REQUEST
        return RewriteType.DIRECT

    @staticmethod
    def _build_rewritten_query(
        query: str,
        entities: dict[str, Any],
        is_follow_up: bool,
        window: ConversationWindow,
    ) -> str:
        request_id = entities.get("request_id")
        error_code = entities.get("error_code")
        if is_follow_up and request_id and error_code:
            return QueryRewriteNode._build_follow_up_query(
                current_query=query,
                business_context=f"继续排查上一轮 requestId={request_id} 的 {error_code} 签名校验失败问题",
                entities=entities,
                window=window,
            )
        if request_id and error_code:
            return f"排查 requestId={request_id} 的健康险个险接口 {error_code} 错误原因"
        if is_follow_up and error_code:
            return QueryRewriteNode._build_follow_up_query(
                current_query=query,
                business_context=f"继续排查上一轮 {error_code} 签名校验失败问题",
                entities=entities,
                window=window,
            )
        if is_follow_up and entities:
            return QueryRewriteNode._build_follow_up_query(
                current_query=query,
                business_context=QueryRewriteNode._latest_user_context(window),
                entities=entities,
                window=window,
            )
        return query

    @staticmethod
    def _build_follow_up_query(
        *,
        current_query: str,
        business_context: str | None,
        entities: dict[str, Any],
        window: ConversationWindow,
    ) -> str:
        parts = ["基于上一轮业务上下文继续追问。"]
        if business_context:
            parts.append(f"上一轮问题背景：{business_context}。")
        answer_summary = QueryRewriteNode._latest_assistant_summary(window)
        if answer_summary:
            parts.append(f"上一轮回答摘要：{answer_summary}。")
        parts.append(f"当前追问：{current_query}。")
        entity_text = QueryRewriteNode._format_entities(entities)
        if entity_text:
            parts.append(f"已知实体：{entity_text}。")
        return "".join(parts)

    @staticmethod
    def _build_clarification_reply_query(
        *,
        original_query: str,
        current_entities: dict[str, Any],
        entities: dict[str, Any],
        pending_metadata: dict[str, Any],
    ) -> str:
        previous_query = str(
            pending_metadata.get("pending_task_query")
            or pending_metadata.get("rewritten_query")
            or pending_metadata.get("original_query")
            or ""
        ).strip()
        supplement = current_entities or {"user_reply": original_query}
        supplement_text = QueryRewriteNode._format_entities(supplement)
        entity_text = QueryRewriteNode._format_entities(entities)
        if not previous_query:
            if entity_text:
                return f"根据上下文继续处理当前澄清补参。已知实体：{entity_text}。当前用户补充：{supplement_text}。"
            return original_query
        parts = [f"继续处理上一轮业务问题：{previous_query}。"]
        if entity_text:
            parts.append(f"已知实体：{entity_text}。")
        if supplement_text:
            parts.append(f"当前用户补充：{supplement_text}。")
        return "".join(parts)

    @staticmethod
    def _latest_user_context(window: ConversationWindow) -> str | None:
        for turn in reversed(window.recent_turns or []):
            if turn.get("role") != "user":
                continue
            content = str(turn.get("content") or "").strip()
            if content:
                return QueryRewriteNode._compact_text(content)
        return QueryRewriteNode._compact_text(window.summary or "") or None

    @staticmethod
    def _latest_assistant_summary(window: ConversationWindow) -> str | None:
        for turn in reversed(window.recent_turns or []):
            if turn.get("role") != "assistant":
                continue
            metadata = turn.get("metadata") if isinstance(turn.get("metadata"), dict) else {}
            if metadata.get("need_clarification"):
                continue
            content = str(turn.get("content") or "").strip()
            if content:
                return QueryRewriteNode._compact_text(QueryRewriteNode._first_sentence(content), limit=140)
        return None

    @staticmethod
    def _format_entities(entities: dict[str, Any]) -> str:
        return "，".join(f"{key}={value}" for key, value in sorted(entities.items()) if value not in (None, "", []))

    @staticmethod
    def _compact_text(text: str, limit: int = 160) -> str:
        normalized = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit]}..."

    @staticmethod
    def _first_sentence(text: str) -> str:
        normalized = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
        for delimiter in ("。", "！", "？", ". ", "! ", "? "):
            index = normalized.find(delimiter)
            if index >= 0:
                end = index + len(delimiter.rstrip())
                return normalized[:end]
        return normalized

    @staticmethod
    def _compact_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _inherited_bag_from_compact(self, value: Any) -> EntityBag:
        bag = EntityBag.from_compact_dict(self._compact_dict(value), source="recent_turn", confidence=0.9)
        inherited = EntityBag()
        for mentions in bag.entities.values():
            for mention in mentions:
                inherited.add(self._as_inherited(mention))
        return inherited

    def _llm_candidate_bag_from_compact(
        self,
        value: Any,
        *,
        current_bag: EntityBag,
        inherited_bag: EntityBag,
    ) -> EntityBag:
        """把 LLM 的 entities 解释为“当前轮候选”，并过滤继承实体 echo。

        提示词已经要求 inherited_entities 与 entities 分离，但真实模型可能仍会把
        历史继承值放进 entities。这里在代码层收紧边界：
        - 与当前轮确定性实体完全重复的值丢弃，避免无意义重复；
        - 与继承实体完全重复的值丢弃，保留 inherited metadata；
        - 若某类型已经由 inherited_entities 提供且当前轮没有该类型，则丢弃同类型
          LLM 候选，避免 LLM 用 final-entities echo 覆盖历史继承来源。
        """
        raw_bag = EntityBag.from_compact_dict(self._compact_dict(value), source="llm", confidence=0.85)
        normalized_llm = self.entity_resolver.normalize_bag(raw_bag, stage="query_rewrite_llm_candidate")
        normalized_current = self.entity_resolver.normalize_bag(current_bag, stage="query_rewrite_llm_current")
        normalized_inherited = self.entity_resolver.normalize_bag(inherited_bag, stage="query_rewrite_llm_inherited_filter")
        excluded_values = self._entity_value_keys(normalized_current) | self._entity_value_keys(normalized_inherited)
        inherited_types = set(normalized_inherited.entities)
        current_types = set(normalized_current.entities)
        filtered = EntityBag()
        for mentions in normalized_llm.entities.values():
            for mention in mentions:
                key = (mention.type, mention.effective_value)
                if key in excluded_values:
                    continue
                if mention.type in inherited_types and mention.type not in current_types:
                    continue
                filtered.add(mention)
        return filtered

    @staticmethod
    def _entity_value_keys(bag: EntityBag) -> set[tuple[str, str]]:
        return {
            (entity_type, mention.effective_value)
            for entity_type, mentions in bag.entities.items()
            for mention in mentions
        }

    def _should_use_llm_json(self) -> bool:
        if self.llm_provider is None:
            return False
        # 内部 InternalLLMProvider，需要有 base_url
        if self.llm_provider.__class__.__name__ == "InternalLLMProvider" and not getattr(self.llm_provider, "base_url", None):
            return False
        return True
