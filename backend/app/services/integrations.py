import json
import uuid

import httpx

from app import models as t
from app.core.errors import ServiceError


async def mcp_server(rt, ident):
    server = await rt.db.get(t.mcp_servers, ident)
    if not server:
        raise ServiceError(404, "MCP 服务不存在")
    return server


async def fetch_card(url):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url.rstrip("/") + "/.well-known/agent.json")
        response.raise_for_status()
        card = response.json()
        if not isinstance(card, dict) or not card.get("name") or not card.get("url"):
            raise ValueError("无效 Agent Card")
        return card


async def sync_mcp(rt, user, ident):
    server = await mcp_server(rt, ident)
    try:
        return {"synced": await rt.tools.sync_mcp(server)}
    except Exception:
        await rt.db.change(t.mcp_servers, ident, {"status": "error", "last_health_at": t.now()})
        raise


async def health_mcp(rt, user, ident):
    server = await mcp_server(rt, ident)
    try:
        await rt.tools.remote_tools(server)
    except Exception:
        await rt.db.change(t.mcp_servers, ident, {"status": "error", "last_health_at": t.now()})
        raise
    await rt.db.change(t.mcp_servers, ident, {"status": "connected", "last_health_at": t.now()})
    return {"status": "connected"}


async def call_mcp(rt, user, ident, body):
    tools = await rt.tools.remote_tools(await mcp_server(rt, ident))
    tool = next((x for x in tools if x.name == body.get("name")), None)
    if not tool:
        raise ValueError("MCP 工具不存在")
    return {"output": await tool.ainvoke(body.get("args", {}))}


async def list_a2a(rt, user):
    return await rt.db.rows(t.a2a_agents)


async def register_a2a(rt, user, body):
    url = body.get("base_url", "")
    card = await fetch_card(url)
    return await rt.db.add(
        t.a2a_agents,
        {
            "name": body.get("name") or card["name"],
            "base_url": url,
            "card": card,
            "status": "connected",
            "last_health_at": t.now(),
        },
    )


async def delete_a2a(rt, user, ident):
    await rt.db.remove(t.a2a_agents, ident)
    return None


async def health_a2a(rt, user, ident):
    agent = await rt.db.get(t.a2a_agents, ident)
    if not agent:
        raise ServiceError(404, "远程 Agent 不存在")
    try:
        card = await fetch_card(agent["base_url"])
    except Exception:
        await rt.db.change(t.a2a_agents, ident, {"status": "error", "last_health_at": t.now()})
        raise
    await rt.db.change(t.a2a_agents, ident, {"card": card, "status": "connected", "last_health_at": t.now()})
    return {"status": "connected"}


async def send_a2a(rt, user, ident, body):
    if not body.get("text", "").strip():
        raise ValueError("任务内容不能为空")
    agent = await rt.db.get(t.a2a_agents, ident)
    if not agent:
        raise ServiceError(404, "远程 Agent 不存在")
    async with httpx.AsyncClient(timeout=rt.cfg.run_timeout) as client:
        response = await client.post(
            agent["card"]["url"],
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        # Accept peers using either discriminator spelling.
                        "parts": [{"kind": "text", "type": "text", "text": body["text"]}],
                    }
                },
            },
        )
        response.raise_for_status()
        result = response.json()
        if result.get("error"):
            raise ValueError(json.dumps(result["error"], ensure_ascii=False))
        task = result.get("result")
        if not isinstance(task, dict) or not task.get("id"):
            raise ValueError("远程 Agent 返回了无效任务")
        status = task.get("status", "unknown")
        state = status.get("state", "unknown") if isinstance(status, dict) else status
        answer = "".join(
            part.get("text", "")
            for artifact in task.get("artifacts", [])
            for part in artifact.get("parts", [])
            if part.get("kind", part.get("type")) == "text"
        )
        return {"task_id": task["id"], "state": state, "text": answer}
