from contextlib import asynccontextmanager

from sqlalchemy import text


@asynccontextmanager
async def resource_lock(db, name):
    """Session advisory locks release even if the API/worker is disconnected."""
    async with db.engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(hashtextextended(:name,0))"), {"name": name})
        try:
            yield
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:name,0))"), {"name": name})
