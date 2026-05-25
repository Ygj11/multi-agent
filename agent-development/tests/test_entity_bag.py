from app.schemas.entities import EntityBag, EntityMention


def test_entity_bag_add_merge_get_best_values_and_compact_dict():
    bag = EntityBag()
    bag.add(EntityMention(type="policy_no", value="P100001", confidence=0.7, source="current_query"))
    other = EntityBag()
    other.add(EntityMention(type="policy_no", value="P100002", confidence=0.95, source="summary"))
    other.add(EntityMention(type="error_code", value="E102", confidence=0.9, source="current_query"))

    bag.merge(other)

    assert bag.get_best("policy_no").value == "P100002"
    assert bag.get_values("policy_no") == ["P100001", "P100002"]
    assert bag.to_compact_dict()["policy_no"] == ["P100001", "P100002"]
    assert bag.to_compact_dict()["error_code"] == "E102"
    assert bag.has_unique_high_confidence("error_code")
    assert not bag.has_unique_high_confidence("policy_no")


def test_entity_bag_from_compact_dict():
    bag = EntityBag.from_compact_dict({"claim_no": "CLM_001", "policy_no": ["P1", "P2"]})

    assert bag.get_values("claim_no") == ["CLM_001"]
    assert bag.get_values("policy_no") == ["P1", "P2"]
