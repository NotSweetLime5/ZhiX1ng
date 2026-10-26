import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from app import models as t
from app.agents.planning import ordered_steps
from app.agents.workflow import parse_dsl, render
from app.schemas.agent import Plan
from app.services.evaluation import evaluate
from app.services.tools import Tools


def test_dsl_validation_and_templates():
    with pytest.raises(ValueError, match="环"):
        parse_dsl("name: cyclic\nnodes: [{key: a, type: human}, {key: b, type: human}]\nedges: [a,b,a]")
    with pytest.raises(ValueError, match="引用不存在"):
        parse_dsl("name: bad\nnodes: [{key: a, type: condition, expr: 'true', then: missing, else: a}]")
    assert render("{{a.result}}", {"a": {"result": "5"}}) == "5"
    plan = Plan.model_validate(
        {
            "goal": "x",
            "steps": [{"id": "b", "description": "b", "depends_on": ["a"]}, {"id": "a", "description": "a"}],
        }
    )
    assert [s["id"] for s in ordered_steps(plan)] == ["a", "b"]


async def test_auth_refresh_and_permissions(rt, client):
    response = await client.post(
        "/api/v1/auth/login", json={"username": rt.test_user["username"], "password": "password123"}
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["refresh_token"]
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": token})).status_code == 200
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": token})).status_code == 401
    assert (
        await client.get("/api/v1/admin/models", headers={"Authorization": "Bearer bad"})
    ).status_code == 401
    plain = await rt.db.add(
        t.users,
        {
            "username": "u_" + uuid.uuid4().hex[:10],
            "email": uuid.uuid4().hex + "@test.local",
            "password_hash": "unused",
        },
    )
    try:
        tokens = await rt.security.tokens(plain)
        forbidden = await client.get(
            "/api/v1/admin/models", headers={"Authorization": "Bearer " + tokens["access_token"]}
        )
        assert forbidden.status_code == 403
    finally:
        await rt.db.remove(t.users, plain["id"])


async def test_react_sse_and_history(rt, client):
    response = await client.post(
        "/api/v1/chat/stream", json={"agent_id": rt.test_expert["id"], "content": "计算2+3"}
    )
    assert response.status_code == 200, response.text
    frames = [x for x in response.text.split("\n\n") if x.strip()]
    events = [frame.splitlines()[0][7:] for frame in frames]
    assert events[0] == "meta"
    assert "tool_call" in events and "tool_result" in events
    assert events[-1] == "done", response.text
    session = json.loads(frames[0].splitlines()[1][6:])["session_id"]
    history = (await client.get(f"/api/v1/sessions/{session}/messages")).json()["data"]
    assert len(history) == 2
    assert "5" in history[-1]["content"]
    assert history[-1]["metadata"]["agent_trace"]


async def test_host_and_plan_use_langgraph(rt):
    user = rt.test_user
    host = {**rt.test_expert, "type": "host"}
    graph = await rt.agent.compile(host, user, "系统规则")
    output = {}
    events = [
        event
        async for event in rt.agent.events(
            graph, [HumanMessage(content="计算2+3")], "test-host:" + uuid.uuid4().hex, output
        )
    ]
    assert graph.name == "ZhixingHost"
    assert any(e == "agent_event" and d["type"] == "delegate" for e, d in events)
    assert "5" in output["content"]
    planned = {**rt.test_expert, "config": {"execution_mode": "plan"}}
    graph = await rt.agent.compile(planned, user, "系统规则")
    output = {}
    events = [
        event
        async for event in rt.agent.events(
            graph, [HumanMessage(content="计算2+3")], "test-plan:" + uuid.uuid4().hex, output
        )
    ]
    assert graph.name == "ZhixingPlan"
    assert any(e == "plan" for e, _ in events)
    assert "s1" in output.get("final_messages", [])[-1]["data"]["content"] or output["content"] == "已完成"


async def test_multiple_approvals_survive_rebuild(rt, client):
    dsl = """name: 审批测试
nodes:
  - {key: first, type: human, prompt: 第一次审批}
  - {key: calc, type: tool, tool_code: calculator, args: {expression: '2+3'}}
  - {key: second, type: human, prompt: 第二次审批}
  - {key: finish, type: tool, tool_code: calculator, args: {expression: '{{calc}}+1'}}
"""
    created = await client.post("/api/v1/workflows", json={"name": "审批", "dsl": dsl})
    assert created.status_code == 200, created.text
    workflow_id = created.json()["data"]["id"]
    response = await client.post("/api/v1/workflows/run", json={"workflow_id": workflow_id, "input": {}})
    run = response.json()["data"]
    assert run["status"] == "waiting_approval", response.text
    assert run["output"]["approval"]["node_key"] == "first"
    # Every call rebuilds the graph; no local pending execution object is retained.
    response = await client.post(f"/api/v1/workflows/runs/{run['id']}/approve", json={"approved": True})
    run = response.json()["data"]
    assert run["status"] == "waiting_approval", response.text
    assert run["output"]["approval"]["node_key"] == "second"
    # Modifying the definition does not mutate an in-flight run's DSL snapshot.
    await rt.db.change(t.workflows, workflow_id, {"dsl": "name: changed\nnodes: [{key: nope, type: human}]"})
    response = await client.post(f"/api/v1/workflows/runs/{run['id']}/approve", json={"approved": True})
    run = response.json()["data"]
    assert run["status"] == "succeeded", response.text
    assert run["output"]["finish"] == "6"
    replay = await client.post(f"/api/v1/workflows/runs/{run['id']}/approve", json={"approved": True})
    assert replay.status_code == 400


async def test_native_milvus_bm25_and_index_idempotence(rt, client, monkeypatch):
    response = await client.post(
        "/api/v1/kbs", json={"name": "检索测试", "embedding_config_id": rt.test_embed["id"]}
    )
    assert response.status_code == 200, response.text
    kb = response.json()["data"]
    upload = await client.post(
        f"/api/v1/kbs/{kb['id']}/documents",
        files={"file": ("test.md", "Zhixing 支持 LangGraph 审批恢复和 Milvus BM25 检索。".encode())},
    )
    assert upload.status_code == 200, upload.text
    doc = upload.json()["data"]
    await rt.rag.index(doc["id"])
    first = await rt.db.rows(t.chunks, t.chunks.c.document_id == doc["id"])

    async def unexpected_embedding(*args, **kwargs):
        raise AssertionError("A replayed ready-document job must not call the embedding provider again")

    with monkeypatch.context() as patch:
        patch.setattr(rt.gateway, "embed", unexpected_embedding)
        await rt.rag.index(doc["id"])
    second = await rt.db.rows(t.chunks, t.chunks.c.document_id == doc["id"])
    assert [c["id"] for c in first] == [c["id"] for c in second]
    response = await client.post(f"/api/v1/kbs/{kb['id']}/retrieve", json={"query": "LangGraph 审批恢复"})
    assert response.status_code == 200, response.text
    refs = response.json()["data"]
    assert refs and refs[0]["filename"] == "test.md"
    assert refs[0]["page"] == 1 and "BM25" in refs[0]["content"]
    await rt.rag.delete_doc(rt.test_user["id"], kb["id"], doc["id"])
    assert await rt.rag.retrieve(rt.test_user["id"], kb["id"], "LangGraph") == []
    await rt.rag.cleanup_doc(doc["id"])


async def test_evaluation_executes_agent(rt):
    dataset = await rt.db.add(t.eval_datasets, {"name": "计算", "user_id": rt.test_user["id"]})
    await rt.db.add(
        t.eval_cases,
        {
            "dataset_id": dataset["id"],
            "question": "计算2+3",
            "expected_answer": "5",
            "expected_tools": ["calculator"],
        },
    )
    run = await rt.db.add(
        t.eval_runs,
        {"dataset_id": dataset["id"], "user_id": rt.test_user["id"], "agent_id": rt.test_expert["id"]},
    )
    await evaluate(rt, run["id"])
    result = await rt.db.get(t.eval_runs, run["id"])
    assert result["status"] == "succeeded" and result["passed"] == 1


async def test_mcp_sync_and_reconstruct_after_restart(rt, client):
    process = await asyncio.to_thread(
        subprocess.Popen,
        [sys.executable, str(Path(__file__).with_name("mcp_server.py"))],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    server = None
    try:
        import httpx

        for _ in range(100):
            assert process.poll() is None, "MCP test server exited before it was ready"
            try:
                async with httpx.AsyncClient(trust_env=False) as probe:
                    response = await probe.get("http://127.0.0.1:18086/mcp", timeout=1)
                if response.status_code < 500:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
        else:
            pytest.fail("MCP test server did not become ready")
        created = await client.post(
            "/api/v1/admin/mcp/servers", json={"name": "Test MCP", "url": "http://127.0.0.1:18086/mcp"}
        )
        assert created.status_code == 200, created.text
        server = created.json()["data"]
        synced = await client.post(f"/api/v1/admin/mcp/servers/{server['id']}/sync")
        assert synced.status_code == 200, synced.text
        assert synced.json()["data"]["synced"] == 1
        row = (await rt.db.rows(t.tools, t.tools.c.mcp_server_id == server["id"]))[0]
        rebuilt = Tools(rt.db, rt.rag, rt.cfg)
        toolset = await rebuilt.build([{"tool_id": row["id"]}], rt.test_user)
        result = await toolset[0].ainvoke({"a": 2, "b": 3})
        assert "5" in str(result)
        direct = await client.post(
            f"/api/v1/admin/mcp/servers/{server['id']}/call", json={"name": "add", "args": {"a": 2, "b": 3}}
        )
        assert direct.status_code == 200 and "5" in direct.text
    finally:
        if server:
            await rt.db.remove(t.mcp_servers, server["id"])
        process.terminate()
        await asyncio.to_thread(process.wait, 10)


async def test_nested_subflow_approval_and_rejection(rt, client):
    child = await rt.db.add(
        t.workflows,
        {
            "name": "child",
            "creator_id": rt.test_user["id"],
            "dsl": """name: child
nodes:
  - {key: ask, type: human, prompt: child approval}
  - {key: calc, type: tool, tool_code: calculator, args: {expression: '2+3'}}
""",
        },
    )
    parent = await rt.db.add(
        t.workflows,
        {
            "name": "parent",
            "creator_id": rt.test_user["id"],
            "dsl": f"""name: parent
nodes:
  - {{key: sub, type: subflow, workflow: {child["id"]}}}
""",
        },
    )
    run = await rt.workflow.run(parent, rt.test_user, {})
    assert run["status"] == "waiting_approval", run
    run = await rt.workflow.approve(run, rt.test_user, {"approved": True})
    assert run["status"] == "succeeded", run
    assert run["output"]["sub"]["calc"] == "5"
    run = await rt.workflow.run(parent, rt.test_user, {})
    run = await rt.workflow.approve(run, rt.test_user, {"approved": False, "comment": "拒绝"})
    assert run["status"] == "canceled", run


async def test_parallel_condition_and_dangerous_tool_gate(rt):
    dsl = """name: parallel
nodes:
  - {key: parallel, type: parallel, branches: [a,b]}
  - {key: a, type: tool, tool_code: calculator, args: {expression: '2+3'}}
  - {key: b, type: tool, tool_code: calculator, args: {expression: '3+4'}}
  - {key: condition, type: condition, expr: "a == '5'", then: yes, else: nope}
  - {key: yes, type: tool, tool_code: calculator, args: {expression: '1+1'}}
  - {key: nope, type: tool, tool_code: calculator, args: {expression: '1+2'}}
edges: [{from: parallel, to: condition}]
out: yes
"""
    # YAML treats unquoted "yes" as a boolean; use an unambiguous key.
    dsl = dsl.replace("yes", "success")
    workflow = await rt.db.add(
        t.workflows, {"name": "parallel", "creator_id": rt.test_user["id"], "dsl": dsl}
    )
    run = await rt.workflow.run(workflow, rt.test_user, {})
    assert run["status"] == "succeeded", run
    assert run["output"]["a"] == "5" and run["output"]["b"] == "7" and run["output"]["success"] == "2"
    assert "nope" not in run["output"]
    with pytest.raises(ValueError, match="审批"):
        await rt.tools.call(
            "file_ops", {"operation": "save", "path": "test.txt", "content": "x"}, rt.test_user
        )
