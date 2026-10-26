from fastapi import APIRouter, Depends, File, UploadFile

from app.api.dependencies import Paging, current_user, runtime
from app.api.responses import ok
from app.schemas import KBInput
from app.schemas.knowledge import RetrieveInput
from app.services import knowledge as service

router = APIRouter(tags=["knowledge"])


@router.get("/kbs")
async def list_kbs(paging=Depends(Paging), user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.list_kbs(paging=paging.values, user=user, rt=rt))


@router.get("/kbs/{ident}")
async def get_kb(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.get_kb(ident=ident, user=user, rt=rt))


@router.post("/kbs")
async def create_kb(body: KBInput, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.create_kb(body=body, user=user, rt=rt))


@router.delete("/kbs/{ident}")
async def delete_kb(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.delete_kb(ident=ident, user=user, rt=rt))


@router.post("/kbs/{ident}/documents")
async def upload(ident: int, file: UploadFile = File(), user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.upload(ident=ident, file=file, user=user, rt=rt))


@router.get("/kbs/{ident}/documents")
async def list_docs(ident: int, paging=Depends(Paging), user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.list_docs(ident=ident, paging=paging.values, user=user, rt=rt))


@router.delete("/kbs/{ident}/documents/{doc_id}")
async def delete_doc(ident: int, doc_id: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.delete_doc(ident=ident, doc_id=doc_id, user=user, rt=rt))


@router.get("/documents/{ident}/chunks")
async def list_chunks(ident: int, paging=Depends(Paging), user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.list_chunks(ident=ident, paging=paging.values, user=user, rt=rt))


@router.post("/kbs/{ident}/retrieve")
async def retrieve_post(ident: int, body: RetrieveInput, user=Depends(current_user), rt=Depends(runtime)):
    return ok(
        await service.retrieve_post(ident=ident, body=body.model_dump(exclude_unset=True), user=user, rt=rt)
    )


@router.get("/kbs/{ident}/retrieve")
async def retrieve_get(ident: int, query: str, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.retrieve_get(ident=ident, query=query, user=user, rt=rt))
