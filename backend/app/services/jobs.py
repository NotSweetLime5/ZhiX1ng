from sqlalchemy import update

from app import models as t


async def jobs(rt, user):
    return await rt.db.paged(t.jobs, page_size=100)


async def retry_job(rt, user, ident):
    query = (
        update(t.jobs)
        .where(t.jobs.c.id == ident, t.jobs.c.status == "failed")
        .values(
            status="pending",
            attempts=0,
            error="",
            lease_until=None,
            stream_id="",
            queue_revision=t.jobs.c.queue_revision + 1,
            updated_at=t.now(),
        )
        .returning(t.jobs)
    )
    async with rt.db.engine.begin() as conn:
        row = (await conn.execute(query)).mappings().first()
        if not row:
            raise ValueError("只能重试失败任务")
        return dict(row)
