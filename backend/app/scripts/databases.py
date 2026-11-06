"""Create the configured logical databases on the existing local database services."""

import asyncio

import psycopg
from psycopg import sql
from pymilvus import MilvusClient
from sqlalchemy.engine import make_url


async def create_databases(cfg):
    url = make_url(cfg.database_url)
    if not url.database:
        raise ValueError("ZHIXING_DATABASE_URL 必须指定数据库名称")

    def postgres():
        admin_url = url.set(drivername="postgresql", database="postgres")
        with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)).fetchone():
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(url.database)))

    def milvus():
        client = MilvusClient(uri=cfg.milvus_uri)
        try:
            if cfg.milvus_database not in client.list_databases():
                client.create_database(cfg.milvus_database)
        finally:
            client.close()

    await asyncio.to_thread(postgres)
    await asyncio.to_thread(milvus)


async def main():
    from app.core.config import settings

    cfg = settings()
    await create_databases(cfg)
    print(f"数据库就绪：PostgreSQL / {make_url(cfg.database_url).database}，Milvus / {cfg.milvus_database}")
