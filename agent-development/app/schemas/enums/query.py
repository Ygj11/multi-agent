from __future__ import annotations

"""Query Rewrite 阶段的稳定协议值。"""

from app.schemas.enums.base import DescribedStrEnum


class RewriteType(DescribedStrEnum):
    DIRECT = ("direct", "当前问题是独立请求，不需要依赖历史上下文。")
    CONTEXTUAL_FOLLOW_UP = ("contextual_follow_up", "当前问题是对上一轮业务结果的追问。")
    CLARIFICATION_REPLY = ("clarification_reply", "当前消息是在回答上一轮澄清问题。")
    NEW_REQUEST = ("new_request", "当前消息开启新的业务请求，不继承旧业务上下文。")
    CLARIFICATION_REQUIRED = ("clarification_required", "改写阶段无法安全消解上下文，需要先澄清。")
