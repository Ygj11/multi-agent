from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config.settings import PROJECT_ROOT, Settings, describe_effective_switches, get_settings, validate_settings


def test_project_root_points_to_repo_root():
    assert PROJECT_ROOT == Path(__file__).resolve().parents[1]
    assert PROJECT_ROOT.name == "agent-development"


def test_get_settings_uses_defaults_without_env_file(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        settings = get_settings(dotenv_path=tmp_path / "missing.env")

    assert settings.internal_llm_max_tokens == 8192
    assert settings.enable_real_llm is False
    assert settings.checkpoint_backend == "memory"
    assert settings.strict_taxonomy_route_coverage is True
    assert settings.pos_tool_mode == "mock"
    assert settings.troubleshooting_tool_mode == "mock"
    assert settings.app_env == "local"
    assert settings.no_skill_policy == "clarify"


def test_get_settings_reads_dotenv_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "INTERNAL_LLM_MAX_TOKENS=4096",
                "ENABLE_REAL_LLM=true",
                "INTERNAL_LLM_API_URL=https://llm.example.test/chat",
                "CHECKPOINT_BACKEND=sqlite",
                "STRICT_TAXONOMY_ROUTE_COVERAGE=false",
                "POS_TOOL_MODE=real",
                "TROUBLESHOOTING_TOOL_MODE=real",
                "TROUBLESHOOTING_API_BASE_URL=https://troubleshooting.example.test",
                "APP_ENV=staging",
                "NO_SKILL_POLICY=answer_no_skill",
            ]
        ),
        encoding="utf-8",
    )

    with patch.dict(os.environ, {}, clear=True):
        settings = get_settings(dotenv_path=env_file)

    assert settings.internal_llm_max_tokens == 4096
    assert settings.enable_real_llm is True
    assert settings.checkpoint_backend == "sqlite"
    assert settings.strict_taxonomy_route_coverage is False
    assert settings.pos_tool_mode == "real"
    assert settings.troubleshooting_tool_mode == "real"
    assert settings.troubleshooting_api_base_url == "https://troubleshooting.example.test"
    assert settings.app_env == "staging"
    assert settings.no_skill_policy == "answer_no_skill"


def test_os_environment_wins_over_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("INTERNAL_LLM_MAX_TOKENS=4096\n", encoding="utf-8")

    with patch.dict(os.environ, {"INTERNAL_LLM_MAX_TOKENS": "2048"}, clear=True):
        settings = get_settings(dotenv_path=env_file)

    assert settings.internal_llm_max_tokens == 2048


def test_dotenv_missing_field_uses_default(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ENABLE_REAL_LLM=true\nINTERNAL_LLM_API_URL=https://llm.example.test/chat\n", encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True):
        settings = get_settings(dotenv_path=env_file)

    assert settings.enable_real_llm is True
    assert settings.internal_llm_max_tokens == 8192


def test_get_settings_rejects_opensdk_without_api_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ENABLE_OPENSDK_LLM=true\n", encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True), pytest.raises(ValueError, match="opensdk_api_key_missing"):
        get_settings(dotenv_path=env_file)


def test_get_settings_rejects_prod_body_identity_fallback(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=prod",
                "AUTH_MODE=required",
                "ALLOW_REQUEST_BODY_IDENTITY_FALLBACK=true",
            ]
        ),
        encoding="utf-8",
    )

    with patch.dict(os.environ, {}, clear=True), pytest.raises(ValueError, match="prod_body_identity_fallback_enabled"):
        get_settings(dotenv_path=env_file)


def test_task_completion_llm_requires_real_llm_provider():
    settings = Settings(
        enable_task_completion_verify=True,
        task_completion_enable_llm=True,
        enable_real_llm=False,
        enable_opensdk_llm=False,
        internal_llm_api_url=None,
    )

    issues = validate_settings(settings)

    assert any(issue.code == "task_completion_llm_without_provider" for issue in issues)


def test_task_completion_refresh_evidence_before_verify_setting(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TASK_COMPLETION_REFRESH_EVIDENCE_BEFORE_VERIFY=true\n", encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True):
        settings = get_settings(dotenv_path=env_file)

    assert settings.task_completion_refresh_evidence_before_verify is True


def test_effective_switches_explain_composed_configuration():
    settings = Settings(
        auth_mode="required",
        allow_request_body_identity_fallback=False,
        enable_opensdk_llm=True,
        openai_api_key="sk-test",
        enable_task_completion_verify=True,
        task_completion_enable_llm=True,
        enable_mcp_client=True,
        mcp_servers_json='{"workflow": {"transport": "http", "url": "https://mcp.example.test"}}',
    )

    switches = {item.name: item for item in describe_effective_switches(settings)}

    assert switches["trusted_auth_required"].enabled is True
    assert switches["real_llm"].enabled is True
    assert switches["task_completion_llm_verify"].enabled is True
    assert switches["mcp_dynamic_tools"].enabled is True
    assert switches["session_execution_lock"].enabled is True


def test_prod_decision_trace_metadata_is_warning_not_error():
    settings = Settings(
        app_env="prod",
        auth_mode="required",
        allow_request_body_identity_fallback=False,
        log_decision_trace_in_messages=True,
    )

    issues = validate_settings(settings)

    assert any(issue.code == "prod_decision_trace_persisted" and issue.level == "warning" for issue in issues)
    assert not [issue for issue in issues if issue.level == "error"]


def test_prod_rejects_disabled_session_execution_lock():
    settings = Settings(
        app_env="prod",
        auth_mode="required",
        allow_request_body_identity_fallback=False,
        enable_session_execution_lock=False,
    )

    issues = validate_settings(settings)

    assert any(issue.code == "prod_session_execution_lock_disabled" for issue in issues)


def test_session_lock_timeout_must_be_positive():
    settings = Settings(session_lock_timeout_seconds=0)

    issues = validate_settings(settings)

    assert any(issue.code == "session_lock_timeout_seconds_must_be_positive" for issue in issues)
