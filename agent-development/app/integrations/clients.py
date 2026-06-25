from __future__ import annotations

"""运行时真实领域 client 的只读依赖集合。"""

from dataclasses import dataclass

from app.integrations.pos_api_client import PosAPIClient
from app.integrations.troubleshooting_api_client import TroubleshootingAPIClient


@dataclass(frozen=True, slots=True)
class IntegrationClients:
    """由 Container 构建并注入工具注册层的真实领域 client 引用。

    该对象只固定 client 引用，不承担连接池关闭职责；生命周期仍归
    AppContainer 所有。新增领域 client 时在此处增加具名字段即可。
    """

    pos: PosAPIClient | None = None
    troubleshooting: TroubleshootingAPIClient | None = None
