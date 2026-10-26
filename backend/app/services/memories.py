from app import models as t
from app.services.access import owned


async def list_memories(rt, user, paging):
    return await rt.db.paged(t.memories, t.memories.c.user_id == user["id"], **paging)


async def extract_memory(rt, user, body):
    session = await owned(rt, t.sessions, body.get("session_id", ""), user)
    return await rt.db.add(
        t.jobs,
        {
            "kind": "memory_extract",
            "payload": {
                "session_id": session["id"],
                "user_id": user["id"],
                "agent_id": session["agent_id"] or 0,
            },
        },
    )


async def archive_memory(rt, user, ident):
    await owned(rt, t.memories, ident, user)
    await rt.db.change(t.memories, ident, {"status": 2})
    await rt.db.add(t.jobs, {"kind": "memory_delete", "payload": {"memory_id": ident}})
    return None


async def delete_memory(rt, user, ident):
    await owned(rt, t.memories, ident, user)
    await rt.db.remove(t.memories, ident)
    await rt.db.add(t.jobs, {"kind": "memory_delete", "payload": {"memory_id": ident}})
    return None
