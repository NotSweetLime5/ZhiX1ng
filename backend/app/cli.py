"""Portable entrypoints; set the Windows event loop before Uvicorn starts."""

import argparse
import asyncio
import json
import sys


def configure_loop():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def loop_factory():
    return asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()


async def conversation(agent_id):
    from app import models as t
    from app.core.config import settings
    from app.runtime import Runtime
    from app.schemas import ChatInput
    from app.services.chat import prepare, stream

    rt = await Runtime(settings()).start()
    try:
        users = await rt.db.rows(t.users, t.users.c.username == "admin", limit=1)
        if not users:
            raise RuntimeError("请先执行 migrate 和 seed")
        session_id = None
        while True:
            content = await asyncio.to_thread(input, "you> ")
            if content.strip() in {"exit", "quit"}:
                return
            if not content.strip():
                continue
            request = ChatInput(content=content, agent_id=agent_id, session_id=session_id)
            agent, session = await prepare(rt, users[0], request)
            session_id = session["id"]
            print("agent> ", end="", flush=True)
            async for frame in stream(rt, users[0], request, agent, session):
                event, raw = frame.splitlines()[:2]
                data = json.loads(raw[6:])
                if event == "event: delta":
                    print(data["content"], end="", flush=True)
                elif event == "event: error":
                    print(data["message"], flush=True)
            print()
    finally:
        await rt.close()


def main():
    configure_loop()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "worker", "migrate", "seed", "chat"])
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--agent", type=int, default=0)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("app.main:app", host=args.host, port=args.port, loop="app.cli:loop_factory")
    elif args.command == "migrate":
        from alembic.config import Config

        from alembic import command

        command.upgrade(Config("alembic.ini"), "head")
    elif args.command == "seed":
        from app.scripts.seed import main as seed

        asyncio.run(seed())
    elif args.command == "worker":
        from app.worker import main as worker

        asyncio.run(worker())
    else:
        asyncio.run(conversation(args.agent))


if __name__ == "__main__":
    main()
