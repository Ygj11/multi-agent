from app.llm.tool_call_parser import extract_tool_arguments, extract_tool_name, normalize_tool_calls


def test_parse_openai_format_json_arguments():
    calls = [
        {
            "id": "call_xxx",
            "type": "function",
            "function": {"name": "query_task_status", "arguments": '{"policy_no":"9201344266"}'},
        }
    ]

    parsed = normalize_tool_calls(calls)

    assert parsed[0].id == "call_xxx"
    assert parsed[0].name == "query_task_status"
    assert parsed[0].arguments == {"policy_no": "9201344266"}
    assert parsed[0].error is None


def test_parse_internal_format_dict_arguments():
    calls = [{"name": "query_task_status", "arguments": {"policy_no": "9201344266"}}]

    parsed = normalize_tool_calls(calls)

    assert parsed[0].name == "query_task_status"
    assert parsed[0].arguments == {"policy_no": "9201344266"}


def test_invalid_arguments_returns_error():
    parsed = normalize_tool_calls([{"name": "query_task_status", "arguments": "{bad json"}])

    assert parsed[0].error.startswith("tool_arguments_invalid_json")


def test_missing_tool_name_returns_error():
    parsed = normalize_tool_calls([{"arguments": {}}])

    assert parsed[0].error == "tool_name_missing"


def test_extract_helpers_return_values():
    call = {"name": "query_task_status", "arguments": {"a": 1}}

    assert extract_tool_name(call) == "query_task_status"
    assert extract_tool_arguments(call) == {"a": 1}

