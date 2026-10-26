import asyncio
import time
from dataclasses import dataclass

import httpx
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app import models as tables


@dataclass
class Descriptor:
    model: dict
    provider: dict
    api_key: str


class Gateway:
    def __init__(self, db, security, cfg):
        self.db, self.security, self.cfg = db, security, cfg
        self.limits = {}
        self.failures = {}

    async def resolve(self, ident=0, kind="chat", alias=None):
        if ident:
            model = await self.db.get(tables.models, ident)
        else:
            name = alias or (self.cfg.default_chat if kind == "chat" else self.cfg.default_embedding)
            rows = await self.db.rows(
                tables.models,
                tables.models.c.type == kind,
                tables.models.c.status == 1,
                tables.models.c.alias == name,
                limit=1,
            )
            if not rows:
                rows = await self.db.rows(
                    tables.models,
                    tables.models.c.type == kind,
                    tables.models.c.status == 1,
                    tables.models.c.is_default.is_(True),
                    limit=1,
                )
            model = rows[0] if rows else None
        if not model or model["status"] != 1 or model["type"] != kind:
            raise ValueError(f"未配置可用的 {kind} 模型")
        provider = await self.db.get(tables.providers, model["provider_id"])
        if not provider or provider["status"] != 1:
            raise ValueError("模型供应商不可用")
        key = self.security.decrypt(provider["api_key"])
        if not key and provider["code"] != "ollama":
            raise ValueError("请先在模型配置中填写供应商 API Key")
        return Descriptor(model, provider, key or "ollama")

    def chat(self, desc, agent=None):
        agent = agent or {}
        return ChatOpenAI(
            model=desc.model["model_name"],
            base_url=desc.provider["base_url"],
            api_key=desc.api_key,
            temperature=float(agent.get("temperature", 0.7)),
            top_p=float(agent.get("top_p", 0.9)),
            max_tokens=agent.get("max_tokens", desc.model["max_output"]),
            timeout=self.cfg.step_timeout,
            max_retries=2,
            stream_usage=True,
        )

    async def invoke(self, desc, messages, config=None, agent=None):
        code = desc.provider["code"]
        failures, opened = self.failures.get(code, (0, 0))
        if opened > time.monotonic():
            raise RuntimeError("模型供应商熔断中")
        sem = self.limits.setdefault(code, asyncio.Semaphore(16))
        async with sem:
            try:
                async with asyncio.timeout(self.cfg.step_timeout):
                    result = await self.chat(desc, agent).ainvoke(messages, config=config)
                self.failures[code] = (0, 0)
                return result
            except Exception:
                failures += 1
                self.failures[code] = (failures, time.monotonic() + 60 if failures >= 5 else 0)
                raise

    async def embed(self, texts, ident=0):
        desc = await self.resolve(ident, "embedding")
        embedder = OpenAIEmbeddings(
            model=desc.model["model_name"],
            base_url=desc.provider["base_url"],
            api_key=desc.api_key,
            check_embedding_ctx_length=False,
            chunk_size=16,
            request_timeout=self.cfg.step_timeout,
            max_retries=2,
        )
        return await embedder.aembed_documents(texts)

    async def rerank(self, query, docs):
        candidates = await self.db.rows(
            tables.models, tables.models.c.type == "rerank", tables.models.c.status == 1, limit=1
        )
        if not candidates:
            return None
        desc = await self.resolve(candidates[0]["id"], "rerank")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                desc.provider["base_url"].rstrip("/") + "/rerank",
                headers={"Authorization": f"Bearer {desc.api_key}"},
                json={"model": desc.model["model_name"], "query": query, "documents": docs},
            )
            response.raise_for_status()
            return response.json()["results"]
