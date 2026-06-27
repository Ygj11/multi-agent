from __future__ import annotations

"""通用 JSON 解析与序列化工具。"""

import json
import re
from typing import Any


def parse_json_object(text: str | None) -> dict[str, Any] | None:
    """从普通文本或 ```json fenced block 中解析 JSON object。

    LLM 输出经常带 Markdown fence 或解释性前后缀。本函数只返回 dict；
    非 JSON、数组、字符串等都返回 None，由上层决定 fallback。
    """
    if not text:
        return None
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    elif not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def to_json(value: Any) -> str:
    """安全序列化为 JSON 字符串。

    默认支持 datetime、Path 等非原生 JSON 对象；如果对象仍无法序列化，
    则退化为其字符串表示，避免持久化日志路径因为单个异常对象中断。
    """
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)
