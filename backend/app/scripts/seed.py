import asyncio
import secrets

from sqlalchemy import insert, select, text

from app import models as t
from app.core.config import settings
from app.core.security import passwords
from app.repositories.database import Database
from app.services.tools import BUILTINS


def bootstrap_password(cfg):
    password = cfg.admin_password or secrets.token_urlsafe(24)
    if len(password) < 16 or password.startswith("replace-with-"):
        raise ValueError("首次初始化需要至少16字符的 ZHIXING_ADMIN_PASSWORD；留空则自动生成")
    return password, not bool(cfg.admin_password)


async def seed(db, cfg):
    generated_password = None
    async with db.engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(7171717)"))
        admin = (await conn.execute(select(t.users).where(t.users.c.username == "admin"))).mappings().first()
        if not admin:
            password, generated = bootstrap_password(cfg)
            if generated:
                generated_password = password
            admin = (
                (
                    await conn.execute(
                        insert(t.users)
                        .values(
                            username="admin",
                            email="admin@zhixing.local",
                            role="admin",
                            password_hash=passwords.hash(password),
                        )
                        .returning(t.users)
                    )
                )
                .mappings()
                .one()
            )
        for code, name, url in [
            ("deepseek", "DeepSeek", "https://api.deepseek.com/v1"),
            ("ollama", "Ollama", "http://127.0.0.1:11435/v1"),
        ]:
            provider = (
                (await conn.execute(select(t.providers).where(t.providers.c.code == code))).mappings().first()
            )
            if not provider:
                provider = (
                    (
                        await conn.execute(
                            insert(t.providers)
                            .values(code=code, name=name, base_url=url)
                            .returning(t.providers)
                        )
                    )
                    .mappings()
                    .one()
                )
            model_name = "deepseek-chat" if code == "deepseek" else "bge-m3"
            model = await conn.scalar(select(t.models.c.id).where(t.models.c.alias == model_name))
            if not model:
                await conn.execute(
                    insert(t.models).values(
                        provider_id=provider["id"],
                        model_name=model_name,
                        alias=model_name,
                        type="chat" if code == "deepseek" else "embedding",
                        is_default=True,
                    )
                )
        for code, name, description, parameters, dangerous in BUILTINS:
            if not await conn.scalar(select(t.tools.c.id).where(t.tools.c.code == code)):
                await conn.execute(
                    insert(t.tools).values(
                        code=code,
                        name=name,
                        description=description,
                        parameters=parameters,
                        handler=code,
                        is_dangerous=dangerous,
                    )
                )
        model_id = await conn.scalar(select(t.models.c.id).where(t.models.c.alias == "deepseek-chat"))
        calculator = await conn.scalar(select(t.tools.c.id).where(t.tools.c.code == "calculator"))
        if not await conn.scalar(select(t.agents.c.id).where(t.agents.c.is_preset.is_(True))):
            await conn.execute(
                insert(t.agents).values(
                    name="通用专家",
                    creator_id=admin["id"],
                    is_preset=True,
                    description="通用问答和数学计算",
                    system_prompt="你是通用专家，必要时调用计算器。",
                    model_config_id=model_id,
                    tools=[{"tool_id": calculator}],
                )
            )
            await conn.execute(
                insert(t.agents).values(
                    name="Host 路由助手",
                    type="host",
                    creator_id=admin["id"],
                    is_preset=True,
                    description="选择合适专家完成任务",
                    system_prompt="你是任务路由助手。",
                    model_config_id=model_id,
                )
            )
    return generated_password


async def main():
    cfg = settings()
    db = Database(cfg.database_url)
    try:
        generated_password = await seed(db, cfg)
        if generated_password:
            print(f"已创建管理员 admin，一次性密码：{generated_password}，请妥善保存。")
    finally:
        await db.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
