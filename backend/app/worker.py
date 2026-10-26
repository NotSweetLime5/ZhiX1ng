import asyncio
import logging
import signal
import sys
from datetime import timedelta

from sqlalchemy import or_, select, update

from app import models as t
from app.core.config import settings
from app.runtime import Runtime

log = logging.getLogger(__name__)


async def claim(rt):
    async with rt.db.engine.begin() as conn:
        expired = (
            (
                await conn.execute(
                    select(t.jobs)
                    .where(
                        t.jobs.c.status == "running", t.jobs.c.lease_until < t.now(), t.jobs.c.attempts >= 3
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
                .values(status="failed", error="任务租约到期且重试次数耗尽")
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
                    .where(eligible, t.jobs.c.attempts < 3)
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


async def heartbeat(rt, ident):
    while True:
        await asyncio.sleep(30)
        await rt.db.change(t.jobs, ident, {"lease_until": t.now() + timedelta(seconds=90)})


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


async def process(rt, job):
    pulse = asyncio.create_task(heartbeat(rt, job["id"]))
    try:
        async with asyncio.timeout(600):
            await handle(rt, job)
        await rt.db.change(t.jobs, job["id"], {"status": "done", "lease_until": None, "error": ""})
    except Exception as exc:
        log.exception("Job %s failed", job["id"])
        terminal = job["attempts"] >= 3
        await rt.db.change(
            t.jobs,
            job["id"],
            {"status": "failed" if terminal else "pending", "lease_until": None, "error": str(exc)},
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
    while not stop.is_set():
        job = await claim(rt)
        if job:
            await process(rt, job)
        else:
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except TimeoutError:
                pass


async def main():
    logging.basicConfig(level=logging.INFO)
    rt = await Runtime(settings()).start()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        await asyncio.gather(*(consume(rt, stop) for _ in range(4)))
    finally:
        await rt.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
