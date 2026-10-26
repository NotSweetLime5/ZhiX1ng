"""Portable entrypoints; set the Windows event loop before Uvicorn starts."""

import argparse
import asyncio
import getpass
import os
import sys


def configure_loop():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def loop_factory():
    return asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()


async def conversation(args):
    import httpx

    from app.terminal import TerminalClient

    username = args.user or await asyncio.to_thread(input, "用户名> ")
    password = (
        args.password
        or os.environ.get("NX_CLI_PASSWORD")
        or await asyncio.to_thread(getpass.getpass, "密码> ")
    )
    async with httpx.AsyncClient(base_url=args.addr.rstrip("/"), timeout=None) as http:
        client = TerminalClient(http, args.agent)
        await client.login(username, password)
        print("已登录，输入消息开始对话（/quit 退出）。")
        while True:
            try:
                content = await asyncio.to_thread(input, "you> ")
            except EOFError:
                return
            if content.strip() in {"exit", "quit", "/quit"}:
                return
            if not content.strip():
                continue
            print("agent> ", end="", flush=True)
            try:
                async for event, data in client.events(content):
                    if event == "delta":
                        print(data["content"], end="", flush=True)
                    elif event == "error":
                        print(data["message"], flush=True)
                    elif event == "tool_call":
                        print(f"\n工具调用: {data['name']}({data.get('args', '')})", flush=True)
                    elif event == "tool_result":
                        print(f"\n工具结果: {data.get('status', '')}", flush=True)
                    elif event == "agent_event":
                        print(f"\n{data.get('type', '')}: {data.get('expert', '')}", flush=True)
                    elif event == "refs":
                        print(f"\n引用资料: {len(data.get('items', []))} 条", flush=True)
            except (httpx.HTTPError, ValueError) as exc:
                print(f"\n对话失败: {exc}", flush=True)
            print()


def main():
    configure_loop()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["serve", "a2a", "mcp", "worker", "createdb", "migrate", "seed", "chat"]
    )
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--agent", type=int, default=0)
    parser.add_argument("--addr", "-addr", default="http://127.0.0.1:8080")
    parser.add_argument("--user", "-user")
    parser.add_argument("--password", "--pass", "-pass", dest="password")
    args = parser.parse_args()
    if args.command in {"serve", "a2a"}:
        import uvicorn
        from app.core.config import settings

        module = "app.main:app" if args.command == "serve" else "app.a2a_server:app"
        port = args.port or (8080 if args.command == "serve" else settings().a2a_port)
        uvicorn.run(module, host=args.host, port=port, loop="app.cli:loop_factory")
    elif args.command == "mcp":
        from app.mcp_server import create_server

        create_server(args.host, args.port).run(transport="streamable-http")
    elif args.command == "createdb":
        from app.scripts.databases import main as createdb

        asyncio.run(createdb())
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
        asyncio.run(conversation(args))


if __name__ == "__main__":
    main()
