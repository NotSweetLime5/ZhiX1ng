"""Idempotent local setup using the same encrypted catalog and upload pipeline as the API."""

import hashlib
import io
from pathlib import Path

from sqlalchemy import insert, select, text, update
from starlette.datastructures import UploadFile

from app import models as t
from app.schemas.knowledge import KBInput
from app.services.knowledge import create_kb, upload

KB_NAME = "大模型资料库"
AGENT_NAME = "大模型资料助手"


async def configure_models(rt, specs):
    configured = {}
    async with rt.db.engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(7171718)"))
        for kind in {spec.kind for spec in specs}:
            await conn.execute(update(t.models).where(t.models.c.type == kind).values(is_default=False))
        for spec in specs:
            provider = (
                (await conn.execute(select(t.providers).where(t.providers.c.code == spec.code)))
                .mappings()
                .first()
            )
            values = {
                "name": spec.provider_name,
                "base_url": spec.base_url,
                "api_key": rt.security.encrypt(spec.api_key),
                "status": 1,
            }
            if provider:
                await conn.execute(
                    update(t.providers).where(t.providers.c.id == provider["id"]).values(**values)
                )
                provider_id = provider["id"]
            else:
                provider_id = await conn.scalar(
                    insert(t.providers).values(code=spec.code, **values).returning(t.providers.c.id)
                )
            current = (
                (
                    await conn.execute(
                        select(t.models).where(
                            t.models.c.provider_id == provider_id,
                            t.models.c.model_name == spec.model_name,
                            t.models.c.type == spec.kind,
                        )
                    )
                )
                .mappings()
                .first()
            )
            values = {
                "alias": spec.model_name,
                "status": 1,
                "is_default": spec.code in {"deepseek", "siliconflow"},
                "max_output": 4096 if spec.kind == "chat" else 512,
                "capabilities": ["function_call"] if spec.kind == "chat" else [],
            }
            if current:
                await conn.execute(update(t.models).where(t.models.c.id == current["id"]).values(**values))
                model_id = current["id"]
            else:
                model_id = await conn.scalar(
                    insert(t.models)
                    .values(provider_id=provider_id, model_name=spec.model_name, type=spec.kind, **values)
                    .returning(t.models.c.id)
                )
            configured[spec.code] = model_id
        # Update the seed presets still pointing at the original DeepSeek placeholder model.
        old_ids = (
            select(t.models.c.id)
            .join(t.providers, t.models.c.provider_id == t.providers.c.id)
            .where(t.providers.c.code == "deepseek", t.models.c.model_name == "deepseek-chat")
        )
        await conn.execute(
            update(t.agents)
            .where(t.agents.c.is_preset.is_(True), t.agents.c.model_config_id.in_(old_ids))
            .values(model_config_id=configured["deepseek"])
        )
    return configured


def save_default_aliases(specs, env_path=Path(".env")):
    defaults = {
        "NX_DEFAULT_CHAT": next(s.model_name for s in specs if s.code == "deepseek"),
        "NX_DEFAULT_EMBEDDING": next(s.model_name for s in specs if s.kind == "embedding"),
    }
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updated = []
    for line in lines:
        key = line.partition("=")[0].strip()
        updated.append(f"{key}={defaults.pop(key)}" if key in defaults else line)
    updated.extend(f"{key}={value}" for key, value in defaults.items())
    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


async def setup_knowledge(rt, user, configured):
    existing = await rt.db.rows(
        t.kbs, t.kbs.c.user_id == user["id"], t.kbs.c.name == KB_NAME, t.kbs.c.status == "active", limit=1
    )
    if existing:
        kb = existing[0]
        if kb["embedding_config_id"] != configured["siliconflow"]:
            raise ValueError("已有同名知识库使用其他 Embedding；请新建知识库以避免混合向量维度")
    else:
        kb = await create_kb(
            rt,
            user,
            KBInput(
                name=KB_NAME,
                description="本机大模型资料：提示词、微调、RAG、Agent、Skills 与幻觉。",
                embedding_config_id=configured["siliconflow"],
                chunk_size=800,
                chunk_overlap=120,
            ),
        )
    agents = await rt.db.rows(
        t.agents, t.agents.c.creator_id == user["id"], t.agents.c.name == AGENT_NAME, limit=1
    )
    values = {
        "name": AGENT_NAME,
        "description": "根据大模型资料库回答问题，并标注文件与页码。",
        "type": "expert",
        "model_config_id": configured["deepseek"],
        "fallback_model_config_id": configured["qwen"],
        "system_prompt": "你是大模型资料助手。优先依据提供的参考资料回答，使用[1]、[2]等编号标注来源；"
        "资料不足时明确说明，不编造出处。默认简短回答，可按用户要求详细解释。",
        "kb_ids": [kb["id"]],
        "tools": [],
        "max_tokens": 2048,
        "status": 1,
    }
    if agents:
        agent = await rt.db.change(t.agents, agents[0]["id"], values)
    else:
        agent = await rt.db.add(t.agents, {**values, "creator_id": user["id"]})
    return kb, agent


async def import_document(rt, user, kb, path):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    existing = await rt.db.rows(
        t.documents,
        t.documents.c.kb_id == kb["id"],
        t.documents.c.status != "deleted",
        t.documents.c.metadata["source_sha256"].astext == digest,
        limit=1,
    )
    if existing:
        failed = await rt.db.rows(
            t.jobs,
            t.jobs.c.kind == "doc_etl",
            t.jobs.c.status == "failed",
            t.jobs.c.payload["doc_id"].as_integer() == existing[0]["id"],
            limit=100,
        )
        for job in failed:
            await rt.db.change(
                t.jobs, job["id"], {"status": "pending", "attempts": 0, "lease_until": None, "error": ""}
            )
        return existing[0], False
    file = UploadFile(io.BytesIO(data), filename=path.name)
    try:
        doc = await upload(rt, user, kb["id"], file)
    finally:
        await file.close()
    doc = await rt.db.change(t.documents, doc["id"], {"metadata": {"source_sha256": digest}})
    return doc, True
