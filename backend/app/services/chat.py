import asyncio
import json
import logging
import time
import uuid

from sqlalchemy import func, insert, select, text, update

from app import models as t
from app.core.serialization import serial
from app.services.access import owned

log = logging.getLogger(__name__)


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(serial(data), ensure_ascii=False, default=str)}\n\n"


async def prepare(runtime, user, request):
    agent = await runtime.agent.load(request.agent_id, user)
    if request.model_config_id:
        agent["model_config_id"] = request.model_config_id
    await runtime.gateway.resolve(agent["model_config_id"])
    if request.session_id:
        try:
            uuid.UUID(request.session_id)
        except ValueError as exc:
            raise ValueError("会话 ID 无效") from exc
        session = await runtime.db.get(t.sessions, request.session_id, t.sessions.c.user_id == user["id"])
        if not session:
            raise ValueError("会话不存在或无权访问")
    else:
        session = await runtime.db.add(
            t.sessions,
            {
                "id": str(uuid.uuid4()),
                "user_id": user["id"],
                "agent_id": agent["id"] or None,
                "title": request.content[:20],
            },
        )
    return agent, session


async def stream(runtime, user, request, agent, session):
    output = {
        "content": "",
        "reasoning": "",
        "trace": [],
        "tool_calls": [],
        "model": "",
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    started = time.monotonic()
    status, message_id = 1, None
    terminal = ("done", {"finish_reason": "stop"})
    conn = await runtime.db.engine.connect()
    locked = False
    try:
        locked = await conn.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:id, 0))"), {"id": session["id"]}
        )
        if not locked:
            yield sse("error", {"code": 409, "message": "该会话正在生成回答"})
            return
        user_msg = await runtime.db.add(
            t.messages, {"session_id": session["id"], "role": "user", "content": request.content}
        )
        message_id = user_msg["id"]
        yield sse("meta", {"session_id": session["id"], "agent": agent["name"], "message_id": message_id})
        history = await runtime.db.rows(
            t.messages, t.messages.c.session_id == session["id"], limit=100, ascending=False
        )
        history.reverse()
        system, refs, messages = await runtime.agent.context(agent, user, request.content, history)
        output["refs"] = refs
        if refs:
            yield sse("refs", {"items": refs})
        graph = await runtime.agent.compile(agent, user, system)
        async for event, data in runtime.agent.events(
            graph, messages, f"chat:{session['id']}:{message_id}", output
        ):
            yield sse(event, data)
        if not output["content"]:
            final = output.get("final_messages", [])
            if final:
                content = final[-1]["data"].get("content", "")
                if isinstance(content, str):
                    output["content"] = content
                    yield sse("delta", {"content": content})
        if not output["content"]:
            raise RuntimeError("模型未生成回答")
        desc = await runtime.gateway.resolve(agent["model_config_id"])
        cost = (
            float(desc.model["input_price"]) * output["prompt_tokens"]
            + float(desc.model["output_price"]) * output["completion_tokens"]
        ) / 1000000
        output["cost"] = cost
        output["model"] = output["model"] or desc.model["model_name"]
        yield sse(
            "usage",
            {
                "prompt_tokens": output["prompt_tokens"],
                "completion_tokens": output["completion_tokens"],
                "cost": f"{cost:.6f}",
                "model": output["model"],
            },
        )
    except (asyncio.CancelledError, GeneratorExit):
        status = 2
        raise
    except Exception as exc:
        status = 3
        log.exception("Chat failed (session %s)", session["id"])
        terminal = ("error", {"code": 90001, "message": str(exc)})
    finally:

        async def persist():
            if message_id is not None:
                async with runtime.db.engine.begin() as tx:
                    await tx.execute(
                        insert(t.messages).values(
                            session_id=session["id"],
                            role="assistant",
                            content=output["content"],
                            reasoning_content=output["reasoning"],
                            tool_calls=output["tool_calls"],
                            refs=output.get("refs", []),
                            model_name=output["model"],
                            status=status,
                            prompt_tokens=output["prompt_tokens"],
                            completion_tokens=output["completion_tokens"],
                            first_token_ms=output.get("first_token_ms", 0),
                            latency_ms=int((time.monotonic() - started) * 1000),
                            metadata={"agent_trace": output["trace"]},
                        )
                    )
                    await tx.execute(
                        update(t.sessions)
                        .where(t.sessions.c.id == session["id"])
                        .values(
                            message_count=t.sessions.c.message_count + 2,
                            last_msg_at=t.now(),
                            updated_at=t.now(),
                            token_usage=t.sessions.c.token_usage
                            + output["prompt_tokens"]
                            + output["completion_tokens"],
                        )
                    )
                    await tx.execute(
                        insert(t.usage).values(
                            user_id=user["id"],
                            agent_id=agent["id"],
                            session_id=session["id"],
                            model=output["model"],
                            prompt_tokens=output["prompt_tokens"],
                            completion_tokens=output["completion_tokens"],
                            cost_amount=output.get("cost", 0),
                        )
                    )
                    count = await tx.scalar(
                        select(t.sessions.c.message_count).where(t.sessions.c.id == session["id"])
                    )
                    every = runtime.cfg.memory_extract_every
                    if status == 1 and agent.get("memory_long_enabled") and every > 0 and count % every == 0:
                        await tx.execute(
                            insert(t.jobs).values(
                                kind="memory_extract",
                                payload={
                                    "session_id": session["id"],
                                    "user_id": user["id"],
                                    "agent_id": agent["id"],
                                },
                            )
                        )

        async def finalize():
            try:
                await persist()
            finally:
                try:
                    if locked:
                        await conn.execute(
                            text("SELECT pg_advisory_unlock(hashtextextended(:id, 0))"), {"id": session["id"]}
                        )
                except Exception:
                    # Never return a connection with a held session lock to the pool.
                    await conn.invalidate()
                    raise
                finally:
                    await conn.close()

        task = asyncio.create_task(finalize())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
    yield sse(*terminal)


async def list_sessions(rt, user, paging):
    return await rt.db.paged(
        t.sessions,
        t.sessions.c.user_id == user["id"],
        t.sessions.c.status == "active",
        order_by=(
            t.sessions.c.pinned.desc(),
            func.coalesce(t.sessions.c.last_msg_at, t.sessions.c.created_at).desc(),
            t.sessions.c.id.desc(),
        ),
        **paging,
    )


async def messages(rt, user, ident):
    await owned(rt, t.sessions, str(ident), user)
    return await rt.db.rows(t.messages, t.messages.c.session_id == str(ident), limit=10000, ascending=True)


async def rename_session(rt, user, ident, body):
    await owned(rt, t.sessions, str(ident), user)
    title = body.get("title", "").strip()
    if not 1 <= len(title) <= 256:
        raise ValueError("标题长度必须为1至256")
    return await rt.db.change(t.sessions, str(ident), {"title": title})


async def delete_session(rt, user, ident):
    await owned(rt, t.sessions, str(ident), user)
    rows = await rt.db.rows(t.messages, t.messages.c.session_id == str(ident), limit=100000)
    for row in rows:
        if row["role"] == "user":
            await rt.checkpointer.adelete_thread(f"chat:{ident}:{row['id']}")
    await rt.db.remove(t.sessions, str(ident))
    return None
