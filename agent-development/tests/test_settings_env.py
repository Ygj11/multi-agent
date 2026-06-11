from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from app.config.settings import PROJECT_ROOT, get_settings


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


def test_get_settings_reads_dotenv_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "INTERNAL_LLM_MAX_TOKENS=4096",
                "ENABLE_REAL_LLM=true",
                "CHECKPOINT_BACKEND=sqlite",
                "STRICT_TAXONOMY_ROUTE_COVERAGE=false",
                "POS_TOOL_MODE=real",
                "TROUBLESHOOTING_TOOL_MODE=real",
                "TROUBLESHOOTING_API_BASE_URL=https://troubleshooting.example.test",
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


def test_os_environment_wins_over_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("INTERNAL_LLM_MAX_TOKENS=4096\n", encoding="utf-8")

    with patch.dict(os.environ, {"INTERNAL_LLM_MAX_TOKENS": "2048"}, clear=True):
        settings = get_settings(dotenv_path=env_file)

    assert settings.internal_llm_max_tokens == 2048


def test_dotenv_missing_field_uses_default(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ENABLE_REAL_LLM=true\n", encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True):
        settings = get_settings(dotenv_path=env_file)

    assert settings.enable_real_llm is True
    assert settings.internal_llm_max_tokens == 8192
