from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from urllib.parse import quote

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


@router.get("/documents/{ident}")
async def get_document(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.get_document(rt, user, ident))


@router.get("/documents/{ident}/content")
async def document_content(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    doc, data = await service.document_content(rt, user, ident)
    kind = doc["file_type"]
    # HTML/Markdown are served as inert text, never executable user-controlled HTML.
    media = (
        "application/pdf"
        if kind == "pdf"
        else (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if kind == "docx"
            else "text/plain; charset=utf-8"
        )
    )
    disposition = "attachment" if kind == "docx" else "inline"
    return Response(
        data,
        media_type=media,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(doc['filename'], safe='')}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/chunks/{ident}/source")
async def chunk_source(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.chunk_source(rt, user, ident))


@router.post("/documents/{ident}/retry")
async def retry_document(ident: int, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.retry_document(rt, user, ident))


@router.post("/kbs/{ident}/retrieve")
async def retrieve_post(ident: int, body: RetrieveInput, user=Depends(current_user), rt=Depends(runtime)):
    return ok(
        await service.retrieve_post(ident=ident, body=body.model_dump(exclude_unset=True), user=user, rt=rt)
    )


@router.get("/kbs/{ident}/retrieve")
async def retrieve_get(ident: int, query: str, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.retrieve_get(ident=ident, query=query, user=user, rt=rt))
