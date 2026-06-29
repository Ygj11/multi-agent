from __future__ import annotations

from pydantic import BaseModel

from app.schemas.enums.base import DescribedStrEnum


class DemoStatus(DescribedStrEnum):
    READY = ("ready", "已经准备好，可以继续执行。")
    BLOCKED = ("blocked", "当前状态被阻断，需要人工处理。")


class DemoModel(BaseModel):
    status: DemoStatus


def test_described_str_enum_value_and_description():
    assert DemoStatus.READY.value == "ready"
    assert DemoStatus.READY.description == "已经准备好，可以继续执行。"
    assert str(DemoStatus.READY) == "ready"


def test_described_str_enum_restores_from_historical_value():
    assert DemoStatus("blocked") is DemoStatus.BLOCKED


def test_described_str_enum_serializes_as_machine_value_only():
    model = DemoModel(status=DemoStatus.READY)

    assert model.model_dump(mode="json") == {"status": "ready"}
    assert model.model_dump_json() == '{"status":"ready"}'
    assert "description" not in model.model_dump(mode="json")
    assert "已经准备好" not in model.model_dump_json()

