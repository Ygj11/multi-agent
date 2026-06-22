from app.query.entity_extractor import EntityExtractor, EntityPatternLoader


def test_entity_extractor_extracts_common_business_entities():
    bag = EntityExtractor().extract(
        "req_001 在 submitProposal 返回 E102，保单号 9200100000458846，理赔 CLM_001，产品 pmABC01，险种 h100。"
    )
    compact = bag.to_compact_dict()

    assert compact["request_id"] == "REQ_001"
    assert compact["error_code"] == "E102"
    assert "interface_name" not in compact
    assert compact["policy_no"] == "9200100000458846"
    assert compact["claim_no"] == "CLM_001"
    assert compact["product_code"] == "PMABC01"
    assert compact["plan_code"] == "H100"


def test_entity_extractor_extracts_endo_aftercare_entities():
    bag = EntityExtractor().extract("保全任务完成了，受理号 930010412672222，保单号 9200100000458846，保全项001028")
    compact = bag.to_compact_dict()

    assert compact["apply_seq"] == "930010412672222"
    assert compact["policy_no"] == "9200100000458846"
    assert compact["endorseType"] == "001028"


def test_apply_seq_is_not_misclassified_as_policy_no():
    compact = EntityExtractor().extract("受理号930010412672222查询批文").to_compact_dict()

    assert compact["apply_seq"] == "930010412672222"
    assert "policy_no" not in compact


def test_policy_no_requires_920_prefix_and_16_digits():
    compact = EntityExtractor().extract("930010412672222 9200100000458846 920010000045884").to_compact_dict()

    assert compact["policy_no"] == "9200100000458846"
    assert "apply_seq" in compact


def test_entity_extractor_marks_sensitive_entities():
    bag = EntityExtractor().extract("手机号13800138000，身份证110101199003074233")

    assert bag.get_best("phone_number").sensitive is True
    assert bag.get_best("id_card").sensitive is True
    assert "policy_no" not in bag.to_compact_dict()


def test_entity_extractor_empty_and_unknown_are_safe():
    bag = EntityExtractor().extract("没有任何结构化编号")

    assert bag.to_compact_dict() == {}


def test_entity_extractor_marks_correction_context_metadata():
    bag = EntityExtractor().extract("不是保单9200100000458846，是9200100000458847")
    mentions = bag.entities["policy_no"]

    assert mentions[0].metadata["negated"] is True
    assert mentions[1].metadata["correction"] is True


def test_entity_extractor_uses_yaml_rule_changes(tmp_path):
    path = tmp_path / "entity_patterns.yaml"
    path.write_text(
        """
version: "1.0.0"
patterns:
  - entity_type: hospital_name
    description: hospital
    regex:
      - "([\\u4e00-\\u9fa5]+医院)"
    normalized_type: string
    sensitive: false
    confidence: 0.88
""",
        encoding="utf-8",
    )

    extractor = EntityExtractor(patterns=EntityPatternLoader(path).load())
    assert extractor.extract("北京协和医院").to_compact_dict()["hospital_name"] == "北京协和医院"
