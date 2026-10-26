"""Behavior checks against chengpeng-cp/nexus-agent at 5c7b81e, beyond route counts."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk

from app import models as t
from app.core.config import Settings
from app.runtime import Runtime
from app.services import integrations
from app.services.llm import CircuitBreaker, Descriptor, Gateway
from app.services.tools import Tools
from app.worker import process
from conftest import ScriptedModel


@pytest.mark.parametrize("password", ["admin123", "replace-with-an-admin-password"])
def test_new_admin_bootstrap_rejects_weak_or_placeholder_password(password):
    from app.scripts.seed import bootstrap_password

    with pytest.raises(ValueError, match="16"):
        bootstrap_password(Settings(admin_password=password))


def test_new_admin_password_is_generated_when_unconfigured():
    from app.scripts.seed import bootstrap_password

    first, generated = bootstrap_password(Settings(admin_password=""))
    second, _ = bootstrap_password(Settings(admin_password=""))
    assert generated and len(first) >= 16 and first != second


@pytest.mark.parametrize("env", ["prod", "production"])
def test_production_rejects_default_or_shared_secrets(env):
    with pytest.raises(ValueError, match="密钥"):
        Settings(_env_file=None, env=env, jwt_secret="short", secret_key="short")
    with pytest.raises(ValueError, match="不能相同"):
        Settings(_env_file=None, env=env, jwt_secret="a" * 40, secret_key="a" * 40)
    cfg = Settings(_env_file=None, env=env, jwt_secret="a" * 40, secret_key="b" * 40)
    assert cfg.env == env


async def test_refresh_rotation_rejects_replay_and_concurrent_reuse(rt, client):
    pair = await rt.security.tokens(rt.test_user)
    responses = await asyncio.gather(
        *(
            client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
            for _ in range(2)
        )
    )
    assert sorted(response.status_code for response in responses) == [200, 401]
    rotated = next(response.json()["data"] for response in responses if response.status_code == 200)
    assert rotated["refresh_token"] != pair["refresh_token"]
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    ).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    ).status_code == 200


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("not-an-email", "a-long-test-password"),
        ("a@example.com", "eight123"),
        ("bad @example.com", "a-long-test-password"),
    ],
)
async def test_registration_rejects_inputs_rejected_by_upstream(client, email, password):
    response = await client.post(
        "/api/v1/auth/register", json={"username": "new_user", "email": email, "password": password}
    )
    assert response.status_code == 422


async def test_datetime_diff_operation_is_preserved():
    result = await Tools(None, None, Settings()).invoke(
        "datetime", {"operation": "diff", "tz": "Asia/Shanghai"}, {"id": 1}
    )
    days, _, _, date = result.split()
    assert 0 <= int(days) <= 366 and date.endswith("-01-01")


async def test_workflow_partial_updates_preserve_dsl_and_false_values(rt, client):
    dsl = "name: original\nnodes: [{key: calc, type: tool, tool_code: calculator, args: {expression: '2+3'}}]"
    created = await client.post("/api/v1/workflows", json={"name": "original", "dsl": dsl})
    workflow = created.json()["data"]
    response = await client.put(
        f"/api/v1/workflows/{workflow['id']}", json={"name": "renamed", "is_active": False, "status": 0}
    )
    assert response.status_code == 200, response.text
    updated = response.json()["data"]
    assert updated["dsl"] == dsl and updated["name"] == "renamed"
    assert updated["is_active"] is False and updated["status"] == 0


@pytest.mark.parametrize("legacy", [True, False])
async def test_a2a_delegation_accepts_upstream_go_and_modern_task_shapes(rt, client, monkeypatch, legacy):
    remote = await rt.db.add(
        t.a2a_agents,
        {"name": "remote", "base_url": "http://remote.test", "card": {"url": "http://remote.test/a2a"}},
    )

    def respond(request):
        message = json.loads(request.content)["params"]["message"]
        assert message["parts"][0]["type"] == "text"  # Original Go's Part struct.
        assert message["parts"][0]["kind"] == "text"  # A2A 0.3 text part.
        assert message["parts"][0]["text"] == "question"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "result": {
                    "id": "task-1",
                    "status": "completed" if legacy else {"state": "completed"},
                    "artifacts": [{"parts": [{"type" if legacy else "kind": "text", "text": "answer"}]}],
                },
            },
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        integrations.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    try:
        response = await client.post(
            f"/api/v1/admin/a2a/agents/{remote['id']}/tasks", json={"text": "question"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"task_id": "task-1", "state": "completed", "text": "answer"}
    finally:
        await rt.db.remove(t.a2a_agents, remote["id"])


async def test_a2a_type_parts_return_go_compatible_task(client):
    response = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"type": "text", "text": "hello"}]}},
        },
    )
    task = response.json()["result"]
    assert task["status"] == "completed"
    assert task["artifacts"][0]["parts"][0] == {"type": "text", "text": "已完成"}


async def test_a2a_health_refreshes_card_and_marks_failures(rt, monkeypatch):
    remote = await rt.db.add(
        t.a2a_agents,
        {"name": "remote", "base_url": "http://remote.test", "card": {"url": "http://remote.test/old"}},
    )
    card = {"name": "updated", "url": "http://remote.test/new"}

    async def fetch(url):
        return card

    monkeypatch.setattr(integrations, "fetch_card", fetch)
    try:
        await integrations.health_a2a(rt, rt.test_user, remote["id"])
        assert (await rt.db.get(t.a2a_agents, remote["id"]))["card"] == card

        async def broken(url):
            raise RuntimeError("offline")

        monkeypatch.setattr(integrations, "fetch_card", broken)
        with pytest.raises(RuntimeError, match="offline"):
            await integrations.health_a2a(rt, rt.test_user, remote["id"])
        assert (await rt.db.get(t.a2a_agents, remote["id"]))["status"] == "error"
    finally:
        await rt.db.remove(t.a2a_agents, remote["id"])


def test_breaker_uses_window_error_rate_and_resets_after_opening():
    breaker = CircuitBreaker(Settings(llm_circuit_window=4, llm_circuit_error_rate=0.5))
    for result in [True, False, True]:
        breaker.record(result)
        assert breaker.allow()
    breaker.record(False)
    assert not breaker.allow()
    breaker.open_until = 0
    breaker.record(True)
    assert breaker.allow() and list(breaker.window) == [True]


async def test_non_streaming_calls_use_guarded_fallback(rt, monkeypatch):
    primary = await rt.gateway.resolve(rt.test_model["id"])
    fallback = Descriptor(
        {**primary.model, "model_name": "backup"}, {**primary.provider, "code": "backup"}, "test-key"
    )
    calls = []

    class Model:
        def __init__(self, desc):
            self.desc = desc

        async def ainvoke(self, messages, config=None):
            calls.append(self.desc.model["model_name"])
            if self.desc is primary:
                raise RuntimeError("primary unavailable")
            return AIMessage(content="backup answer")

    monkeypatch.setattr(rt.gateway, "chat", lambda desc, agent=None: Model(desc))
    answer = await rt.gateway.invoke(primary, [HumanMessage(content="hello")], fallback=fallback)
    assert answer.content == "backup answer" and calls == ["test-chat", "backup"]
    assert "backup" in rt.gateway.limits and "backup" in rt.gateway.breakers


async def test_disabled_backup_does_not_break_healthy_primary(rt):
    backup = await rt.db.add(
        t.models,
        {
            "provider_id": rt.test_model["provider_id"],
            "model_name": "disabled",
            "alias": "disabled_" + uuid.uuid4().hex,
            "type": "chat",
            "status": 0,
        },
    )
    graph = await rt.agent.react(
        {**rt.test_expert, "fallback_model_config_id": backup["id"]}, rt.test_user, "system"
    )
    answer = await graph.ainvoke({"messages": [HumanMessage(content="hello")]})
    assert answer["messages"][-1].content == "已完成"


async def test_embeddings_share_provider_concurrency_guard(rt, monkeypatch):
    from app.services import llm

    active = peak = 0

    class Embedder:
        def __init__(self, **kwargs):
            pass

        async def aembed_documents(self, texts):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(llm, "OpenAIEmbeddings", Embedder)
    gateway = Gateway(rt.db, rt.security, rt.cfg.model_copy(update={"llm_max_conns": 1}))
    results = await asyncio.gather(*(gateway.embed(["test"], rt.test_embed["id"]) for _ in range(3)))
    assert peak == 1 and len(results) == 3


async def test_stream_failure_after_output_does_not_switch_models(rt, monkeypatch):
    class BrokenStream(ScriptedModel):
        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            yield ChatGenerationChunk(message=AIMessageChunk(content="partial"))
            raise RuntimeError("broken stream")

    backup = await rt.db.add(
        t.models,
        {
            "provider_id": rt.test_model["provider_id"],
            "model_name": "backup",
            "alias": "backup_" + uuid.uuid4().hex,
            "type": "chat",
        },
    )
    calls = []

    def model(desc, agent=None):
        calls.append(desc.model["model_name"])
        return BrokenStream() if desc.model["model_name"] == "test-chat" else ScriptedModel()

    monkeypatch.setattr(rt.gateway, "chat", model)
    graph = await rt.agent.react(
        {**rt.test_expert, "fallback_model_config_id": backup["id"]}, rt.test_user, "system"
    )
    output = {}
    with pytest.raises(RuntimeError, match="broken stream"):
        async for _ in rt.agent.events(
            graph, [HumanMessage(content="hello")], "partial:" + uuid.uuid4().hex, output
        ):
            pass
    assert output["content"] == "partial" and calls == ["test-chat"]


async def test_optional_retrieval_failures_do_not_abort_chat_context(rt, monkeypatch):
    async def broken(*args):
        raise RuntimeError("optional store offline")

    monkeypatch.setattr(rt.rag, "retrieve", broken)
    monkeypatch.setattr(rt.memory, "recall", broken)
    system, refs, messages = await rt.agent.context(
        {**rt.test_expert, "kb_ids": [1], "memory_long_enabled": True},
        rt.test_user,
        "hello",
        [{"role": "user", "content": "hello"}],
    )
    assert system and refs == [] and messages[-1].content == "hello"


async def test_host_does_not_inject_its_system_prompt_into_expert(rt, monkeypatch):
    await rt.db.change(t.agents, rt.test_expert["id"], {"system_prompt": "expert-only persona"})
    original = rt.agent.react
    systems = {}

    async def capture(agent, user, system, checkpoint=None):
        systems[agent["name"]] = system
        return await original(agent, user, system, checkpoint)

    monkeypatch.setattr(rt.agent, "react", capture)
    await rt.agent.compile(
        {**rt.test_expert, "name": "host", "type": "host"}, rt.test_user, "host-only secret"
    )
    assert "expert-only persona" in systems[rt.test_expert["name"]]
    assert "host-only secret" not in systems[rt.test_expert["name"]]


async def test_worker_processes_upload_into_retrievable_document(rt, client):
    kb = (
        await client.post(
            "/api/v1/kbs", json={"name": "worker-etl", "embedding_config_id": rt.test_embed["id"]}
        )
    ).json()["data"]
    doc = (
        await client.post(
            f"/api/v1/kbs/{kb['id']}/documents",
            files={"file": ("worker.txt", b"Python migration keeps document indexing and retrieval.")},
        )
    ).json()["data"]
    job = (
        await rt.db.rows(
            t.jobs, t.jobs.c.kind == "doc_etl", t.jobs.c.payload["doc_id"].as_integer() == doc["id"]
        )
    )[0]
    await process(rt, {**job, "attempts": 1})
    assert (await rt.db.get(t.jobs, job["id"]))["status"] == "done"
    assert (await rt.db.get(t.documents, doc["id"]))["status"] == "ready"
    refs = await rt.rag.retrieve(rt.test_user["id"], kb["id"], "document indexing")
    assert refs and refs[0]["filename"] == "worker.txt"


async def test_workflow_knowledge_and_llm_nodes_share_the_python_runtime(rt, client):
    kb = (
        await client.post(
            "/api/v1/kbs", json={"name": "workflow-rag", "embedding_config_id": rt.test_embed["id"]}
        )
    ).json()["data"]
    doc = (
        await client.post(
            f"/api/v1/kbs/{kb['id']}/documents",
            files={
                "file": ("workflow.txt", b"Knowledge nodes feed source references into language model nodes.")
            },
        )
    ).json()["data"]
    await rt.rag.index(doc["id"])
    dsl = (
        "name: knowledge-and-model\ninput: [topic]\nnodes:\n"
        f"  - {{key: lookup, type: kb, kb_id: {kb['id']}, query: '{{{{topic}}}}'}}\n"
        "  - {key: write, type: llm, prompt: 'Summarize {{lookup.result}}'}\nout: write\n"
    )
    workflow = await rt.db.add(
        t.workflows, {"name": "workflow-rag", "creator_id": rt.test_user["id"], "dsl": dsl}
    )
    result = await rt.workflow.run(workflow, rt.test_user, {"topic": "source references"})
    assert result["status"] == "succeeded", result
    assert result["output"]["lookup"][0]["filename"] == "workflow.txt"
    assert result["output"]["result"] == "已完成"


async def test_memory_vectors_survive_runtime_restart_and_keep_user_scope(rt):
    fact = await rt.db.add(
        t.memories,
        {"user_id": rt.test_user["id"], "agent_id": rt.test_expert["id"], "content": "用户偏好使用 Python"},
    )
    other = await rt.db.add(
        t.users,
        {
            "username": "memory_other_" + uuid.uuid4().hex[:8],
            "email": uuid.uuid4().hex + "@test.local",
            "password_hash": "unused",
        },
    )
    foreign = await rt.db.add(t.memories, {"user_id": other["id"], "content": "用户偏好使用 Python"})
    await rt.memory.index(fact["id"])
    await rt.memory.index(foreign["id"])
    restarted = await Runtime(rt.cfg).start()
    restarted.gateway.embed = rt.gateway.embed
    try:
        recalled = await restarted.memory.recall(rt.test_user["id"], rt.test_expert["id"], fact["content"])
        assert [row["id"] for row in recalled] == [fact["id"]]
        assert (await rt.db.get(t.memories, fact["id"]))["hit_count"] == 1
    finally:
        await restarted.close()
        await rt.db.remove(t.users, other["id"])


async def test_workflow_approval_resumes_with_new_runtime(rt):
    workflow = await rt.db.add(
        t.workflows,
        {
            "name": "restart",
            "creator_id": rt.test_user["id"],
            "dsl": "name: restart\nnodes:\n  - {key: audit, type: human}\n  - {key: calc, type: tool, tool_code: calculator, args: {expression: '2+3'}}",
        },
    )
    run = await rt.workflow.run(workflow, rt.test_user, {})
    assert run["status"] == "waiting_approval"
    restarted = await Runtime(rt.cfg).start()
    try:
        result = await restarted.workflow.approve(run, rt.test_user, {"approved": True})
        assert result["status"] == "succeeded" and result["output"]["calc"] == "5"
    finally:
        await restarted.close()


async def test_legacy_tool_code_binding_can_create_and_run_agent(rt, client):
    created = await client.post(
        "/api/v1/agents",
        json={
            "name": "legacy bindings",
            "model_config_id": rt.test_model["id"],
            "tools": [{"tool_code": "calculator"}],
        },
    )
    assert created.status_code == 200, created.text
    response = await client.post(
        "/api/v1/chat/stream", json={"agent_id": created.json()["data"]["id"], "content": "计算2+3"}
    )
    assert "event: tool_result" in response.text and "5" in response.text
    assert "event: done" in response.text


async def test_http_tool_preserves_headers_suffix_allowlist_and_text_output(monkeypatch):
    from app.services import tools

    def respond(request):
        assert request.headers["X-Test"] == "preserved"
        return httpx.Response(404, text="<html><h1>Missing page</h1></html>")

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        tools.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    toolset = Tools(None, None, Settings(allowed_http_hosts=["example.test"]))
    result = await toolset.invoke(
        "http_client", {"url": "https://api.example.test/page", "headers": {"X-Test": "preserved"}}, {"id": 1}
    )
    assert result == {"status": 404, "content": "Missing page"}
    with pytest.raises(ValueError, match="域名"):
        await toolset.invoke("http_client", {"url": "https://evil-example.test/page"}, {"id": 1})


async def test_search_tool_preserves_twenty_results_and_snippets(monkeypatch):
    from app.services import tools

    def respond(request):
        assert request.url.params["language"] == "zh-CN"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": str(i), "url": "http://example.test", "content": "x" * 300} for i in range(25)
                ]
            },
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        tools.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await Tools(None, None, Settings()).invoke(
        "web_search", {"query": "test", "count": 20}, {"id": 1}
    )
    assert len(result) == 20 and len(result[0]["snippet"]) == 200


async def test_mcp_tools_obey_timeout_and_return_structured_errors(rt, monkeypatch):
    from langchain_core.tools import StructuredTool

    server = await rt.db.add(t.mcp_servers, {"name": "slow", "url": "http://slow.test/mcp"})
    tool = await rt.db.add(
        t.tools,
        {
            "code": "slow_" + uuid.uuid4().hex[:10],
            "name": "slow",
            "description": "slow MCP",
            "type": "mcp",
            "handler": "slow",
            "mcp_server_id": server["id"],
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            "timeout_ms": 1,
        },
    )

    async def slow(value: str):
        """Wait before returning input."""
        await asyncio.sleep(1)
        return value

    async def remote(_):
        return [StructuredTool.from_function(coroutine=slow)]

    monkeypatch.setattr(rt.tools, "remote_tools", remote)
    bound = await rt.tools.build([{"tool_id": tool["id"]}], rt.test_user)
    result = json.loads(await bound[0].ainvoke({"value": "test"}))
    assert result["status"] == "timeout" and result["error"]
    await rt.db.remove(t.mcp_servers, server["id"])


async def test_metrics_and_business_spans_cover_model_and_tool_calls(rt, client, monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app.core import observability

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        observability.trace, "get_tracer", lambda *args, **kwargs: provider.get_tracer("test")
    )
    try:
        response = await client.post(
            "/api/v1/chat/stream", json={"agent_id": rt.test_expert["id"], "content": "计算2+3"}
        )
        assert "event: done" in response.text
        metrics = (await client.get("/metrics")).text
        assert (
            "llm_requests_total" in metrics
            and "tool_calls_total" in metrics
            and "chat_first_token_seconds_count" in metrics
        )
        spans = {span.name for span in exporter.get_finished_spans()}
        assert {"llm.chat", "tool.calculator"} <= spans
    finally:
        provider.shutdown()


async def test_hybrid_failure_falls_back_to_dense_with_same_user_filter():
    from app.infrastructure.vector_store import Vectors

    class Client:
        def has_collection(self, name):
            assert name == "test_namespace_kb"
            return True

        def hybrid_search(self, **kwargs):
            raise RuntimeError("BM25 unavailable")

        def search(self, **kwargs):
            assert kwargs["collection_name"] == "test_namespace_kb"
            assert kwargs["filter"] == "user_id == 7"
            return [[{"id": 42, "distance": 0.9}]]

    vectors = Vectors("unused", namespace="test_namespace")
    vectors.client = Client()
    assert await vectors.search("kb", [1, 0], "query", "user_id == 7") == [{"id": 42, "distance": 0.9}]


def test_python_migration_refuses_go_database_without_changing_its_data(isolated_services):
    import psycopg
    from psycopg import sql
    from sqlalchemy.engine import make_url

    cfg = Settings()
    legacy_database = "nx_legacy_check_" + uuid.uuid4().hex[:16]
    original = make_url(cfg.database_url)
    legacy_url = original.set(database=legacy_database)
    with psycopg.connect(cfg.checkpoint_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(legacy_database)))
        try:
            with psycopg.connect(
                legacy_url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True
            ) as legacy:
                legacy.execute("CREATE TABLE schema_migrations (version bigint, dirty boolean)")
                legacy.execute("CREATE TABLE legacy_marker (value text)")
                legacy.execute("INSERT INTO legacy_marker VALUES ('original data')")
            result = subprocess.run(
                [sys.executable, "-m", "app.cli", "migrate"],
                cwd=Path(__file__).parents[1],
                env={
                    **os.environ,
                    "NX_DATABASE_URL": legacy_url.render_as_string(hide_password=False),
                    "PYTHONIOENCODING": "utf-8",
                },
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            assert result.returncode != 0 and "Go" in result.stderr and "Python" in result.stderr
            with psycopg.connect(
                legacy_url.set(drivername="postgresql").render_as_string(hide_password=False)
            ) as legacy:
                assert legacy.execute("SELECT value FROM legacy_marker").fetchone()[0] == "original data"
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(legacy_database)))
