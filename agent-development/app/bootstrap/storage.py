from __future__ import annotations

"""Storage dependency bootstrap."""

from dataclasses import dataclass
from pathlib import Path

from app.approval.store import SQLiteApprovalStore
from app.config.settings import Settings
from app.evidence.store import EvidenceStore
from app.runtime.checkpoint import SQLiteCheckpointStore
from app.session.message_store import MessageStore
from app.storage.sqlite import SQLiteDatabase
from app.tools.tool_execution_log_store import ToolExecutionLogStore


@dataclass(slots=True)
class StorageBundle:
    db: SQLiteDatabase
    message_store: MessageStore
    checkpoint_store: SQLiteCheckpointStore
    tool_execution_log_store: ToolExecutionLogStore
    evidence_store: EvidenceStore
    approval_store: SQLiteApprovalStore


def build_storage(settings: Settings, sqlite_db_path: str | Path | None = None) -> StorageBundle:
    db = SQLiteDatabase(sqlite_db_path or settings.sqlite_db_path)
    return StorageBundle(
        db=db,
        message_store=MessageStore(db=db),
        checkpoint_store=SQLiteCheckpointStore(db=db),
        tool_execution_log_store=ToolExecutionLogStore(db=db),
        evidence_store=EvidenceStore(db=db),
        approval_store=SQLiteApprovalStore(db=db),
    )
