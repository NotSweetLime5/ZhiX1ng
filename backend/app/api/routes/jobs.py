from fastapi import APIRouter, Depends

from app.api.dependencies import admin, runtime
from app.api.responses import ok
from app.services import jobs as service

router = APIRouter(tags=["jobs"])


@router.get("/admin/jobs")
async def jobs(user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.jobs(user=user, rt=rt))


@router.post("/admin/jobs/{ident}/retry")
async def retry_job(ident: int, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.retry_job(ident=ident, user=user, rt=rt))
