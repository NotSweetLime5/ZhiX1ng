from sqlalchemy import or_

from app import models as t
from app.services.access import owned


async def validate_agent(rt, user, values):
    if values.get("model_config_id"):
        await rt.gateway.resolve(values["model_config_id"])
    if values.get("fallback_model_config_id"):
        await rt.gateway.resolve(values["fallback_model_config_id"])
    for kb in values.get("kb_ids", []):
        await owned(rt, t.kbs, kb, user)
    for binding in values.get("tools", []):
        row = await rt.db.get(t.tools, binding["tool_id"]) if binding.get("tool_id") else None
        if not row and binding.get("tool_code"):
            rows = await rt.db.rows(t.tools, t.tools.c.code == binding["tool_code"], limit=1)
            row = rows[0] if rows else None
        if not row or row["status"] != 1:
            raise ValueError("工具绑定需要有效 tool_id 或 tool_code")
    mode = values.get("config", {}).get("execution_mode", "react")
    if mode not in {"react", "plan"}:
        raise ValueError("execution_mode 支持 react 和 plan")


async def list_agents(rt, user, paging):
    return await rt.db.paged(
        t.agents,
        t.agents.c.status == 1,
        or_(t.agents.c.creator_id == user["id"], t.agents.c.is_preset.is_(True)),
        search_fields=("name", "description"),
        order_by=(t.agents.c.id.asc(),),
        **paging,
    )


async def get_agent(rt, user, ident):
    return await rt.agent.load(ident, user)


async def create_agent(rt, user, body):
    values = body.model_dump(exclude_unset=True, exclude_none=True)
    if not values.get("name"):
        raise ValueError("Agent 名称必填")
    values.setdefault("model_config_id", (await rt.gateway.resolve()).model["id"])
    await validate_agent(rt, user, values)
    return await rt.db.add(t.agents, {**values, "creator_id": user["id"]})


async def update_agent(rt, user, ident, body):
    await owned(rt, t.agents, ident, user, "creator_id")
    values = body.model_dump(exclude_unset=True)
    values = {
        key: value for key, value in values.items() if value is not None or key == "fallback_model_config_id"
    }
    await validate_agent(rt, user, values)
    return await rt.db.change(t.agents, ident, values)


async def delete_agent(rt, user, ident):
    await owned(rt, t.agents, ident, user, "creator_id")
    await rt.db.change(t.agents, ident, {"status": 0})
    return None


async def list_tools(rt, user, paging):
    return await rt.db.paged(t.tools, t.tools.c.status == 1, **paging)
