import inspect
import re

from app.runtime.graph import AgentGraphFactory
from app.runtime.node_contracts import NODE_CONTRACTS, validate_node_contracts


def test_all_graph_nodes_have_contracts():
    source = inspect.getsource(AgentGraphFactory.build)
    graph_nodes = set(re.findall(r'graph\.add_node\("([^"]+)"', source))

    assert graph_nodes
    assert graph_nodes == set(NODE_CONTRACTS)


def test_node_contracts_reference_known_state_fields_and_failure_codes():
    assert validate_node_contracts() == []


def test_route_contracts_declare_graph_edge_values():
    assert NODE_CONTRACTS["route_entry"].routes == ["resume", "normal"]
    assert NODE_CONTRACTS["query_rewrite"].routes == ["clarify", "continue"]
    assert NODE_CONTRACTS["intent_recognition"].routes == ["clarify", "continue"]
    assert NODE_CONTRACTS["select_agent"].routes == ["clarify", "continue"]
    assert NODE_CONTRACTS["check_human_approval_required"].routes == ["required", "not_required", "skip_completion"]
    assert NODE_CONTRACTS["verify_task_completion"].routes == ["passed", "continue", "need_user", "handoff", "failed"]
    assert NODE_CONTRACTS["create_approval_request"].routes == ["submit", "manual"]
    assert NODE_CONTRACTS["pre_answer_verify"].routes == ["passed", "retry", "fallback"]
