import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.dependencies import Paging, current_user, runtime
from app.api.responses import ok
from app.schemas import ChatInput
from app.schemas.chat import SessionUpdate
from app.services import chat as service

router = APIRouter(tags=["chat"])


@router.post("/chat/stream")
async def chat_stream(body: ChatInput, user=Depends(current_user), rt=Depends(runtime)):
    if not body.content.strip():
        raise ValueError("消息不能为空")
    agent, session = await service.prepare(rt, user, body)
    return StreamingResponse(
        service.stream(rt, user, body, agent, session),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions")
async def list_sessions(paging=Depends(Paging), user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.list_sessions(paging=paging.values, user=user, rt=rt))


@router.get("/sessions/{ident}/messages")
async def messages(ident: uuid.UUID, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.messages(ident=ident, user=user, rt=rt))


@router.put("/sessions/{ident}")
async def rename_session(
    ident: uuid.UUID, body: SessionUpdate, user=Depends(current_user), rt=Depends(runtime)
):
    return ok(
        await service.rename_session(ident=ident, body=body.model_dump(exclude_unset=True), user=user, rt=rt)
    )


@router.delete("/sessions/{ident}")
async def delete_session(ident: uuid.UUID, user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.delete_session(ident=ident, user=user, rt=rt))
