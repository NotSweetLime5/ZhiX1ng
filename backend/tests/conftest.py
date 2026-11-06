import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app import models as t
from app.core.config import Settings
from app.core.security import passwords
from app.main import app
from app.runtime import Runtime


@pytest.fixture(autouse=True)
def bypass_proxies_for_local_test_services(monkeypatch):
    # MCP test servers run on loopback even when the workstation uses an HTTP proxy.
    existing = os.environ.get("no_proxy", os.environ.get("NO_PROXY", ""))
    bypass = ",".join(filter(None, [existing, "localhost", "127.0.0.1", "::1", "test"]))
    monkeypatch.setenv("NO_PROXY", bypass)
    monkeypatch.setenv("no_proxy", bypass)


@pytest.fixture(scope="session")
def isolated_services(tmp_path_factory):
    """Bootstrap a new Python database and isolate test objects/vectors from user data."""
    import psycopg
    from minio import Minio
    from psycopg import sql
    from pymilvus import MilvusClient
    from redis import Redis
    from sqlalchemy.engine import make_url

    cfg = Settings()
    suffix = uuid.uuid4().hex[:16]
    database = "nx_test_" + suffix
    namespace = "nx_test_" + suffix
    bucket = "nx-test-" + suffix
    overrides = {
        "ZHIXING_DATABASE_URL": make_url(cfg.database_url)
        .set(database=database)
        .render_as_string(hide_password=False),
        "ZHIXING_MILVUS_NAMESPACE": namespace,
        "ZHIXING_MINIO_BUCKET": bucket,
        "ZHIXING_FILE_ROOT": str(tmp_path_factory.mktemp("tool-files")),
        "ZHIXING_ADMIN_PASSWORD": uuid.uuid4().hex,
        "ZHIXING_REDIS_NAMESPACE": namespace,
        "ZHIXING_JWT_SECRET": uuid.uuid4().hex,
        "ZHIXING_SECRET_KEY": uuid.uuid4().hex,
    }
    original = {key: os.environ.get(key) for key in overrides}
    with psycopg.connect(cfg.checkpoint_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            os.environ.update(overrides)
            for command in ("migrate", "seed"):
                result = subprocess.run(
                    [sys.executable, "-m", "app.cli", command],
                    cwd=Path(__file__).parents[1],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                assert result.returncode == 0, f"Isolated Python {command} failed: {result.stderr}"
            yield
        finally:
            try:
                vectors = MilvusClient(uri=cfg.milvus_uri, db_name=cfg.milvus_database)
                try:
                    for collection in vectors.list_collections():
                        if collection.startswith(namespace + "_"):
                            vectors.drop_collection(collection)
                finally:
                    vectors.close()
                objects = Minio(
                    cfg.minio_endpoint,
                    access_key=cfg.minio_access_key,
                    secret_key=cfg.minio_secret_key,
                    secure=cfg.minio_secure,
                )
                if objects.bucket_exists(bucket):
                    for obj in objects.list_objects(bucket, recursive=True):
                        objects.remove_object(bucket, obj.object_name)
                    objects.remove_bucket(bucket)
                tokens = Redis.from_url(cfg.redis_url)
                try:
                    keys = list(tokens.scan_iter(match=namespace + ":*"))
                    if keys:
                        tokens.delete(*keys)
                finally:
                    tokens.close()
            finally:
                for key, value in original.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


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
async def rt(monkeypatch, isolated_services):
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
