"""Original standalone A2A port, isolated from the authenticated administration API."""

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.dialects.postgresql import insert

from app import models as t
from app.api.routes.a2a import router
from app.core.config import settings
from app.core.observability import configure_tracing
from app.core.security import passwords
from app.runtime import Runtime


async def service_user(rt):
    async with rt.db.engine.begin() as conn:
        await conn.execute(
            insert(t.users)
            .values(
                username="__a2a_service__",
                email="__a2a_service__@localhost.invalid",
                password_hash=passwords.hash(secrets.token_urlsafe(48)),
                role="service",
                status=0,
            )
            .on_conflict_do_nothing(index_elements=["username"])
        )
    user = (await rt.db.rows(t.users, t.users.c.username == "__a2a_service__", limit=1))[0]
    if user["role"] != "service" or user["status"] != 0:
        raise RuntimeError("A2A reserved service account conflicts with an existing account")
    return user


@asynccontextmanager
async def lifespan(app):
    rt = await Runtime(settings()).start()
    app.state.runtime = rt
    try:
        app.state.a2a_user = await service_user(rt)
        yield
    finally:
        await rt.close()


app = FastAPI(title="Zhixing A2A", lifespan=lifespan)
app.state.a2a_legacy = True
app.include_router(router)
configure_tracing(settings(), "zhixing-a2a", app)
