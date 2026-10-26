import asyncio
import logging

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete, func, insert, select, update

from app import models as t
from app.core.observability import operation
from app.infrastructure.documents import load_document
from app.repositories.locking import resource_lock

log = logging.getLogger(__name__)


class RAG:
    def __init__(self, db, gateway, vectors, objects, cfg=None):
        self.db, self.gateway, self.vectors, self.objects = db, gateway, vectors, objects
        self.cfg = cfg

    async def index(self, doc_id):
        async with resource_lock(self.db, f"document:{doc_id}"):
            await self._index(doc_id)

    async def _index(self, doc_id):
        doc = await self.db.get(t.documents, doc_id)
        if not doc or doc["status"] in {"deleted", "ready"}:
            return
        kb = await self.db.get(t.kbs, doc["kb_id"])
        if not kb or kb["status"] != "active":
            return

        async def advance(status):
            async with self.db.engine.begin() as conn:
                result = await conn.execute(
                    update(t.documents)
                    .where(t.documents.c.id == doc_id, t.documents.c.status != "deleted")
                    .values(status=status, error="")
                )
                return result.rowcount > 0

        if not await advance("parsing"):
            return
        loaded = await asyncio.to_thread(
            load_document, doc["filename"], await self.objects.get(doc["object_key"])
        )
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=kb["chunk_size"],
            chunk_overlap=kb["chunk_overlap"],
            separators=["\n\n", "\n", "。", "！", "？", " ", ""],
        )
        parts = await asyncio.to_thread(splitter.split_documents, loaded)
        parts = [p for p in parts if p.page_content.strip()]
        if not parts:
            raise ValueError("文档未提取到文本；扫描 PDF 需要先做 OCR")
        if not await advance("chunking"):
            return
        # Retry indexes reuse persisted chunk IDs. Partial upserts are replaced, never duplicated.
        existing = await self.db.rows(
            t.chunks, t.chunks.c.document_id == doc_id, limit=100000, ascending=True
        )
        if not existing:
            async with self.db.engine.begin() as conn:
                existing = []
                for i, part in enumerate(parts):
                    row = (
                        (
                            await conn.execute(
                                insert(t.chunks)
                                .values(
                                    kb_id=kb["id"],
                                    document_id=doc_id,
                                    seq=i,
                                    content=part.page_content,
                                    token_count=max(1, len(part.page_content) // 2),
                                    meta=part.metadata,
                                )
                                .returning(t.chunks)
                            )
                        )
                        .mappings()
                        .one()
                    )
                    existing.append(dict(row))
        if not await advance("embedding"):
            return
        batch_size = self.cfg.rag_batch_embed if self.cfg else 64
        for offset in range(0, len(existing), batch_size):
            latest = await self.db.get(t.documents, doc_id)
            if not latest or latest["status"] == "deleted":
                return
            batch = existing[offset : offset + batch_size]
            vecs = await self.gateway.embed([c["content"] for c in batch], kb["embedding_config_id"])
            await self.vectors.upsert(
                kb["milvus_collection"],
                [
                    {
                        "id": c["id"],
                        "doc_id": doc_id,
                        "user_id": kb["user_id"],
                        "agent_id": 0,
                        "text": c["content"],
                        "dense": v,
                    }
                    for c, v in zip(batch, vecs, strict=True)
                ],
            )
        async with self.db.engine.begin() as conn:
            await conn.execute(
                update(t.documents)
                .where(t.documents.c.id == doc_id, t.documents.c.status != "deleted")
                .values(
                    status="ready",
                    chunk_count=len(existing),
                    token_count=sum(c["token_count"] for c in existing),
                )
            )

    async def retrieve(self, user_id, kb_id, query, top_k=None):
        top_k = top_k or (self.cfg.rag_final_top_k if self.cfg else 5)
        kb = await self.db.get(t.kbs, kb_id, t.kbs.c.user_id == user_id, t.kbs.c.status == "active")
        if not kb:
            raise ValueError("知识库不存在或无权访问")
        ready = await self.db.rows(
            t.documents, t.documents.c.kb_id == kb_id, t.documents.c.status == "ready", limit=100000
        )
        if not ready:
            return []
        ids = [d["id"] for d in ready]
        vector = (await self.gateway.embed([query], kb["embedding_config_id"]))[0]
        with operation("rag.retrieve", stage="fused"):
            hits = await self.vectors.search(
                kb["milvus_collection"],
                vector,
                query,
                f"user_id == {user_id} and doc_id in {ids}",
                max(top_k, self.cfg.rag_fused_top_n if self.cfg else 15),
            )
        refs = []
        docs = {d["id"]: d for d in ready}
        for hit in hits:
            chunk = await self.db.get(t.chunks, int(hit["id"]), t.chunks.c.kb_id == kb_id)
            if chunk and chunk["document_id"] in docs:
                refs.append(
                    {
                        "chunk_id": chunk["id"],
                        "document_id": chunk["document_id"],
                        "filename": docs[chunk["document_id"]]["filename"],
                        "page": chunk["meta"].get("page", 1),
                        "content": chunk["content"],
                        "score": hit["distance"],
                    }
                )
        try:
            ranking = await self.gateway.rerank(query, [r["content"] for r in refs]) if refs else None
            if ranking is not None:
                ranked = [
                    {**refs[r["index"]], "score": r["relevance_score"]}
                    for r in ranking
                    if type(r.get("index")) is int and 0 <= r["index"] < len(refs)
                ]
                if ranked:
                    threshold = self.cfg.rag_score_threshold if self.cfg else 0.35
                    refs = [r for i, r in enumerate(ranked) if i < 3 or r["score"] >= threshold]
        except Exception:
            log.warning("Rerank unavailable; retaining RRF ranking", exc_info=True)
        return refs[:top_k]

    async def delete_doc(self, user_id, kb_id, doc_id):
        await self.retrieve_owner(user_id, kb_id)
        doc = await self.db.get(t.documents, doc_id, t.documents.c.kb_id == kb_id)
        if not doc:
            raise ValueError("文档不存在")
        # A tombstone immediately excludes it from retrieval; worker performs retryable cleanup.
        async with self.db.engine.begin() as conn:
            await conn.execute(update(t.documents).where(t.documents.c.id == doc_id).values(status="deleted"))
            await conn.execute(insert(t.jobs).values(kind="delete_doc", payload={"doc_id": doc_id}))

    async def cleanup_doc(self, doc_id):
        async with resource_lock(self.db, f"document:{doc_id}"):
            await self._cleanup_doc(doc_id)

    async def _cleanup_doc(self, doc_id):
        doc = await self.db.get(t.documents, doc_id)
        if not doc:
            return
        kb = await self.db.get(t.kbs, doc["kb_id"])
        if kb:
            await self.vectors.delete(kb["milvus_collection"], f"doc_id == {doc_id}")
        await self.objects.remove(doc["object_key"])
        async with self.db.engine.begin() as conn:
            await conn.execute(delete(t.documents).where(t.documents.c.id == doc_id))
            if kb:
                count = await conn.scalar(
                    select(func.count())
                    .select_from(t.documents)
                    .where(t.documents.c.kb_id == kb["id"], t.documents.c.status != "deleted")
                )
                await conn.execute(update(t.kbs).where(t.kbs.c.id == kb["id"]).values(doc_count=count))
                remaining = await conn.scalar(
                    select(func.count()).select_from(t.documents).where(t.documents.c.kb_id == kb["id"])
                )
                if kb["status"] == "deleted" and remaining == 0:
                    await self.vectors.drop(kb["milvus_collection"])
                    await conn.execute(delete(t.kbs).where(t.kbs.c.id == kb["id"]))

    async def retrieve_owner(self, user_id, kb_id):
        kb = await self.db.get(t.kbs, kb_id, t.kbs.c.user_id == user_id)
        if not kb:
            raise ValueError("知识库不存在或无权访问")
        return kb
