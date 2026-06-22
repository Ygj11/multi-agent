from __future__ import annotations

"""统一结构化运行时日志。"""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any


LOGGER_NAME = "agent_runtime"
SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "authorization",
    "id_card",
    "phone",
    "mobile",
    "bank_card",
    "health_info",
    "medical_record",
    "policy_no",
    "policyno",
    "apply_seq",
    "id_no",
    "identity_no",
}

PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<!\d)920\d{13}(?!\d)", re.IGNORECASE), "920*************"),
    (re.compile(r"(?<!\d)930\d{12}(?!\d)", re.IGNORECASE), "930************"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "1**********"),
    (re.compile(r"(?<![A-Za-z0-9])\d{6}(?:19|20)\d{2}\d{2}\d{2}\d{3}[\dXx](?![A-Za-z0-9])"), "****** ******** ****"),
)


def get_runtime_logger() -> logging.Logger:
    """获取运行时 logger。"""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = True
    return logger


def log_event(
    event: str,
    *,
    level: str = "INFO",
    request_id: str | None = None,
    trace_id: str | None = None,
    session_key: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    node: str | None = None,
    message: str = "",
    data: dict[str, Any] | None = None,
) -> None:
    """输出一条 JSON line 风格的运行时事件日志。"""
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level.upper(),
        "event": event,
        "request_id": request_id,
        "trace_id": trace_id,
        "session_key": session_key,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "node": node,
        "message": message,
        "data": sanitize_data(data or {}),
    }
    text = json.dumps(payload, ensure_ascii=False, default=str)
    logger = get_runtime_logger()
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(log_level, text)


def sanitize_data(data: Any) -> Any:
    """递归脱敏并截断日志 data。"""
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            if str(key).lower() in SENSITIVE_KEYS:
                sanitized[key] = "***"
            else:
                sanitized[key] = sanitize_data(value)
        return sanitized
    if isinstance(data, list):
        return [sanitize_data(item) for item in data[:20]]
    if isinstance(data, str):
        return preview_text(data)
    if isinstance(data, (int, float, bool)) or data is None:
        return data
    return preview_text(str(data))


def preview_text(text: str, limit: int = 120) -> str:
    """生成适合日志输出的短文本预览。"""
    normalized = _mask_sensitive_text(text.replace("\r", " ").replace("\n", " ").strip())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _mask_sensitive_text(text: str) -> str:
    masked = text
    for pattern, replacement in PII_PATTERNS:
        masked = pattern.sub(replacement, masked)
    return masked
