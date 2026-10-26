from app.core.errors import ServiceError


async def owned(rt, table, ident, user, owner="user_id"):
    row = await rt.db.get(table, ident, table.c[owner] == user["id"])
    if not row:
        raise ServiceError(404, "资源不存在或无权访问")
    return row
