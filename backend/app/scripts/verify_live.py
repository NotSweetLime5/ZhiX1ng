"""Exercise the running services. --model-calls explicitly enables billable probes.

Run inside the API container after enable_integrations. Output contains summaries
only: no credentials, document contents, or authentication tokens.
"""

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime

import httpx

from app import models as t
from app.cli import configure_loop
from app.core.config import settings
from app.runtime import Runtime


async def verify(model_calls=False):
    rt = await Runtime(settings()).start()
    report = {"checked_at": datetime.now(UTC).isoformat(), "checks": {}}
    checks = report["checks"]
    try:
        user = (await rt.db.rows(t.users, t.users.c.role == "admin", t.users.c.status == 1, limit=1))[0]
        token = rt.security.token_pair(user)["access_token"]
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8080", timeout=120, headers={"Authorization": "Bearer " + token}
        ) as client:

            async def api(method, path, **kwargs):
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
                body = response.json()
                return body.get("data", body)

            checks["api"] = await api("GET", "/healthz")
            server = (
                await rt.db.rows(t.mcp_servers, t.mcp_servers.c.name == "Zhixing local tools", limit=1)
            )[0]
            for name, args in {
                "calculator": {"expression": "123*456"},
                "current_time": {},
                "web_search": {"query": "FastAPI Python", "count": 3},
                "fetch_page": {"url": "https://docs.python.org/3/"},
            }.items():
                result = await api(
                    "POST",
                    f"/api/v1/admin/mcp/servers/{server['id']}/call",
                    json={"name": name, "args": args},
                )
                encoded = json.dumps(result)
                assert result.get("output"), f"Empty MCP output: {name}"
                if name == "calculator":
                    assert "56088" in encoded
                elif name == "web_search":
                    assert "https://" in encoded
                elif name == "fetch_page":
                    assert "200" in encoded and "Python" in encoded
                checks["mcp_" + name] = {"ok": True}

            try:
                await rt.tools.invoke("http_client", {"url": "http://unlisted.invalid"}, user)
                raise AssertionError("HTTP allowlist did not reject an unlisted domain")
            except ValueError:
                checks["http_allowlist"] = {
                    "allowed_domains": rt.cfg.allowed_http_hosts,
                    "rejects_unlisted": True,
                }

            assert rt.cfg.sandbox_enabled
            programs = {
                "python": "print(2+3)",
                "shell": "echo $((2+3))",
                "go": 'package main; import "fmt"; func main(){ fmt.Println(2+3) }',
            }
            for language, code in programs.items():
                result = await asyncio.to_thread(rt.tools.sandbox, {"language": language, "code": code})
                assert result["exit_code"] == 0 and result["output"].strip() == "5"
                checks["sandbox_" + language] = {"ok": True}

            if model_calls:
                agent = (
                    await rt.db.rows(
                        t.agents,
                        t.agents.c.creator_id == user["id"],
                        t.agents.c.name == "联网与 MCP 助手",
                        limit=1,
                    )
                )[0]
                response = await client.post(
                    "/api/v1/chat/stream",
                    json={
                        "agent_id": agent["id"],
                        "content": "请调用 calculator 工具计算 123*456，只回复计算结果。",
                    },
                )
                response.raise_for_status()
                events, answer, refs, tools = [], "", 0, []
                for frame in response.text.split("\n\n"):
                    lines = frame.splitlines()
                    if len(lines) < 2:
                        continue
                    event, data = (
                        lines[0].removeprefix("event: "),
                        json.loads(lines[1].removeprefix("data: ")),
                    )
                    events.append(event)
                    assert event != "error", "Live streaming chat returned an error"
                    if event == "delta":
                        answer += data.get("content", "")
                    elif event == "refs":
                        refs = len(data.get("items", []))
                    elif event == "tool_call":
                        tools.append(data.get("name", data.get("tool", "")))
                assert "56088" in answer and "tool_result" in events and "done" in events
                if agent["kb_ids"]:
                    assert refs > 0
                checks["model_mcp_rag_stream"] = {"ok": True, "references": refs, "tool_names": tools}

                remote = (await rt.db.rows(t.a2a_agents, t.a2a_agents.c.name == "Zhixing A2A", limit=1))[0]
                result = await api(
                    "POST",
                    f"/api/v1/admin/a2a/agents/{remote['id']}/tasks",
                    json={"text": "只回复联调成功。"},
                )
                assert result["state"] == "completed" and result["text"]
                checks["a2a_modern"] = {"ok": True, "state": result["state"]}
                async with httpx.AsyncClient(timeout=120) as legacy:
                    response = await legacy.post(
                        remote["base_url"] + "/a2a",
                        json={
                            "jsonrpc": "2.0",
                            "id": "live",
                            "method": "message/send",
                            "params": {"message": {"parts": [{"type": "text", "text": "只回复 OK。"}]}},
                        },
                    )
                    result = response.json()
                    assert result["result"]["status"] == "completed"
                    checks["a2a_legacy_anonymous"] = {"ok": True, "port": 8082}

                kb = await api("POST", "/api/v1/kbs", json={"name": "live-check-" + uuid.uuid4().hex})
                try:
                    document = await api(
                        "POST",
                        f"/api/v1/kbs/{kb['id']}/documents",
                        files={
                            "file": (
                                "live-check.txt",
                                b"The migration verification number is 56088. Redis Streams delivers this document to the Python worker.",
                                "text/plain",
                            )
                        },
                    )
                    for _ in range(120):
                        row = await rt.db.get(t.documents, document["id"])
                        if row["status"] == "ready":
                            break
                        assert row["status"] != "failed", "Live worker ETL failed"
                        await asyncio.sleep(1)
                    else:
                        raise TimeoutError("Live document was not indexed")
                    refs = await api(
                        "POST",
                        f"/api/v1/kbs/{kb['id']}/retrieve",
                        json={"query": "migration verification number"},
                    )
                    assert refs and any("56088" in ref["content"] for ref in refs)
                    jobs = await rt.db.rows(
                        t.jobs,
                        t.jobs.c.kind == "doc_etl",
                        t.jobs.c.payload["doc_id"].as_integer() == document["id"],
                    )
                    assert jobs[0]["status"] == "done" and jobs[0]["stream_id"]
                    checks["redis_streams_real_etl"] = {
                        "ok": True,
                        "references": len(refs),
                        "stream_id": jobs[0]["stream_id"],
                    }
                finally:
                    await api("DELETE", f"/api/v1/kbs/{kb['id']}")
                    for _ in range(30):
                        if not await rt.db.get(t.kbs, kb["id"]):
                            break
                        await asyncio.sleep(1)
                    assert not await rt.db.get(t.kbs, kb["id"]), "Temporary knowledge base cleanup failed"

            async with httpx.AsyncClient(timeout=15) as obs:
                response = await obs.get("http://prometheus:9090/api/v1/targets")
                targets = response.json()["data"]["activeTargets"]
                assert any(x["labels"]["job"] == "nexus-agent" and x["health"] == "up" for x in targets)
                checks["prometheus"] = {"api_target": "up"}
                response = await obs.get("http://jaeger:16686/api/services")
                services = response.json()["data"]
                assert "zhixing-api" in services
                checks["jaeger"] = {"services": services}
                response = await obs.get(
                    "http://grafana:3000/api/dashboards/uid/zhixing-overview", auth=("admin", "admin")
                )
                response.raise_for_status()
                checks["grafana"] = {"dashboard": response.json()["dashboard"]["title"]}
        report["ok"] = True
        return report
    finally:
        await rt.close()


if __name__ == "__main__":
    configure_loop()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-calls", action="store_true", help="Allow small real model/embedding requests"
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(args.model_calls)), ensure_ascii=False, indent=2))
