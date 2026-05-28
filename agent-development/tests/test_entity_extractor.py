from app.query.entity_extractor import EntityExtractor, EntityPatternLoader


def test_entity_extractor_extracts_common_business_entities():
    bag = EntityExtractor().extract(
        "REQ_001 在 submitProposal 返回 E102，保单号 P2021344266，理赔 CLM_001，产品 PROD_ABC。"
    )
    compact = bag.to_compact_dict()

    assert compact["request_id"] == "REQ_001"
    assert compact["error_code"] == "E102"
    assert compact["interface_name"] == "submitProposal"
    assert compact["policy_no"] == "P2021344266"
    assert compact["claim_no"] == "CLM_001"
    assert compact["product_code"] == "PROD_ABC"


def test_entity_extractor_extracts_endo_aftercare_entities():
    bag = EntityExtractor().extract("保全任务完成了，受理号 APPLY_POLICY_UPDATE_FAIL，保单号 P001，保全项退保")
    compact = bag.to_compact_dict()

    assert compact["apply_seq"] == "APPLY_POLICY_UPDATE_FAIL"
    assert compact["policy_no"] == "P001"
    assert compact["endorseType"] == "退保"


def test_entity_extractor_marks_sensitive_entities():
    bag = EntityExtractor().extract("手机号13800138000，身份证110101199003074233")

    assert bag.get_best("phone_number").sensitive is True
    assert bag.get_best("id_card").sensitive is True
    assert "policy_no" not in bag.to_compact_dict()


def test_entity_extractor_empty_and_unknown_are_safe():
    bag = EntityExtractor().extract("没有任何结构化编号")

    assert bag.to_compact_dict() == {}


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
