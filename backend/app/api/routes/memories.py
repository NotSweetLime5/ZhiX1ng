from fastapi import APIRouter, Depends

from app.api.dependencies import Paging, current_user, runtime
from app.api.responses import ok
from app.schemas.memory import MemoryExtractInput
from app.services import memories as service

router = APIRouter(tags=["memories"])


@router.get("/memories")
async def list_memories(paging=Depends(Paging), user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.list_memories(paging=paging.values, user=user, rt=rt))


@router.post("/memories/extract")
async def extract_memory(body: MemoryExtractInput, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.extract_memory(body=body.model_dump(exclude_unset=True), user=user, rt=rt))


@router.post("/memories/{ident}/archive")
async def archive_memory(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.archive_memory(ident=ident, user=user, rt=rt))


@router.delete("/memories/{ident}")
async def delete_memory(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.delete_memory(ident=ident, user=user, rt=rt))
