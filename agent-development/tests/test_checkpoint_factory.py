from app.config.settings import Settings
from app.runtime.checkpoint import build_checkpointer


def test_build_checkpointer_memory_backend():
    checkpointer = build_checkpointer(Settings(checkpoint_backend="memory"))

    assert type(checkpointer).__name__ == "InMemorySaver"


def test_build_checkpointer_sqlite_backend_falls_back_when_optional_package_missing():
    checkpointer = build_checkpointer(Settings(checkpoint_backend="sqlite", checkpoint_db_path="checkpoint.sqlite3"))

    assert checkpointer is not None
    assert hasattr(checkpointer, "get_tuple")
