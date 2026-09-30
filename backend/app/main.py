from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.routing import Route

from .db import engine
from .config import get_settings
from .execution_service import ExecutionGateway, execution_resources
from .sandbox.client import BrokerClientError
from .errors import AtomError
from .models import Base
from .routers import auth, preview, projects, publish, settings, usage
from .schema_guard import verify as verify_schema
from .services.orchestrator import orchestrator
from .services.runtime_client import runtime_client


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _app.state.execution = None
    async with execution_resources(get_settings()) as resources:
        verify_schema(engine)
        if resources is None:
            Base.metadata.create_all(engine)
        await orchestrator.reconcile()
        _app.state.execution = resources
        try:
            yield
        finally:
            _app.state.execution = None
            await orchestrator.shutdown()


app = FastAPI(title="Atoms Demo API", version="1.0.0", lifespan=lifespan)
for action in ('complete', 'cancel'):
    app.router.routes.append(Route('/v1/executions/' + action, ExecutionGateway(), methods=['POST']))


@app.exception_handler(AtomError)
async def handle_atom_error(_request: Request, error: AtomError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail})


_FIELD_LABELS = {
    "email": "邮箱",
    "password": "密码",
    "name": "名称",
    "prompt": "需求描述",
    "message": "消息",
    "models": "模型列表",
    "baseUrl": "Base URL",
    "apiKey": "API Key",
}


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    """Turn Pydantic's error list into one sentence a user can act on.

    The default 422 body is a list of objects, which every client ends up
    rendering as "request failed (422)".
    """
    messages: list[str] = []
    for item in error.errors():
        location = [
            part for part in item.get("loc", ()) if part not in ("body", "query")
        ]
        field = (
            _FIELD_LABELS.get(str(location[-1]), str(location[-1]))
            if location
            else "请求"
        )
        messages.append(f"{field}{_explain(item)}")
    return JSONResponse(
        status_code=422, content={"detail": "；".join(messages) or "请求参数不正确"}
    )


def _explain(item: dict[str, object]) -> str:
    kind = str(item.get("type", ""))
    context = item.get("ctx") if isinstance(item.get("ctx"), dict) else {}
    if kind == "value_error" and "email" in str(item.get("msg", "")).lower():
        return "格式不正确"
    if kind == "missing":
        return "不能为空"
    if kind.endswith("too_short"):
        return f"至少需要 {context.get('min_length', '更多')} 个字符"
    if kind.endswith("too_long"):
        return f"最多 {context.get('max_length', '')} 个字符"
    return "不正确"


@app.get("/api/health")
async def health() -> JSONResponse:
    runtime_ready = await runtime_client.healthy()
    if get_settings().sandbox_mode == 'broker':
        resources = getattr(app.state, 'execution', None)
        broker_ready = False
        if resources is not None:
            try:
                await resources.coordinator.broker.require_ready()
                broker_ready = True
            except BrokerClientError:
                pass
        ready = runtime_ready and broker_ready
        return JSONResponse(status_code=200 if ready else 503,
                            content={'ok':ready,'runtime':runtime_ready,'broker':broker_ready})
    return JSONResponse(status_code=200 if runtime_ready else 503,
                        content={"ok": runtime_ready, "runtime": runtime_ready})


app.include_router(auth.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(publish.router, prefix="/api")
app.include_router(usage.router, prefix="/api")

# Preview and published sites are served from the root, not under /api,
# because generated apps use root-relative asset paths.
app.include_router(preview.router)


@app.get("/api/{path:path}")
async def api_not_found(path: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": f"未知接口 /api/{path}"})
