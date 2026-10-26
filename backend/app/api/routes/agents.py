from fastapi import APIRouter, Depends

from app.api.dependencies import Paging, current_user, runtime
from app.api.responses import ok
from app.schemas import AgentInput
from app.services import agents as service

router = APIRouter(tags=["agents"])


@router.get("/agents")
async def list_agents(paging=Depends(Paging), user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.list_agents(paging=paging.values, user=user, rt=rt))


@router.get("/agents/{ident}")
async def get_agent(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.get_agent(ident=ident, user=user, rt=rt))


@router.post("/agents")
async def create_agent(body: AgentInput, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.create_agent(body=body, user=user, rt=rt))


@router.put("/agents/{ident}")
async def update_agent(ident: int, body: AgentInput, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.update_agent(ident=ident, body=body, user=user, rt=rt))


@router.delete("/agents/{ident}")
async def delete_agent(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.delete_agent(ident=ident, user=user, rt=rt))


@router.get("/tools")
async def list_tools(paging=Depends(Paging), user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.list_tools(paging=paging.values, user=user, rt=rt))
