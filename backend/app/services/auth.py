import jwt

from app import models as t
from app.core.errors import ServiceError
from app.core.security import passwords


def public_user(user):
    return {key: user[key] for key in ("id", "username", "email", "role", "avatar_url")}


async def register(rt, body):
    user = await rt.db.add(
        t.users, {**body.model_dump(exclude={"password"}), "password_hash": passwords.hash(body.password)}
    )
    return public_user(user)


async def login(rt, body):
    users = await rt.db.rows(t.users, t.users.c.username == body.username, t.users.c.status == 1, limit=1)
    if not users or not passwords.verify(body.password, users[0]["password_hash"]):
        raise ServiceError(401, "用户名或密码错误")
    return await rt.security.tokens(users[0])


async def refresh(rt, body):
    try:
        return await rt.security.refresh(body.get("refresh_token", ""), rt.db, t.users)
    except jwt.InvalidTokenError as exc:
        raise ServiceError(401, "刷新令牌失效") from exc


async def logout(rt, user):
    await rt.redis.delete(f"nx:refresh:{user['id']}")
    return None


async def me(user):
    return public_user(user)
