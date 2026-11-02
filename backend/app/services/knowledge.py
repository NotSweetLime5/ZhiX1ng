import uuid

from sqlalchemy import insert, select, update
from minio.error import S3Error

from app import models as t
from app.core.errors import ServiceError
from app.services.access import owned


async def list_kbs(rt, user, paging):
    return await rt.db.paged(t.kbs, t.kbs.c.user_id == user["id"], t.kbs.c.status == "active", **paging)


async def get_kb(rt, user, ident):
    return await owned(rt, t.kbs, ident, user)


async def create_kb(rt, user, body):
    values = body.model_dump()
    values["embedding_config_id"] = (
        await rt.gateway.resolve(values["embedding_config_id"] or 0, "embedding")
    ).model["id"]
    return await rt.db.add(
        t.kbs, {**values, "user_id": user["id"], "milvus_collection": "nx_kb_" + uuid.uuid4().hex}
    )


async def delete_kb(rt, user, ident):
    kb = await owned(rt, t.kbs, ident, user)
    async with rt.db.engine.begin() as conn:
        await conn.execute(update(t.kbs).where(t.kbs.c.id == ident).values(status="deleted"))
        docs = (await conn.execute(select(t.documents).where(t.documents.c.kb_id == ident))).mappings().all()
        for doc in docs:
            await conn.execute(
                update(t.documents).where(t.documents.c.id == doc["id"]).values(status="deleted")
            )
            await conn.execute(insert(t.jobs).values(kind="delete_doc", payload={"doc_id": doc["id"]}))
    if not docs:
        await rt.vectors.drop(kb["milvus_collection"])
        await rt.db.remove(t.kbs, ident)
    return None


async def upload(rt, user, ident, file):
    await owned(rt, t.kbs, ident, user)
    filename = (file.filename or "document.txt").replace("\\", "/").split("/")[-1]
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in {"pdf", "docx", "txt", "md", "markdown", "html", "htm"}:
        raise ValueError("不支持的文档类型")
    data = await file.read(20 * 1024 * 1024 + 1)
    if not data or len(data) > 20 * 1024 * 1024:
        raise ValueError("文档大小必须为1字节至20MB")
    key = f"{user['id']}/{ident}/{uuid.uuid4().hex}/{filename}"
    await rt.objects.put(key, data)
    try:
        async with rt.db.engine.begin() as conn:
            doc = (
                (
                    await conn.execute(
                        insert(t.documents)
                        .values(
                            kb_id=ident, filename=filename, file_type=ext, object_key=key, file_size=len(data)
                        )
                        .returning(t.documents)
                    )
                )
                .mappings()
                .one()
            )
            await conn.execute(insert(t.jobs).values(kind="doc_etl", payload={"doc_id": doc["id"]}))
            await conn.execute(
                update(t.kbs).where(t.kbs.c.id == ident).values(doc_count=t.kbs.c.doc_count + 1)
            )
    except BaseException:
        await rt.objects.remove(key)
        raise
    return dict(doc)


async def list_docs(rt, user, ident, paging):
    await owned(rt, t.kbs, ident, user)
    return await rt.db.paged(
        t.documents, t.documents.c.kb_id == ident, t.documents.c.status != "deleted", **paging
    )


async def delete_doc(rt, user, ident, doc_id):
    await rt.rag.delete_doc(user["id"], ident, doc_id)
    return None


async def list_chunks(rt, user, ident, paging):
    doc = await rt.db.get(t.documents, ident)
    if not doc:
        raise ServiceError(404, "文档不存在")
    await owned(rt, t.kbs, doc["kb_id"], user)
    return await rt.db.paged(t.chunks, t.chunks.c.document_id == ident, **paging)


async def get_document(rt, user, ident):
    doc = await rt.db.get(t.documents, ident, t.documents.c.status != "deleted")
    if not doc:
        raise ServiceError(404, "文档已删除或不存在")
    kb = await owned(rt, t.kbs, doc["kb_id"], user)
    if kb["status"] != "active":
        raise ServiceError(404, "知识库已删除")
    return doc


async def document_content(rt, user, ident):
    doc = await get_document(rt, user, ident)
    try:
        data = await rt.objects.get(doc["object_key"])
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject"}:
            raise ServiceError(404, "原文件已不可用") from exc
        raise
    return doc, data


async def chunk_source(rt, user, ident):
    chunk = await rt.db.get(t.chunks, ident)
    if not chunk:
        raise ServiceError(404, "引用内容已删除或不存在")
    doc = await get_document(rt, user, chunk["document_id"])
    return {
        "chunk_id": chunk["id"],
        "document_id": doc["id"],
        "kb_id": doc["kb_id"],
        "filename": doc["filename"],
        "file_type": doc["file_type"],
        "page": chunk["meta"].get("page", 1),
        "content": chunk["content"],
    }


async def retry_document(rt, user, ident):
    await get_document(rt, user, ident)
    async with rt.db.engine.begin() as conn:
        # A short row lock serializes retry clicks without blocking on long ETL work.
        doc = (
            (await conn.execute(select(t.documents).where(t.documents.c.id == ident).with_for_update()))
            .mappings()
            .first()
        )
        if not doc or doc["status"] != "failed":
            raise ServiceError(409, "仅可重试处理失败的文档，请刷新查看最新状态")
        if not await conn.scalar(
            select(t.kbs.c.id).where(
                t.kbs.c.id == doc["kb_id"],
                t.kbs.c.user_id == user["id"],
                t.kbs.c.status == "active",
            )
        ):
            raise ServiceError(404, "知识库已删除或不可访问")
        active = await conn.scalar(
            select(t.jobs.c.id)
            .where(
                t.jobs.c.kind == "doc_etl",
                t.jobs.c.payload["doc_id"].as_integer() == ident,
                t.jobs.c.status.in_(["pending", "running"]),
            )
            .limit(1)
        )
        if active:
            raise ServiceError(409, "该文档已有处理任务")
        await conn.execute(insert(t.jobs).values(kind="doc_etl", payload={"doc_id": ident}))
        row = (
            (
                await conn.execute(
                    update(t.documents)
                    .where(t.documents.c.id == ident)
                    .values(status="pending", error="", updated_at=t.now())
                    .returning(t.documents)
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def retrieve_post(rt, user, ident, body):
    query = body.get("query", "").strip()
    if not query:
        raise ValueError("query 必填")
    return await rt.rag.retrieve(user["id"], ident, query)


async def retrieve_get(rt, user, ident, query):
    return await rt.rag.retrieve(user["id"], ident, query)
