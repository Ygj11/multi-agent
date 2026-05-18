from __future__ import annotations

"""QueryRewriteNode 的输入语义输出。"""

from pydantic import BaseModel


class QueryRewriteResult(BaseModel):
    """保留原始 query，同时提供标准化后的 rewritten_query。"""

    original_query: str
    rewritten_query: str
