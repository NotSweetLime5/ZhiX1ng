import asyncio
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from sqlalchemy import select

from app import models as tables
from app.core.observability import operation, record_usage


class CompatibleChatOpenAI(ChatOpenAI):
    """Retain the reasoning_content extension used by the original Go adapter.

    Generic ChatOpenAI deliberately drops provider-specific fields. Preserve the
    field on both incoming responses and the next assistant/tool request so an
    OpenAI-compatible reasoning model can complete a multi-step tool round trip.
    """

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        raw = response if isinstance(response, dict) else response.model_dump()
        for generation, choice in zip(result.generations, raw.get("choices", []), strict=False):
            reasoning = choice.get("message", {}).get("reasoning_content")
            if isinstance(reasoning, str):
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        result = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        if result is not None and choices:
            reasoning = (choices[0].get("delta") or {}).get("reasoning_content")
            if isinstance(reasoning, str):
                result.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        for message, raw in zip(messages, payload.get("messages", []), strict=False):
            reasoning = message.additional_kwargs.get("reasoning_content")
            if isinstance(message, AIMessage) and isinstance(reasoning, str):
                raw["reasoning_content"] = reasoning
        return payload


class CircuitBreaker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.window = deque(maxlen=cfg.llm_circuit_window)
        self.open_until = 0

    def allow(self):
        return time.monotonic() >= self.open_until

    def record(self, success):
        self.window.append(success)
        if (
            len(self.window) == self.window.maxlen
            and self.window.count(False) / len(self.window) >= self.cfg.llm_circuit_error_rate
        ):
            self.open_until = time.monotonic() + self.cfg.llm_circuit_open
            self.window.clear()


@dataclass
class Descriptor:
    model: dict
    provider: dict
    api_key: str


class Gateway:
    def __init__(self, db, security, cfg):
        self.db, self.security, self.cfg = db, security, cfg
        self.limits = {}
        self.breakers = {}

    @asynccontextmanager
    async def guard(self, desc, name="llm.chat"):
        code = desc.provider["code"]
        breaker = self.breakers.setdefault(code, CircuitBreaker(self.cfg))
        sem = self.limits.setdefault(code, asyncio.Semaphore(self.cfg.llm_max_conns))
        with operation(name, model=desc.model["model_name"]):
            if not breaker.allow():
                raise RuntimeError("模型供应商熔断中")
            try:
                async with asyncio.timeout(self.cfg.step_timeout), sem:
                    yield
            except Exception:
                breaker.record(False)
                raise
            else:
                breaker.record(True)

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
                async with self.db.engine.connect() as conn:
                    rows = (
                        (
                            await conn.execute(
                                select(tables.models)
                                .join(tables.providers, tables.models.c.provider_id == tables.providers.c.id)
                                .where(
                                    tables.models.c.type == kind,
                                    tables.models.c.status == 1,
                                    tables.providers.c.status == 1,
                                )
                                .order_by(
                                    tables.models.c.is_default.desc(),
                                    tables.models.c.priority,
                                    tables.models.c.id,
                                )
                                .limit(1)
                            )
                        )
                        .mappings()
                        .all()
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

    async def fallback(self, ident):
        if not ident:
            return None
        try:
            return await self.resolve(ident)
        except Exception:
            logging.getLogger(__name__).warning(
                "Fallback model %s unavailable; retaining primary", ident, exc_info=True
            )
            return None

    def chat(self, desc, agent=None):
        agent = agent or {}
        return CompatibleChatOpenAI(
            model=desc.model["model_name"],
            base_url=desc.provider["base_url"],
            api_key=desc.api_key,
            temperature=float(agent.get("temperature", 0.7)),
            top_p=float(agent.get("top_p", 0.9)),
            max_tokens=agent.get("max_tokens", desc.model["max_output"]),
            timeout=self.cfg.step_timeout,
            max_retries=self.cfg.llm_retries,
            stream_usage=True,
            use_responses_api=False,
            metadata={"nx_model_id": desc.model.get("id"), "nx_model_name": desc.model["model_name"]},
        )

    async def invoke(self, desc, messages, config=None, agent=None, fallback=None):
        try:
            async with self.guard(desc):
                result = await self.chat(desc, agent).ainvoke(messages, config=config)
                record_usage(desc, result)
                return result
        except Exception:
            if fallback is None:
                raise
            async with self.guard(fallback):
                result = await self.chat(fallback, agent).ainvoke(messages, config=config)
                record_usage(fallback, result)
                return result

    async def embed(self, texts, ident=0):
        desc = await self.resolve(ident, "embedding")
        embedder = OpenAIEmbeddings(
            model=desc.model["model_name"],
            base_url=desc.provider["base_url"],
            api_key=desc.api_key,
            check_embedding_ctx_length=False,
            chunk_size=16,
            request_timeout=self.cfg.step_timeout,
            max_retries=self.cfg.llm_retries,
        )
        async with self.guard(desc, "llm.embed"):
            return await embedder.aembed_documents(texts)

    async def rerank(self, query, docs):
        candidates = await self.db.rows(
            tables.models, tables.models.c.type == "rerank", tables.models.c.status == 1, limit=1
        )
        if not candidates:
            return None
        desc = await self.resolve(candidates[0]["id"], "rerank")
        async with self.guard(desc, "llm.rerank"), httpx.AsyncClient(timeout=self.cfg.step_timeout) as client:
            for attempt in range(self.cfg.llm_retries + 1):
                try:
                    response = await client.post(
                        desc.provider["base_url"].rstrip("/") + "/rerank",
                        headers={"Authorization": f"Bearer {desc.api_key}"},
                        json={"model": desc.model["model_name"], "query": query, "documents": docs},
                    )
                    response.raise_for_status()
                    return response.json()["results"]
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    transient = (
                        not isinstance(exc, httpx.HTTPStatusError)
                        or exc.response.status_code == 429
                        or exc.response.status_code >= 500
                    )
                    if not transient or attempt == self.cfg.llm_retries:
                        raise
                    await asyncio.sleep(0.25 * 2**attempt)
