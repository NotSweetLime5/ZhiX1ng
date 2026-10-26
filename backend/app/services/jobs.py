from app import models as t


async def jobs(rt, user):
    return await rt.db.paged(t.jobs, page_size=100)


async def retry_job(rt, user, ident):
    job = await rt.db.get(t.jobs, ident)
    if not job or job["status"] != "failed":
        raise ValueError("只能重试失败任务")
    return await rt.db.change(t.jobs, ident, {"status": "pending", "attempts": 0, "error": ""})
