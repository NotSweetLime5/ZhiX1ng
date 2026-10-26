import json
import uuid

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import current_user, runtime
from app.core.brand import APP_NAME, APP_VERSION
from app.schemas.chat import ChatInput
from app.services.chat import prepare, stream

router = APIRouter(tags=["a2a"])


@router.get("/.well-known/agent-card.json")
@router.get("/.well-known/agent.json")
async def card(request: Request):
    return {
        "name": APP_NAME,
        "description": "LangChain/LangGraph Agent 平台",
        "version": APP_VERSION,
        "protocolVersion": "0.3.0",
        "url": str(request.base_url).rstrip("/") + "/a2a",
        "capabilities": {"streaming": False},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        "security": [{"bearer": []}],
        "skills": [{"id": "chat", "name": "对话", "description": "对话与工具调用", "tags": ["chat"]}],
    }


@router.post("/a2a")
async def rpc(body: dict, user=Depends(current_user), rt=Depends(runtime)):
    ident = body.get("id")
    if body.get("jsonrpc") != "2.0" or body.get("method") != "message/send":
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "只支持 message/send"}}
    parts = body.get("params", {}).get("message", {}).get("parts", [])
    content = "".join((p.get("text", "") for p in parts if p.get("kind", p.get("type")) == "text"))
    if not content.strip():
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "文本不能为空"}}
    try:
        request = ChatInput(content=content)
        agent, session = await prepare(rt, user, request)
        answer = ""
        async for frame in stream(rt, user, request, agent, session):
            lines = frame.splitlines()
            event = lines[0][7:]
            data = json.loads(lines[1][6:])
            if event == "delta":
                answer += data["content"]
            elif event == "error":
                raise RuntimeError(data["message"])
        return {
            "jsonrpc": "2.0",
            "id": ident,
            "result": {
                "id": str(uuid.uuid4()),
                "contextId": session["id"],
                "kind": "task",
                "status": {"state": "completed"},
                "artifacts": [{"artifactId": str(uuid.uuid4()), "parts": [{"kind": "text", "text": answer}]}],
            },
        }
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32603, "message": str(exc)}}
