from __future__ import annotations

"""Inspect stored checkpoint snapshot sizes.

This script is read-only. It reports the latest checkpoint snapshots and the
largest top-level fields inside each `snapshot_json` payload.
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit checkpoint snapshot sizes.")
    parser.add_argument("--db", default=".data/agent_mvp.sqlite3", help="SQLite database path.")
    parser.add_argument("--limit", type=int, default=5, help="Number of latest checkpoints to inspect.")
    parser.add_argument("--top-fields", type=int, default=10, help="Number of largest top-level fields to show.")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT thread_id, schema_version, snapshot_json, updated_at
            FROM graph_checkpoints
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()

    if not rows:
        print("No checkpoint snapshots found.")
        return

    for row in rows:
        payload = json.loads(row["snapshot_json"])
        size = len(row["snapshot_json"].encode("utf-8"))
        print(f"\nthread_id={row['thread_id']}")
        print(f"schema_version={row['schema_version']} updated_at={row['updated_at']} size_bytes={size}")
        print("largest_fields:")
        for name, field_size in _largest_fields(payload, args.top_fields):
            print(f"  {name}: {field_size} bytes")


def _largest_fields(payload: dict[str, Any], limit: int) -> list[tuple[str, int]]:
    fields = []
    for key, value in payload.items():
        encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        fields.append((key, len(encoded)))
    return sorted(fields, key=lambda item: item[1], reverse=True)[:limit]


if __name__ == "__main__":
    main()
