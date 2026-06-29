from __future__ import annotations

"""带开发说明的字符串枚举基础类。"""

from enum import StrEnum


class DescribedStrEnum(StrEnum):
    """同时保存稳定机器值和开发说明的字符串枚举。

    `value` 是系统运行、持久化和路由使用的唯一机器值；`description` 只给
    开发者、文档和调试阅读，不能作为业务判断依据，也不会进入 Pydantic
    `model_dump(mode="json")` 的实例数据。
    """

    description: str

    def __new__(cls, value: str, description: str):
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.description = description
        return obj

    def __str__(self) -> str:
        return self.value

