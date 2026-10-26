from fastapi import APIRouter, Depends

from app import models as t
from app.api.dependencies import admin, runtime
from app.api.responses import ok
from app.schemas.admin import A2ARegisterInput, A2ATaskInput, MCPCallInput, MCPServerInput
from app.services import catalog
from app.services import integrations as service

router = APIRouter(tags=["integrations"])


@router.post("/admin/mcp/servers/{ident}/sync")
async def sync_mcp(ident: int, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.sync_mcp(ident=ident, user=user, rt=rt))


@router.post("/admin/mcp/servers/{ident}/health")
async def health_mcp(ident: int, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.health_mcp(ident=ident, user=user, rt=rt))


@router.post("/admin/mcp/servers/{ident}/call")
async def call_mcp(ident: int, body: MCPCallInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.call_mcp(ident=ident, body=body.model_dump(exclude_unset=True), user=user, rt=rt))


@router.get("/admin/a2a/agents")
async def list_a2a(user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.list_a2a(user=user, rt=rt))


@router.post("/admin/a2a/agents")
async def register_a2a(body: A2ARegisterInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.register_a2a(body=body.model_dump(exclude_unset=True), user=user, rt=rt))


@router.delete("/admin/a2a/agents/{ident}")
async def delete_a2a(ident: int, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.delete_a2a(ident=ident, user=user, rt=rt))


@router.post("/admin/a2a/agents/{ident}/health")
async def health_a2a(ident: int, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.health_a2a(ident=ident, user=user, rt=rt))


@router.post("/admin/a2a/agents/{ident}/tasks")
async def send_a2a(ident: int, body: A2ATaskInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(await service.send_a2a(ident=ident, body=body.model_dump(exclude_unset=True), user=user, rt=rt))


@router.get("/admin/mcp/servers", name="list_mcp_servers")
async def list_mcp_servers(type: str | None = None, user=Depends(admin), rt=Depends(runtime)):
    return ok(await catalog.listing(t.mcp_servers, ("name", "url"), rt, user, type))


@router.post("/admin/mcp/servers", name="create_mcp_servers")
async def create_mcp_servers(body: MCPServerInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(
        await catalog.create(t.mcp_servers, ("name", "url"), rt, user, body.model_dump(exclude_unset=True))
    )


@router.put("/admin/mcp/servers/{ident}", name="update_mcp_servers")
async def update_mcp_servers(ident: int, body: MCPServerInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(
        await catalog.edit(
            t.mcp_servers, ("name", "url"), rt, user, ident, body.model_dump(exclude_unset=True)
        )
    )


@router.delete("/admin/mcp/servers/{ident}", name="delete_mcp_servers")
async def delete_mcp_servers(ident: int, user=Depends(admin), rt=Depends(runtime)):
    return ok(await catalog.remove(t.mcp_servers, ("name", "url"), rt, user, ident))
