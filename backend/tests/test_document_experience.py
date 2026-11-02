"""Authenticated source viewing and owner-scoped retry of failed document processing."""

import uuid

from app import models as t


async def create_doc(rt, client, filename="source.html", content=b"<script>alert('not executed')</script>"):
    kb_response = await client.post(
        "/api/v1/kbs",
        json={
            "name": "Source viewing",
            "embedding_config_id": rt.test_embed["id"],
        },
    )
    assert kb_response.status_code == 200, kb_response.text
    kb = kb_response.json()["data"]
    response = await client.post(f"/api/v1/kbs/{kb['id']}/documents", files={"file": (filename, content)})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_document_content_is_authenticated_and_html_is_inert(rt, client):
    doc = await create_doc(rt, client)
    path = f"/api/v1/documents/{doc['id']}/content"
    response = await client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert b"<script>" in response.content
    assert (await client.get(path, headers={"Authorization": ""})).status_code == 401
    chunk = await rt.db.add(
        t.chunks,
        {
            "kb_id": doc["kb_id"],
            "document_id": doc["id"],
            "content": "owner-only excerpt",
            "meta": {"page": 1},
        },
    )
    other = await rt.db.add(
        t.users,
        {
            "username": "viewer_" + uuid.uuid4().hex[:10],
            "email": uuid.uuid4().hex + "@test.local",
            "password_hash": "unused",
        },
    )
    try:
        tokens = await rt.security.tokens(other)
        for route in (
            path,
            f"/api/v1/documents/{doc['id']}",
            f"/api/v1/documents/{doc['id']}/retry",
            f"/api/v1/chunks/{chunk['id']}/source",
        ):
            method = client.post if route.endswith("retry") else client.get
            result = await method(route, headers={"Authorization": "Bearer " + tokens["access_token"]})
            assert result.status_code == 404, result.text
    finally:
        await rt.db.remove(t.users, other["id"])


async def test_chunk_source_keeps_page_and_is_unavailable_after_delete(rt, client):
    doc = await create_doc(rt, client, "sources.txt", b"Page provenance for retrieval.")
    chunk = await rt.db.add(
        t.chunks,
        {
            "kb_id": doc["kb_id"],
            "document_id": doc["id"],
            "content": "Source paragraph",
            "meta": {"page": 3},
        },
    )
    route = f"/api/v1/chunks/{chunk['id']}/source"
    response = await client.get(route)
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "chunk_id": chunk["id"],
        "document_id": doc["id"],
        "kb_id": doc["kb_id"],
        "filename": "sources.txt",
        "file_type": "txt",
        "page": 3,
        "content": "Source paragraph",
    }
    await rt.db.change(t.documents, doc["id"], {"status": "deleted"})
    assert (await client.get(route)).status_code == 404
    assert (await client.get(f"/api/v1/documents/{doc['id']}/content")).status_code == 404


async def test_document_retry_enqueues_once_and_rejects_active_processing(rt, client):
    doc = await create_doc(rt, client, "retry.txt", b"Retryable document.")
    route = f"/api/v1/documents/{doc['id']}/retry"
    assert (await client.post(route)).status_code == 409
    jobs = await rt.db.rows(t.jobs, t.jobs.c.payload["doc_id"].as_integer() == doc["id"])
    await rt.db.change(t.documents, doc["id"], {"status": "failed", "error": "previous failure"})
    # A failed doc must not create another task while the original is still pending.
    assert (await client.post(route)).status_code == 409
    for job in jobs:
        await rt.db.change(t.jobs, job["id"], {"status": "failed", "attempts": 3})
    response = await client.post(route)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "pending"
    assert response.json()["data"]["error"] == ""
    assert (await client.post(route)).status_code == 409
    pending = await rt.db.rows(
        t.jobs, t.jobs.c.payload["doc_id"].as_integer() == doc["id"], t.jobs.c.status == "pending"
    )
    assert len(pending) == 1 and pending[0]["kind"] == "doc_etl"
