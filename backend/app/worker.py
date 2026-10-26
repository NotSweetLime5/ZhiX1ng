import asyncio
import logging
import signal
import sys
import time
from datetime import timedelta

from sqlalchemy import or_, select, update

from app import models as t
from app.core.config import settings
from app.core.observability import configure_tracing, operation
from app.infrastructure.task_queue import TaskQueue
from app.runtime import Runtime

log = logging.getLogger(__name__)


async def claim(rt, ident=None, revision=None):
    async with rt.db.engine.begin() as conn:
        expired = (
            (
                await conn.execute(
                    select(t.jobs)
                    .where(
                        or_(
                            t.jobs.c.status == "pending",
                            (t.jobs.c.status == "running") & (t.jobs.c.lease_until < t.now()),
                        ),
                        t.jobs.c.attempts >= rt.cfg.worker_max_retry,
                        *([t.jobs.c.id == ident] if ident is not None else []),
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .all()
        )
        for job in expired:
            await conn.execute(
                update(t.jobs)
                .where(t.jobs.c.id == job["id"])
                .values(status="failed", lease_until=None, error="任务租约到期且重试次数耗尽")
            )
            if job["kind"] == "doc_etl":
                await conn.execute(
                    update(t.documents)
                    .where(t.documents.c.id == job["payload"]["doc_id"], t.documents.c.status != "deleted")
                    .values(status="failed", error="Worker 重试次数耗尽")
                )
            elif job["kind"] == "eval":
                await conn.execute(
                    update(t.eval_runs)
                    .where(t.eval_runs.c.id == job["payload"]["run_id"])
                    .values(status="failed")
                )
        eligible = or_(
            t.jobs.c.status == "pending", (t.jobs.c.status == "running") & (t.jobs.c.lease_until < t.now())
        )
        row = (
            (
                await conn.execute(
                    select(t.jobs)
                    .where(eligible, t.jobs.c.attempts < rt.cfg.worker_max_retry)
                    .where(*([t.jobs.c.id == ident] if ident is not None else []))
                    .where(*([t.jobs.c.queue_revision == revision] if revision is not None else []))
                    .order_by(t.jobs.c.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        return dict(
            (
                await conn.execute(
                    update(t.jobs)
                    .where(t.jobs.c.id == row["id"])
                    .values(
                        status="running",
                        attempts=row["attempts"] + 1,
                        lease_until=t.now() + timedelta(seconds=90),
                    )
                    .returning(t.jobs)
                )
            )
            .mappings()
            .one()
        )


async def heartbeat(rt, ident, queue=None, delivery=None):
    while True:
        await asyncio.sleep(30)
        try:
            await rt.db.change(t.jobs, ident, {"lease_until": t.now() + timedelta(seconds=90)})
        except Exception:
            log.exception("Job %s SQL heartbeat failed; retrying", ident)
        if queue:
            try:
                await queue.heartbeat(delivery)
            except Exception:
                log.exception("Job %s Redis heartbeat failed; retrying", ident)


async def handle(rt, job):
    payload, kind = job["payload"], job["kind"]
    if kind == "doc_etl":
        await rt.rag.index(payload["doc_id"])
    elif kind == "delete_doc":
        await rt.rag.cleanup_doc(payload["doc_id"])
    elif kind == "memory_index":
        await rt.memory.index(payload["memory_id"])
    elif kind == "memory_delete":
        await rt.vectors.delete("nx_memories", f"id == {int(payload['memory_id'])}")
    elif kind == "memory_extract":
        session = await rt.db.get(
            t.sessions, payload["session_id"], t.sessions.c.user_id == payload["user_id"]
        )
        if session:
            history = await rt.db.rows(t.messages, t.messages.c.session_id == session["id"], limit=20)
            history.reverse()
            await rt.memory.extract(
                payload["user_id"],
                payload.get("agent_id", 0),
                [{"role": h["role"], "content": h["content"]} for h in history],
            )
    elif kind == "eval":
        from app.services.evaluation import evaluate

        await evaluate(rt, payload["run_id"])
    else:
        raise ValueError(f"未知任务类型 {kind}")


async def process(rt, job, queue=None, delivery=None):
    pulse = asyncio.create_task(heartbeat(rt, job["id"], queue, delivery))
    try:
        async with asyncio.timeout(600):
            with operation("worker." + job["kind"]):
                await handle(rt, job)
        await rt.db.change(t.jobs, job["id"], {"status": "done", "lease_until": None, "error": ""})
    except Exception as exc:
        log.exception("Job %s failed", job["id"])
        terminal = job["attempts"] >= rt.cfg.worker_max_retry
        await rt.db.change(
            t.jobs,
            job["id"],
            {
                "status": "failed" if terminal else "pending",
                "lease_until": None,
                "error": str(exc),
                "queue_revision": t.jobs.c.queue_revision + (0 if terminal else 1),
                "stream_id": "" if not terminal else job["stream_id"],
            },
        )
        if job["kind"] == "doc_etl":
            async with rt.db.engine.begin() as conn:
                await conn.execute(
                    update(t.documents)
                    .where(t.documents.c.id == job["payload"]["doc_id"], t.documents.c.status != "deleted")
                    .values(status="failed" if terminal else "pending", error=str(exc))
                )
        if terminal and job["kind"] == "eval":
            await rt.db.change(t.eval_runs, job["payload"]["run_id"], {"status": "failed"})
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)


async def consume(rt, stop):
    queue = TaskQueue(rt)
    await queue.setup()
    while not stop.is_set():
        try:
            delivery = await queue.receive()
            if not delivery:
                continue
            _, _, fields = delivery
            # Go-format entries may exist before migration. Import them exactly once.
            if "job_id" not in fields:
                await import_legacy(rt, queue, delivery)
                continue
            try:
                ident, revision = int(fields["job_id"]), int(fields["revision"])
            except (KeyError, ValueError):
                await queue.ack(delivery, "Invalid job_id or revision")
                continue
            job = await claim(rt, ident, revision)
            if job:
                await process(rt, job, queue, delivery)
            latest = await rt.db.get(t.jobs, ident)
            if not latest or latest["status"] == "done" or latest["queue_revision"] != revision:
                await queue.ack(delivery)
            elif latest["status"] == "failed":
                await queue.ack(delivery, latest["error"])
            # A duplicate whose SQL lease is still held stays pending for reclamation.
        except Exception:
            log.exception("Redis Streams consumer failed; delivery remains recoverable")
            await asyncio.sleep(1)


async def import_legacy(rt, queue, delivery):
    from sqlalchemy import insert, text

    stream, ident, fields = delivery
    if stream not in {"stream:doc-etl", "stream:eval"}:
        await queue.ack(delivery, "Unknown legacy stream")
        return
    field, kind = ("doc_id", "doc_etl") if stream == "stream:doc-etl" else ("run_id", "eval")
    try:
        payload = {field: int(fields[field])}
    except (KeyError, ValueError):
        await queue.ack(delivery, "Invalid legacy queue payload")
        return
    marker = f"legacy_stream:{stream}:{ident}"
    async with rt.db.engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": marker})
        existing = await conn.scalar(
            select(t.jobs.c.id).where(t.jobs.c.payload["legacy_delivery"].astext == marker)
        )
        if not existing:
            await conn.execute(
                insert(t.jobs).values(kind=kind, payload={**payload, "legacy_delivery": marker})
            )
    await queue.ack(delivery)


async def dispatch(rt, stop):
    queue = TaskQueue(rt)
    await queue.setup()
    await queue.recover_outbox()
    recovered_at = time.monotonic()
    while not stop.is_set():
        try:
            if time.monotonic() - recovered_at >= 30:
                await queue.setup()
                await queue.recover_outbox()
                recovered_at = time.monotonic()
            count = await queue.publish()
        except Exception:
            log.exception("Outbox publish failed; committed jobs remain pending")
            count = 0
        if count < 100:
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except TimeoutError:
                pass


async def main():
    logging.basicConfig(level=logging.INFO)
    configure_tracing(settings(), "zhixing-worker")
    rt = await Runtime(settings()).start()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        await asyncio.gather(
            dispatch(rt, stop), *(consume(rt, stop) for _ in range(rt.cfg.worker_concurrency))
        )
    finally:
        await rt.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
