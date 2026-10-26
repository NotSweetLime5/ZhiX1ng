import hashlib
import uuid

import httpx
import pytest_asyncio
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app import models as t
from app.core.config import Settings
from app.core.security import passwords
from app.main import app
from app.runtime import Runtime


class ScriptedModel(BaseChatModel):
    """Tests exercise the real LangChain/LangGraph runtime without paid model calls."""

    expert_id: int = 0
    tool_names: list[str] = []

    @property
    def _llm_type(self):
        return "scripted-test"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(
            update={"tool_names": [x.name if hasattr(x, "name") else x["function"]["name"] for x in tools]}
        )

    def _response(self, messages):
        last = messages[-1]
        question = str(last.content)
        if question.startswith("选择最合适"):
            return AIMessage(content=str(self.expert_id))
        if "返回JSON" in question and "depends_on" in question:
            return AIMessage(
                content='{"goal":"计算","steps":[{"id":"s1","description":"计算2+3","depends_on":[]}]}'
            )
        if isinstance(last, ToolMessage):
            return AIMessage(content="计算结果是 " + str(last.content))
        if "calculator" in self.tool_names and ("2+3" in question or "计算" in question):
            return AIMessage(
                content="",
                tool_calls=[{"id": "call-calculator", "name": "calculator", "args": {"expression": "2+3"}}],
            )
        return AIMessage(
            content="已完成", usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._response(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        response = self._response(messages)
        if response.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "calculator",
                            "args": '{"expression":"2+3"}',
                            "id": "call-calculator",
                            "index": 0,
                        }
                    ],
                )
            )
        else:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=response.content, usage_metadata=response.usage_metadata)
            )


@pytest_asyncio.fixture
async def rt(monkeypatch):
    suffix = uuid.uuid4().hex[:12]
    cfg = Settings(default_chat="test_chat_" + suffix, default_embedding="test_embed_" + suffix)
    runtime = await Runtime(cfg).start()
    user = await runtime.db.add(
        t.users,
        {
            "username": "test_" + suffix,
            "email": suffix + "@test.local",
            "role": "admin",
            "password_hash": passwords.hash("password123"),
        },
    )
    provider = await runtime.db.add(
        t.providers,
        {
            "code": "test_" + suffix,
            "name": "Test",
            "base_url": "http://test.invalid/v1",
            "api_key": runtime.security.encrypt("test-key"),
        },
    )
    model = await runtime.db.add(
        t.models,
        {
            "provider_id": provider["id"],
            "model_name": "test-chat",
            "alias": cfg.default_chat,
            "type": "chat",
            "is_default": True,
        },
    )
    embed = await runtime.db.add(
        t.models,
        {
            "provider_id": provider["id"],
            "model_name": "test-embed",
            "alias": cfg.default_embedding,
            "type": "embedding",
            "is_default": True,
        },
    )
    tool = (await runtime.db.rows(t.tools, t.tools.c.code == "calculator", limit=1))[0]
    expert = await runtime.db.add(
        t.agents,
        {
            "name": "Test Expert",
            "creator_id": user["id"],
            "model_config_id": model["id"],
            "description": "测试专家",
            "tools": [{"tool_id": tool["id"]}],
        },
    )
    monkeypatch.setattr(runtime.gateway, "chat", lambda *args, **kw: ScriptedModel(expert_id=expert["id"]))

    async def embed_texts(texts, ident=0):
        return [[(b - 127) / 127 for b in hashlib.sha256(text.encode()).digest()[:8]] for text in texts]

    async def rerank(*args):
        return None

    monkeypatch.setattr(runtime.gateway, "embed", embed_texts)
    monkeypatch.setattr(runtime.gateway, "rerank", rerank)
    runtime.test_user, runtime.test_model, runtime.test_expert, runtime.test_embed = (
        user,
        model,
        expert,
        embed,
    )
    app.state.runtime = runtime
    try:
        yield runtime
    finally:
        kbs = await runtime.db.rows(t.kbs, t.kbs.c.user_id == user["id"], limit=10000)
        for kb in kbs:
            docs = await runtime.db.rows(t.documents, t.documents.c.kb_id == kb["id"], limit=10000)
            for doc in docs:
                await runtime.objects.remove(doc["object_key"])
            await runtime.vectors.drop(kb["milvus_collection"])
        await runtime.db.remove(t.users, user["id"])
        await runtime.db.remove(t.providers, provider["id"])
        await runtime.close()


@pytest_asyncio.fixture
async def client(rt):
    tokens = await rt.security.tokens(rt.test_user)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer " + tokens["access_token"]},
    ) as client:
        yield client
