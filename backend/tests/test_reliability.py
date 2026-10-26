import json
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from langchain_core.messages import HumanMessage
from sqlalchemy import text

from app import models as t
from app.schemas import ChatInput
from app.services import chat
from app.worker import claim


async def test_session_ownership(rt, client):
    other = await rt.db.add(
        t.users,
        {
            "username": "other_" + uuid.uuid4().hex[:8],
            "email": uuid.uuid4().hex + "@test.local",
            "password_hash": "unused",
        },
    )
    session = await rt.db.add(t.sessions, {"id": str(uuid.uuid4()), "user_id": other["id"]})
    try:
        assert (await client.get(f"/api/v1/sessions/{session['id']}/messages")).status_code == 404
        assert (
            await client.post("/api/v1/chat/stream", json={"session_id": session["id"], "content": "hello"})
        ).status_code == 400
    finally:
        await rt.db.remove(t.users, other["id"])


async def test_disconnected_stream_persists_interrupted_message(rt):
    request = ChatInput(agent_id=rt.test_expert["id"], content="计算2+3")
    agent, session = await chat.prepare(rt, rt.test_user, request)
    generator = chat.stream(rt, rt.test_user, request, agent, session)
    frame = await anext(generator)
    assert frame.startswith("event: meta")
    await generator.aclose()
    rows = await rt.db.rows(t.messages, t.messages.c.session_id == session["id"], ascending=True)
    assert len(rows) == 2 and rows[-1]["status"] == 2
    async with rt.db.engine.connect() as conn:
        locked = await conn.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:id,0))"), {"id": session["id"]}
        )
        assert locked
        await conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:id,0))"), {"id": session["id"]})


async def test_worker_last_expired_lease_becomes_failed(rt):
    job = await rt.db.add(
        t.jobs,
        {
            "kind": "test",
            "payload": {},
            "status": "running",
            "attempts": 3,
            "lease_until": t.now() - timedelta(seconds=10),
        },
    )
    await claim(rt)
    row = await rt.db.get(t.jobs, job["id"])
    assert row["status"] == "failed"
    await rt.db.remove(t.jobs, job["id"])


async def test_plan_replans_once_on_failed_execution(rt, monkeypatch):
    original_react = rt.agent.react
    executions = 0

    class FailureThenSuccess:
        async def ainvoke(self, input_, config=None):
            nonlocal executions
            executions += 1
            if executions == 1:
                raise RuntimeError("test execution failure")
            from langchain_core.messages import AIMessage

            return {"messages": [AIMessage(content="5")]}

    async def react(agent, user, system, checkpoint=None):
        if checkpoint is None:
            return FailureThenSuccess()
        return await original_react(agent, user, system, checkpoint)

    monkeypatch.setattr(rt.agent, "react", react)
    agent = {**rt.test_expert, "config": {"execution_mode": "plan"}}
    graph = await rt.agent.compile(agent, rt.test_user, "系统规则")
    output = {}
    events = [
        event
        async for event in rt.agent.events(
            graph, [HumanMessage(content="计算2+3")], "replan:" + uuid.uuid4().hex, output
        )
    ]
    assert sum(name == "plan" for name, _ in events) == 2
    assert executions == 2


async def test_real_chatopenai_client_with_mock_http(rt, monkeypatch):
    """Exercises the OpenAI-compatible SDK boundary, not just a BaseChatModel fake."""
    import httpx
    from langchain_openai import ChatOpenAI

    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "test-chat",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "SDK 已接通"},
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        model = ChatOpenAI(
            model="test-chat",
            api_key="test-key",
            base_url="http://test/v1",
            http_async_client=http,
            streaming=False,
            disable_streaming=True,
        )
        monkeypatch.setattr(rt.gateway, "chat", lambda *args, **kwargs: model)
        graph = await rt.agent.react(rt.test_expert, rt.test_user, "系统规则")
        result = await graph.ainvoke({"messages": [HumanMessage(content="hello")]})
        assert result["messages"][-1].content == "SDK 已接通"
        assert calls[0]["tools"][0]["function"]["name"] == "calculator"


async def test_chat_lock_released_when_persistence_fails(rt, monkeypatch):
    request = ChatInput(agent_id=rt.test_expert["id"], content="hello")
    agent, session = await chat.prepare(rt, rt.test_user, request)
    generator = chat.stream(rt, rt.test_user, request, agent, session)
    await anext(generator)

    @asynccontextmanager
    async def broken_transaction(self):
        raise RuntimeError("test persistence failure")
        yield

    with monkeypatch.context() as patch:
        patch.setattr(type(rt.db.engine), "begin", broken_transaction)
        with pytest.raises(RuntimeError, match="persistence failure"):
            await generator.aclose()
    async with rt.db.engine.connect() as conn:
        assert await conn.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:id,0))"), {"id": session["id"]}
        )
        await conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:id,0))"), {"id": session["id"]})


async def test_deleting_document_during_parsing_is_not_undone(rt, client, monkeypatch):
    kb = (
        await client.post(
            "/api/v1/kbs", json={"name": "删除竞争", "embedding_config_id": rt.test_embed["id"]}
        )
    ).json()["data"]
    doc = (
        await client.post(f"/api/v1/kbs/{kb['id']}/documents", files={"file": ("test.txt", b"hello")})
    ).json()["data"]
    original_get = rt.objects.get

    async def deleting_get(key):
        data = await original_get(key)
        await rt.rag.delete_doc(rt.test_user["id"], kb["id"], doc["id"])
        return data

    monkeypatch.setattr(rt.objects, "get", deleting_get)
    await rt.rag.index(doc["id"])
    assert (await rt.db.get(t.documents, doc["id"]))["status"] == "deleted"
    assert await rt.db.rows(t.chunks, t.chunks.c.document_id == doc["id"]) == []
    await rt.rag.cleanup_doc(doc["id"])


async def test_memory_updates_forgets_and_rejects_out_of_scope_ids(rt, monkeypatch):
    from langchain_core.messages import AIMessage

    first = await rt.db.add(
        t.memories, {"user_id": rt.test_user["id"], "agent_id": rt.test_expert["id"], "content": "喜欢茶"}
    )
    second = await rt.db.add(
        t.memories, {"user_id": rt.test_user["id"], "agent_id": rt.test_expert["id"], "content": "旧地址"}
    )
    operations = [
        {"op": "UPDATE", "id": first["id"], "content": "喜欢咖啡"},
        {"op": "DELETE", "id": second["id"]},
        {"op": "ADD", "content": "使用Python"},
        {"op": "NOOP"},
    ]

    async def invoke(*args, **kwargs):
        return AIMessage(content=json.dumps(operations))

    monkeypatch.setattr(rt.gateway, "invoke", invoke)
    assert await rt.memory.extract(rt.test_user["id"], rt.test_expert["id"], []) == 3
    assert (await rt.db.get(t.memories, first["id"]))["content"] == "喜欢咖啡"
    assert (await rt.db.get(t.memories, second["id"]))["status"] == 2
    operations[:] = [{"op": "ADD", "content": "不应被写入"}, {"op": "DELETE", "id": -1}]
    with pytest.raises(ValueError, match="范围"):
        await rt.memory.extract(rt.test_user["id"], rt.test_expert["id"], [])
    assert not await rt.db.rows(
        t.memories, t.memories.c.user_id == rt.test_user["id"], t.memories.c.content == "不应被写入"
    )
