from __future__ import annotations

"""长期记忆接口预留。"""

from typing import Any


class LongTermMemoryManager:
    """第一阶段轻量实现，后续可接数据库和向量索引。"""

    async def retrieve(self, *args: Any, **kwargs: Any) -> list[Any]:
        """预留长期记忆检索接口，MVP 阶段返回空。"""
        return []

    async def extract_and_update(self, *args: Any, **kwargs: Any) -> None:
        """预留长期记忆抽取与更新接口，MVP 阶段不执行写入。"""
        return None
