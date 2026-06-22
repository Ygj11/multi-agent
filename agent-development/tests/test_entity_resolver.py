from app.query.entity_resolver import EntityResolver, build_entity_state_updates
from app.schemas.entities import EntityBag, EntityMention


def _bag(*mentions: EntityMention) -> EntityBag:
    bag = EntityBag()
    for mention in mentions:
        bag.add(mention)
    return bag


def _mention(entity_type: str, value: str, *, source: str, confidence: float = 0.95, **metadata) -> EntityMention:
    return EntityMention(
        type=entity_type,
        value=value,
        normalized_value=value,
        source=source,
        confidence=confidence,
        metadata=metadata,
    )


def test_current_deterministic_entity_is_not_overwritten_by_llm_entity():
    resolver = EntityResolver()
    result = resolver.resolve(
        base_bag=_bag(_mention("policy_no", "9200100000458846", source="current_query")),
        candidate_bag=_bag(_mention("policyNo", "9200100000458847", source="llm", confidence=0.85)),
        stage="test",
    )

    assert result.entity_bag.to_compact_dict()["policy_no"] == "9200100000458846"
    assert result.need_clarification is False


def test_current_entity_overrides_historical_entity():
    resolver = EntityResolver()
    result = resolver.resolve(
        base_bag=_bag(_mention("policy_no", "9200100000458846", source="recent_turn")),
        candidate_bag=_bag(_mention("policy_no", "9200100000458847", source="current_query")),
        stage="test",
    )

    assert result.entity_bag.to_compact_dict()["policy_no"] == "9200100000458847"


def test_current_correction_uses_new_value_over_history():
    resolver = EntityResolver()
    result = resolver.resolve(
        base_bag=_bag(_mention("policy_no", "9200100000458846", source="recent_turn")),
        candidate_bag=_bag(_mention("policy_no", "9200100000458847", source="current_query", correction=True)),
        stage="test",
    )

    assert result.entity_bag.to_compact_dict()["policy_no"] == "9200100000458847"
    selected = result.entity_bag.get_best("policy_no")
    assert selected is not None
    assert selected.metadata["correction"] is True


def test_llm_can_supplement_missing_semantic_entity():
    resolver = EntityResolver()
    result = resolver.resolve(
        base_bag=_bag(_mention("policy_no", "9200100000458846", source="current_query")),
        candidate_bag=_bag(_mention("document_type", "保全批文", source="llm", confidence=0.85)),
        stage="test",
    )

    assert result.entity_bag.to_compact_dict() == {
        "document_type": "保全批文",
        "policy_no": "9200100000458846",
    }


def test_recent_unique_high_confidence_entity_can_be_inherited():
    resolver = EntityResolver()
    result = resolver.resolve(
        base_bag=EntityBag(),
        candidate_bag=_bag(_mention("policy_no", "9200100000458846", source="recent_turn", inherited=True)),
        stage="test",
    )

    assert result.entity_bag.to_compact_dict()["policy_no"] == "9200100000458846"
    selected = result.entity_bag.get_best("policy_no")
    assert selected is not None
    assert selected.metadata["inherited"] is True


def test_multiple_same_priority_historical_candidates_need_clarification():
    resolver = EntityResolver()
    result = resolver.resolve(
        base_bag=EntityBag(),
        candidate_bag=_bag(
            _mention("policy_no", "9200100000458846", source="recent_turn"),
            _mention("policy_no", "9200100000458847", source="recent_turn"),
        ),
        stage="test",
    )

    assert result.need_clarification is True
    assert result.conflicts[0].entity_type == "policy_no"
    assert sorted(result.entity_bag.to_compact_dict()["policy_no"]) == ["9200100000458846", "9200100000458847"]


def test_summary_entity_does_not_override_recent_or_current_entity():
    resolver = EntityResolver()
    result = resolver.resolve(
        base_bag=_bag(_mention("policy_no", "9200100000458846", source="summary")),
        candidate_bag=_bag(_mention("policy_no", "9200100000458847", source="recent_turn")),
        stage="test",
    )

    assert result.entity_bag.to_compact_dict()["policy_no"] == "9200100000458847"

    result = resolver.resolve(
        base_bag=result.entity_bag,
        candidate_bag=_bag(_mention("policy_no", "9200100000458848", source="current_query")),
        stage="test",
    )

    assert result.entity_bag.to_compact_dict()["policy_no"] == "9200100000458848"


def test_invalid_or_low_confidence_llm_entity_does_not_pollute_canonical_bag():
    resolver = EntityResolver()
    invalid = resolver.resolve(
        base_bag=EntityBag(),
        candidate_bag=_bag(_mention("policy_no", "123", source="llm", confidence=0.85)),
        stage="test",
    )
    low_confidence = resolver.resolve(
        base_bag=EntityBag(),
        candidate_bag=_bag(_mention("document_type", "批文", source="llm", confidence=0.2)),
        stage="test",
    )

    assert invalid.entity_bag.to_compact_dict() == {}
    assert low_confidence.entity_bag.to_compact_dict() == {}


def test_aliases_are_canonicalized_to_internal_keys():
    resolver = EntityResolver()
    result = resolver.resolve(
        base_bag=EntityBag(),
        candidate_bag=_bag(
            _mention("policyNo", "9200100000458846", source="current_query"),
            _mention("applySeq", "930010412672222", source="current_query"),
            _mention("requestId", "req-20240501-0001", source="current_query"),
        ),
        stage="test",
    )

    assert result.entity_bag.to_compact_dict() == {
        "apply_seq": "930010412672222",
        "policy_no": "9200100000458846",
        "request_id": "REQ-20240501-0001",
    }


def test_build_entity_state_updates_projects_compact_entities_from_bag():
    bag = _bag(_mention("policyNo", "9200100000458846", source="current_query"))

    updates = build_entity_state_updates(bag)

    assert updates["entities"] == EntityBag(**updates["entity_bag"]).to_compact_dict()
    assert updates["entities"] == {"policy_no": "9200100000458846"}
