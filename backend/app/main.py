from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .db import engine
from .errors import AtomError
from .models import Base
from .routers import auth, preview, projects, publish, settings, usage
from .schema_guard import verify as verify_schema
from .services.orchestrator import orchestrator
from .services.runtime_client import runtime_client


@asynccontextmanager
async def lifespan(_app: FastAPI):
    verify_schema(engine)
    Base.metadata.create_all(engine)
    yield
    await orchestrator.shutdown()


app = FastAPI(title="Atoms Demo API", version="1.0.0", lifespan=lifespan)


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
        location = [part for part in item.get("loc", ()) if part not in ("body", "query")]
        field = _FIELD_LABELS.get(str(location[-1]), str(location[-1])) if location else "请求"
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
async def health() -> dict[str, object]:
    return {"ok": True, "runtime": await runtime_client.healthy()}


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
