"""Idempotently register the bundled live MCP/A2A services and a usable assistant."""

import argparse
import asyncio
import json

import httpx

from app import models as t
from app.cli import configure_loop
from app.core.config import settings
from app.runtime import Runtime
from app.services.integrations import health_a2a, register_a2a


async def enable(mcp_url, a2a_url):
    # Compose reports containers running before Uvicorn has finished startup.
    async with httpx.AsyncClient(timeout=3) as client:
        for attempt in range(30):
            try:
                response = await client.get(a2a_url.rstrip("/") + "/.well-known/agent.json")
                response.raise_for_status()
                break
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt == 29:
                    raise
                await asyncio.sleep(1)
    rt = await Runtime(settings()).start()
    try:
        users = await rt.db.rows(t.users, t.users.c.role == "admin", t.users.c.status == 1, limit=1)
        if not users:
            raise RuntimeError("Seed an administrator before registering integrations")
        user = users[0]
        rows = await rt.db.rows(t.mcp_servers, t.mcp_servers.c.name == "Zhixing local tools", limit=1)
        values = {"name": "Zhixing local tools", "transport": "streamable_http", "url": mcp_url}
        server = (
            await rt.db.change(t.mcp_servers, rows[0]["id"], values)
            if rows
            else await rt.db.add(t.mcp_servers, values)
        )
        count = await rt.tools.sync_mcp(server)
        rows = await rt.db.rows(t.a2a_agents, t.a2a_agents.c.name == "Zhixing A2A", limit=1)
        if rows and rows[0]["base_url"] != a2a_url:
            rows[0] = await rt.db.change(t.a2a_agents, rows[0]["id"], {"base_url": a2a_url})
        remote = (
            rows[0] if rows else await register_a2a(rt, user, {"base_url": a2a_url, "name": "Zhixing A2A"})
        )
        await health_a2a(rt, user, remote["id"])
        try:
            model = await rt.gateway.resolve()
        except ValueError:
            print(
                json.dumps(
                    {
                        "mcp_server_id": server["id"],
                        "mcp_tools": count,
                        "a2a_agent_id": remote["id"],
                        "assistant_id": None,
                        "next_step": "Configure a usable default chat provider, then rerun enable_integrations.",
                    }
                )
            )
            return
        tools = await rt.db.rows(t.tools, t.tools.c.mcp_server_id == server["id"], t.tools.c.status == 1)
        kbs = await rt.db.rows(t.kbs, t.kbs.c.user_id == user["id"], t.kbs.c.status == "active")
        values = {
            "name": "联网与 MCP 助手",
            "description": "调用本地 MCP 服务的计算、时间、联网搜索和网页读取，并检索你的知识库。",
            "creator_id": user["id"],
            "model_config_id": model.model["id"],
            "system_prompt": "你是知行助手。计算必须调用 calculator 工具，联网问题先搜索再回答。知识库问题根据参考资料回答。",
            "tools": [{"tool_id": tool["id"]} for tool in tools],
            "kb_ids": [kb["id"] for kb in kbs],
            "max_tokens": 1024,
            "memory_long_enabled": False,
        }
        rows = await rt.db.rows(
            t.agents, t.agents.c.creator_id == user["id"], t.agents.c.name == values["name"], limit=1
        )
        agent = (
            await rt.db.change(t.agents, rows[0]["id"], values) if rows else await rt.db.add(t.agents, values)
        )
        print(
            json.dumps(
                {
                    "mcp_server_id": server["id"],
                    "mcp_tools": count,
                    "a2a_agent_id": remote["id"],
                    "assistant_id": agent["id"],
                },
                ensure_ascii=False,
            )
        )
    finally:
        await rt.close()


if __name__ == "__main__":
    configure_loop()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8086/mcp")
    parser.add_argument("--a2a-url", default="http://127.0.0.1:8082")
    args = parser.parse_args()
    asyncio.run(enable(args.mcp_url, args.a2a_url))
