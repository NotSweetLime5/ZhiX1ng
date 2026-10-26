import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import Counter, Histogram, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api import router
from app.api.routes.a2a import router as a2a_router
from app.core.brand import APP_NAME, APP_VERSION
from app.core.config import settings
from app.core.errors import ServiceError
from app.core.observability import configure_tracing
from app.runtime import Runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
requests = Counter("zhixing_http_requests_total", "HTTP requests", ["method", "path", "status"])
latency = Histogram("zhixing_http_request_seconds", "HTTP request latency", ["method", "path"])


@asynccontextmanager
async def lifespan(app):
    rt = await Runtime(settings()).start()
    app.state.runtime = rt
    try:
        yield
    finally:
        await rt.close()


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings().cors_origins, allow_methods=["*"], allow_headers=["*"]
)
app.include_router(router)
app.include_router(a2a_router)


@app.exception_handler(ServiceError)
@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(
        {"code": exc.status_code, "message": exc.detail, "data": None}, status_code=exc.status_code
    )


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({"code": 400, "message": str(exc), "data": None}, status_code=400)


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse({"code": 409, "message": "名称重复或关联资源不存在", "data": None}, status_code=409)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        {"code": 422, "message": "; ".join(e["msg"] for e in exc.errors()), "data": None}, status_code=422
    )


@app.middleware("http")
async def observe(request: Request, call_next):
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logging.getLogger(__name__).exception("Request failed")
        response = JSONResponse(
            {"code": 500, "message": "服务请求失败，请查看后端日志", "data": None}, status_code=500
        )
    route = request.scope.get("route")
    path = route.path if route else "unmatched"
    requests.labels(request.method, path, response.status_code).inc()
    latency.labels(request.method, path).observe(time.monotonic() - start)
    return response


@app.get("/healthz")
async def health(request: Request):
    rt = request.app.state.runtime
    async with rt.db.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await rt.redis.ping()
    return {"status": "ok", "backend": "python", "agent": "langchain+langgraph"}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain; version=0.0.4")


configure_tracing(settings(), "zhixing-api", app)
