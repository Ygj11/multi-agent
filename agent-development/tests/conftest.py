"""pytest 共享 fixture。

所有集成测试都使用临时 SQLite 数据库，避免污染本地 .data/agent_mvp.sqlite3。
"""

from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app_factory(tmp_path: Path) -> Callable[[str], object]:
    """创建使用临时 SQLite 文件的 FastAPI app。"""

    def factory(name: str = "agent_test.sqlite3"):
        return create_app(sqlite_db_path=tmp_path / name)

    return factory


@pytest.fixture
def client(app_factory) -> TestClient:
    """创建使用临时 SQLite 数据库的 TestClient。"""
    return TestClient(app_factory())
