"""Async PostgreSQL data access and transaction entrypoint."""

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.serialization import serial
from app.models.base import now


class Database:
    def __init__(self, url):
        self.engine = create_async_engine(url, pool_pre_ping=True)

    async def get(self, tab, ident, *where):
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(tab).where(tab.c.id == ident, *where))).mappings().first()
            return dict(row) if row else None

    async def rows(self, tab, *where, limit=100, offset=0, ascending=False):
        async with self.engine.connect() as conn:
            order = tab.c.id.asc() if ascending else tab.c.id.desc()
            result = await conn.execute(select(tab).where(*where).order_by(order).limit(limit).offset(offset))
            return [dict(r) for r in result.mappings()]

    async def paged(self, tab, *where, page=1, page_size=20, keyword=""):
        filters = list(where)
        if keyword and "name" in tab.c:
            filters.append(tab.c.name.ilike(f"%{keyword}%"))
        async with self.engine.connect() as conn:
            total = await conn.scalar(select(func.count()).select_from(tab).where(*filters))
        rows = await self.rows(tab, *filters, limit=page_size, offset=(page - 1) * page_size)
        return {"list": serial(rows), "total": total}

    async def add(self, tab, values):
        async with self.engine.begin() as conn:
            row = (await conn.execute(insert(tab).values(**values).returning(tab))).mappings().one()
            return dict(row)

    async def change(self, tab, ident, values):
        if "updated_at" in tab.c:
            values = {**values, "updated_at": now()}
        async with self.engine.begin() as conn:
            row = (
                (await conn.execute(update(tab).where(tab.c.id == ident).values(**values).returning(tab)))
                .mappings()
                .first()
            )
            return dict(row) if row else None

    async def remove(self, tab, ident):
        async with self.engine.begin() as conn:
            await conn.execute(delete(tab).where(tab.c.id == ident))
