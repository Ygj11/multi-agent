from app.query.context_reference_policy import QueryContextReferencePolicy
from app.query.query_rewrite_node import QueryRewriteNode


def test_context_reference_policy_loads_yaml_rules():
    policy = QueryContextReferencePolicy.load()

    assert policy.version == "1.0.0"
    assert policy.has_explicit_reference("继续这个问题")
    assert policy.ordinal_target("第二个继续处理") == (1, "第二个")
    assert policy.remaining_required_entities(["policyNo", "applySeq"], _Bag({"policy_no": "9200100000458846"})) == [
        "applySeq"
    ]


async def test_query_rewrite_uses_injected_context_reference_policy():
    policy = QueryContextReferencePolicy(
        version="test-policy",
        explicit_reference_signals=("承接",),
        weak_follow_up_signals=(),
        strong_anchor_entity_types=frozenset({"policy_no"}),
        entity_type_aliases={},
        ordinal_targets={},
        short_query_without_anchor_max_len=0,
    )
    node = QueryRewriteNode(llm_provider=None, context_reference_policy=policy)

    result = await node.rewrite(
        "承接处理一下",
        recent_messages=[
            {"role": "user", "content": "保单 9200100000458846 没更新", "metadata": {}},
            {"role": "assistant", "content": "请继续补充。", "metadata": {"need_clarification": False}},
        ],
    )

    assert result.is_follow_up is True
    assert result.inherited_entities["policy_no"] == "9200100000458846"
    assert result.decision_trace["policy_name"] == "query_context_reference_policy"
    assert result.decision_trace["policy_version"] == "test-policy"


class _Bag:
    def __init__(self, compact):
        self.compact = compact

    def to_compact_dict(self):
        return self.compact
