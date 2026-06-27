from __future__ import annotations

from datetime import datetime

from app.utils.json_utils import parse_json_object, to_json


def test_parse_json_object_accepts_fenced_json():
    assert parse_json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_parse_json_object_extracts_object_from_text():
    assert parse_json_object('prefix {"answer": "done"} suffix') == {"answer": "done"}


def test_parse_json_object_rejects_non_object_json():
    assert parse_json_object("[1, 2, 3]") is None


def test_to_json_serializes_non_json_native_values():
    payload = to_json({"at": datetime(2026, 1, 2, 3, 4, 5)})

    assert '"2026-01-02 03:04:05"' in payload
