from fastapi import APIRouter, Depends

from app.api.dependencies import admin, runtime
from app.api.responses import ok
from app.schemas.evaluation import CaseInput, DatasetInput, EvalRunInput
from app.services import evaluation as service

router = APIRouter(tags=["evaluation"])


@router.get("/admin/eval/datasets")
async def datasets(user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.datasets(user=user, rt=rt))


@router.post("/admin/eval/datasets")
async def create_dataset(body: DatasetInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.create_dataset(body=body.model_dump(exclude_unset=True), user=user, rt=rt))


@router.get("/admin/eval/datasets/{ident}/cases")
async def cases(ident: int, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.cases(ident=ident, user=user, rt=rt))


@router.post("/admin/eval/datasets/{ident}/cases")
async def create_case(ident: int, body: CaseInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(
        await service.create_case(ident=ident, body=body.model_dump(exclude_unset=True), user=user, rt=rt)
    )


@router.post("/admin/eval/runs")
async def create_run(body: EvalRunInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.create_run(body=body.model_dump(exclude_unset=True), user=user, rt=rt))


@router.get("/admin/eval/runs/{ident}")
async def get_eval_run(ident: int, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.get_eval_run(ident=ident, user=user, rt=rt))
