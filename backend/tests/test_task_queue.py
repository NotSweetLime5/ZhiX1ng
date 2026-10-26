import asyncio
import uuid
from datetime import timedelta

import pytest

from app import models as t
from app.infrastructure.task_queue import TaskQueue
from app.services.jobs import retry_job
from app.worker import claim, consume, dispatch


@pytest.fixture
async def queue(rt):
    rt.cfg = rt.cfg.model_copy(update={"redis_namespace": "nx_queue_" + uuid.uuid4().hex})
    queue = TaskQueue(rt)
    await queue.setup()
    try:
        yield queue
    finally:
        keys = [key async for key in rt.redis.scan_iter(match=rt.cfg.redis_namespace + ":*")]
        if keys:
            await rt.redis.delete(*keys)


async def delivery_for(queue, ident):
    for _ in range(200):
        delivery = await queue.receive()
        if delivery and delivery[2].get("job_id") == str(ident):
            return delivery
        if delivery:
            await queue.ack(delivery)
    raise AssertionError("Committed job was not delivered")


async def test_outbox_restart_deduplicates_and_repairs_lost_redis_entry(rt, queue):
    job = await rt.db.add(t.jobs, {"kind": "doc_etl", "payload": {"doc_id": -100}})
    await queue.publish()
    delivery = await delivery_for(queue, job["id"])
    first_id = delivery[1]
    await queue.recover_outbox()
    await queue.publish()
    assert (await rt.db.get(t.jobs, job["id"]))["stream_id"] == first_id
    await rt.redis.xdel(queue.key("stream:doc-etl"), first_id)
    await queue.recover_outbox()
    await queue.publish()
    repaired = await rt.db.get(t.jobs, job["id"])
    assert repaired["stream_id"] != first_id
    assert await rt.redis.xrange(queue.key("stream:doc-etl"), repaired["stream_id"], repaired["stream_id"])


async def test_stream_reclaims_crashed_worker_without_double_execution(rt, queue):
    job = await rt.db.add(t.jobs, {"kind": "doc_etl", "payload": {"doc_id": -101}})
    await queue.publish()
    delivery = await delivery_for(queue, job["id"])
    running = await claim(rt, job["id"], 0)
    assert running["attempts"] == 1
    assert await claim(rt, job["id"], 0) is None
    await rt.db.change(t.jobs, job["id"], {"lease_until": t.now() - timedelta(seconds=1)})
    await rt.redis.xclaim(
        queue.key(delivery[0]),
        queue.groups[delivery[0]],
        "dead-worker",
        0,
        [delivery[1]],
        idle=rt.cfg.worker_claim_idle_ms + 1,
    )
    replacement = TaskQueue(rt)
    recovered = await delivery_for(replacement, job["id"])
    assert recovered[1] == delivery[1]
    assert (await claim(rt, job["id"], 0))["attempts"] == 2
    await rt.db.change(t.jobs, job["id"], {"status": "done"})
    await replacement.ack(recovered)


async def test_stream_worker_retries_to_dlq_and_admin_can_requeue(rt, queue, monkeypatch):
    from app import worker

    job = await rt.db.add(t.jobs, {"kind": "memory_index", "payload": {"memory_id": -102}})
    calls = []

    async def fail(_rt, row):
        if row["id"] == job["id"]:
            calls.append(row["attempts"])
            raise RuntimeError("intentional transient failure")

    monkeypatch.setattr(worker, "handle", fail)
    stop = asyncio.Event()
    tasks = [asyncio.create_task(dispatch(rt, stop)), asyncio.create_task(consume(rt, stop))]
    try:
        async with asyncio.timeout(20):
            while not await rt.redis.xlen(queue.key("stream:jobs:dlq")):  # noqa: ASYNC110 - bounded integration polling
                await asyncio.sleep(0.05)
        assert calls == [1, 2, 3]
        latest = await rt.db.get(t.jobs, job["id"])
        assert latest["status"] == "failed"
        dlq = await rt.redis.xrange(queue.key("stream:jobs:dlq"))
        assert any(item[1]["job_id"] == str(job["id"]) for item in dlq)
        revision = latest["queue_revision"]
        retried = await retry_job(rt, rt.test_user, job["id"])
        assert retried["attempts"] == 0 and retried["queue_revision"] == revision + 1
    finally:
        stop.set()
        await asyncio.gather(*tasks)


async def test_original_go_stream_payload_is_imported_once(rt, queue):
    from app.worker import import_legacy

    ident = await rt.redis.xadd(queue.key("stream:doc-etl"), {"doc_id": "-103"})
    delivery = ("stream:doc-etl", ident, {"doc_id": "-103"})
    await import_legacy(rt, queue, delivery)
    await import_legacy(rt, queue, delivery)
    marker = f"legacy_stream:stream:doc-etl:{ident}"
    rows = await rt.db.rows(t.jobs, t.jobs.c.payload["legacy_delivery"].astext == marker)
    assert len(rows) == 1 and rows[0]["payload"]["doc_id"] == -103


async def test_busy_document_stream_does_not_starve_evaluations(rt, queue):
    for doc_id in range(3):
        await rt.redis.xadd(queue.key("stream:doc-etl"), {"doc_id": str(doc_id)})
    await rt.redis.xadd(queue.key("stream:eval"), {"run_id": "1"})
    assert (await queue.receive())[0] == "stream:doc-etl"
    assert (await queue.receive())[0] == "stream:eval"


async def test_malformed_message_goes_to_dlq_instead_of_being_retried_forever(rt, queue, monkeypatch):
    stop = asyncio.Event()
    original_ack = TaskQueue.ack

    async def ack_and_stop(self, delivery, error=None):
        await original_ack(self, delivery, error)
        stop.set()

    monkeypatch.setattr(TaskQueue, "ack", ack_and_stop)
    await rt.redis.xadd(queue.key("stream:jobs"), {"job_id": "invalid", "revision": "0"})
    async with asyncio.timeout(5):
        await consume(rt, stop)
    assert await rt.redis.xlen(queue.key("stream:jobs:dlq")) == 1


async def test_concurrent_admin_retries_only_publish_one_new_generation(rt):
    job = await rt.db.add(
        t.jobs,
        {
            "kind": "memory_index",
            "payload": {"memory_id": -104},
            "status": "failed",
            "attempts": 3,
            "queue_revision": 2,
        },
    )
    results = await asyncio.gather(
        *(retry_job(rt, rt.test_user, job["id"]) for _ in range(2)), return_exceptions=True
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert (await rt.db.get(t.jobs, job["id"]))["queue_revision"] == 3
