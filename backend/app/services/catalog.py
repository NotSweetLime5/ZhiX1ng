from app import models as t
from app.core.errors import ServiceError


def clean(body, table, required=()):
    allowed = set(table.c.keys()) - {"id", "created_at", "updated_at"}
    unknown = set(body) - allowed
    if unknown:
        raise ValueError(f"不支持的字段：{sorted(unknown)}")
    if any(not body.get(key) for key in required):
        raise ValueError(f"必填字段：{required}")
    return body.copy()


async def safe_provider(row, rt):
    result = dict(row)
    key = rt.security.decrypt(result.pop("api_key", ""))
    result["api_key_masked"] = key[:2] + "****" + key[-4:] if key else ""
    return result


async def listing(table, required, rt, user, type=None):
    filters = [table.c.type == type] if table is t.models and type else []
    rows = await rt.db.rows(table, *filters, limit=10000)
    if table is t.providers:
        rows = [await safe_provider(row, rt) for row in rows]
    return rows


async def create(table, required, rt, user, body):
    values = clean(body, table, required)
    await validate(table, values, rt)
    row = await rt.db.add(table, values)
    return await safe_provider(row, rt) if table is t.providers else row


async def edit(table, required, rt, user, ident, body):
    current = await rt.db.get(table, ident)
    if not current:
        raise ServiceError(404, "资源不存在")
    values = clean(body, table)
    await validate(table, values, rt)
    row = await rt.db.change(table, ident, values)
    return await safe_provider(row, rt) if table is t.providers else row


async def validate(table, values, rt):
    if table is t.providers:
        if values.get("api_key"):
            values["api_key"] = rt.security.encrypt(values["api_key"])
        else:
            values.pop("api_key", None)
    if table is t.mcp_servers:
        if values.get("transport", "streamable_http") not in {"streamable_http", "sse"}:
            raise ValueError("MCP transport 支持 streamable_http 和 sse")
    if table is t.models and values.get("type", "chat") not in {"chat", "embedding", "rerank"}:
        raise ValueError("模型类型不支持")


async def remove(table, required, rt, user, ident):
    if not await rt.db.get(table, ident):
        raise ServiceError(404, "资源不存在")
    if table is t.models:
        referenced = await rt.db.rows(t.agents, t.agents.c.model_config_id == ident, limit=1)
        referenced += await rt.db.rows(t.agents, t.agents.c.fallback_model_config_id == ident, limit=1)
        referenced += await rt.db.rows(t.kbs, t.kbs.c.embedding_config_id == ident, limit=1)
        if referenced:
            raise ServiceError(409, "模型仍被 Agent 或知识库引用")
    if table is t.providers and await rt.db.rows(t.models, t.models.c.provider_id == ident, limit=1):
        raise ServiceError(409, "供应商仍包含模型")
    await rt.db.remove(table, ident)
    return None
