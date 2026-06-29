from __future__ import annotations

"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException

from app.auth.dependencies import get_current_principal
from app.auth.principal import Principal
from app.adapters.request_adapter import RequestAdapter
from app.adapters.response_adapter import ResponseAdapter
from app.bootstrap.container import build_app_container
from app.config.settings import get_settings
from app.observability.logger import log_event, preview_text
from app.runtime.session_locks import SessionExecutionLockTimeout
from app.schemas.approval import ApprovalCallbackRequest, ApprovalCallbackResponse
from app.schemas.enums.observability import RuntimeEvent
from app.schemas.message import ChatRequest, ChatResponse


def create_app(sqlite_db_path: str | Path | None = None) -> FastAPI:
    """创建 FastAPI 入口。

    FastAPI 只负责 HTTP adapter、dependency 和 route；Agent runtime 的装配与
    生命周期由 AppContainer 管理，避免 CLI/测试/HTTP 入口各自复制初始化逻辑。
    """
    settings = get_settings()
    container = build_app_container(settings, sqlite_db_path=sqlite_db_path)
    request_adapter = RequestAdapter()
    response_adapter = ResponseAdapter()
    orchestrator = container.orchestrator
    approval_service = container.approval_service
    approval_store = container.storage.approval_store

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Initialize enabled external runtime resources before serving traffic."""
        await container.startup()
        try:
            yield
        finally:
            await container.shutdown()

    app = FastAPI(title="Health Insurance Agent MVP", lifespan=lifespan)
    app.state.container = container

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest, principal: Principal | None = Depends(get_current_principal)) -> ChatResponse:
        """聊天接口：请求适配 -> LangGraph 执行 -> 响应适配。"""
        log_event(
            RuntimeEvent.REQUEST_RECEIVED,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            node="api_chat",
            message="Chat request received",
            data={
                "channel": request.channel,
                "session_id": request.session_id,
                "message_count": len(request.messages),
                "last_message_preview": preview_text(request.messages[-1].content if request.messages else ""),
            },
        )
        try:
            inbound = request_adapter.adapt(request, principal=principal)
            state = await orchestrator.run(inbound)
            response = response_adapter.adapt(state)
            log_event(
                RuntimeEvent.RESPONSE_RETURNED,
                request_id=response.request_id,
                trace_id=state.get("trace_id"),
                session_key=response.session_key,
                user_id=state.get("user_id"),
                tenant_id=state.get("tenant_id"),
                node="api_chat",
                message="Chat response returned",
                data={"intent": response.intent, "answer_preview": preview_text(response.answer)},
            )
            return response
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except SessionExecutionLockTimeout as exc:
            raise HTTPException(
                status_code=409,
                detail="当前会话上一条请求仍在处理中，请稍后再试。",
            ) from exc

    @app.post("/api/approval/callback", response_model=ApprovalCallbackResponse)
    async def approval_callback(request: ApprovalCallbackRequest) -> ApprovalCallbackResponse:
        """Receive external approval decisions and resume the paused flow."""
        try:
            result = await approval_service.handle_callback(request)
            return ApprovalCallbackResponse(
                approval_id=result.approval_request.approval_id,
                status=result.approval_request.status,
                resumed=result.resumed,
                final_answer=result.final_answer,
                error=result.error,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"approval not found: {request.approval_id}") from exc
        except SessionExecutionLockTimeout as exc:
            raise HTTPException(
                status_code=409,
                detail="当前会话上一条请求仍在处理中，请稍后再试。",
            ) from exc

    @app.get("/api/approval/{approval_id}")
    async def get_approval(approval_id: str) -> dict:
        """Return the current approval result for frontend polling."""
        item = await approval_store.get(approval_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"approval not found: {approval_id}")
        return {
            "approval_id": item.approval_id,
            "status": item.status,
            "final_answer": item.final_answer,
            "error": item.error,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "decided_at": item.decided_at,
        }

    return app


app = create_app()
