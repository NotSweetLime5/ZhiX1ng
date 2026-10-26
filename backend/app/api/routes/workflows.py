from fastapi import APIRouter, Depends

from app.api.dependencies import Paging, current_user, runtime
from app.api.responses import ok
from app.schemas import Approval, RunInput, WorkflowInput
from app.schemas.workflow import WorkflowValidationInput
from app.services import workflows as service

router = APIRouter(tags=["workflows"])


@router.post("/workflows/validate")
async def validate_workflow(body: WorkflowValidationInput, user=Depends(current_user)):
    return ok(await service.validate_workflow(body=body.model_dump(exclude_unset=True), user=user))


@router.post("/workflows/run")
async def run_workflow(body: RunInput, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.run_workflow(body=body, user=user, rt=rt))


@router.get("/workflows/runs")
async def list_runs(
    workflow_id: int | None = None, paging=Depends(Paging), user=Depends(current_user), rt=Depends(runtime)
):
    return ok(await service.list_runs(workflow_id=workflow_id, paging=paging.values, user=user, rt=rt))


@router.get("/workflows/runs/{ident}")
async def get_run(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.get_run(ident=ident, user=user, rt=rt))


@router.post("/workflows/runs/{ident}/approve")
async def approve(ident: int, body: Approval, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.approve(ident=ident, body=body, user=user, rt=rt))


@router.get("/workflows")
async def list_workflows(paging=Depends(Paging), user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.list_workflows(paging=paging.values, user=user, rt=rt))


@router.post("/workflows")
async def create_workflow(body: WorkflowInput, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.create_workflow(body=body, user=user, rt=rt))


@router.get("/workflows/{ident}")
async def get_workflow(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.get_workflow(ident=ident, user=user, rt=rt))


@router.put("/workflows/{ident}")
async def update_workflow(ident: int, body: WorkflowInput, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.update_workflow(ident=ident, body=body, user=user, rt=rt))


@router.delete("/workflows/{ident}")
async def delete_workflow(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.delete_workflow(ident=ident, user=user, rt=rt))
