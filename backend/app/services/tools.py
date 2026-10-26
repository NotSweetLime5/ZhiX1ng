import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from simpleeval import simple_eval
from sqlalchemy import text

from app import models as t
from app.core.serialization import serial
from app.core.observability import operation


def schema(properties, required):
    return {"type": "object", "properties": properties, "required": required}


BUILTINS = [
    (
        "calculator",
        "计算器",
        "计算数学表达式",
        schema({"expression": {"type": "string"}}, ["expression"]),
        False,
    ),
    (
        "datetime",
        "时间日期",
        "获取时间或增加天数",
        schema(
            {"operation": {"type": "string"}, "tz": {"type": "string"}, "days": {"type": "integer"}},
            ["operation"],
        ),
        False,
    ),
    (
        "web_search",
        "网络搜索",
        "搜索互联网",
        schema({"query": {"type": "string"}, "count": {"type": "integer"}}, ["query"]),
        False,
    ),
    (
        "http_client",
        "HTTP请求",
        "访问配置允许的域名",
        schema(
            {
                "url": {"type": "string"},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            ["url"],
        ),
        False,
    ),
    (
        "kb_search",
        "知识库检索",
        "检索当前用户知识库",
        schema(
            {"kb_id": {"type": "integer"}, "query": {"type": "string"}, "top_k": {"type": "integer"}},
            ["kb_id", "query"],
        ),
        False,
    ),
    (
        "file_ops",
        "文件操作",
        "读写授权目录文件",
        schema(
            {"operation": {"type": "string"}, "path": {"type": "string"}, "content": {"type": "string"}},
            ["operation", "path"],
        ),
        True,
    ),
    ("db_query", "数据库查询", "管理员只读 SQL 查询", schema({"sql": {"type": "string"}}, ["sql"]), True),
    (
        "code_exec",
        "代码执行",
        "在无网络容器内执行 python/go/shell",
        schema({"language": {"type": "string"}, "code": {"type": "string"}}, ["language", "code"]),
        True,
    ),
]


class Tools:
    def __init__(self, db, rag, cfg):
        self.db, self.rag, self.cfg = db, rag, cfg

    def mcp_connection(self, server):
        if server["transport"] not in {"streamable_http", "sse"}:
            raise ValueError("仅支持 streamable_http 和 sse MCP 服务")
        return {"transport": server["transport"], "url": server["url"], "headers": server["headers"]}

    async def remote_tools(self, server):
        client = MultiServerMCPClient({str(server["id"]): self.mcp_connection(server)})
        return await client.get_tools()

    async def sync_mcp(self, server):
        remote = await self.remote_tools(server)
        existing = await self.db.rows(t.tools, t.tools.c.mcp_server_id == server["id"], limit=10000)
        found = set()
        for tool in remote:
            code = f"mcp_{server['id']}_{tool.name}"
            found.add(code)
            if len(code) > 64:
                raise ValueError("MCP 工具名称过长")
            values = {
                "code": code,
                "name": tool.name,
                "description": tool.description or tool.name,
                "type": "mcp",
                "parameters": convert_to_openai_tool(tool)["function"]["parameters"],
                "mcp_server_id": server["id"],
                "handler": tool.name,
                "status": 1,
                "timeout_ms": 60000,
            }
            old = next((x for x in existing if x["code"] == code), None)
            if old:
                await self.db.change(t.tools, old["id"], values)
            else:
                await self.db.add(t.tools, values)
        for old in existing:
            if old["code"] not in found:
                await self.db.change(t.tools, old["id"], {"status": 0})
        await self.db.change(
            t.mcp_servers,
            server["id"],
            {
                "tools_cache": [convert_to_openai_tool(x)["function"] for x in remote],
                "status": "connected",
                "last_health_at": t.now(),
            },
        )
        return len(remote)

    async def build(self, bindings, user, approved=False):
        result = []
        for binding in bindings:
            row = await self.db.get(t.tools, binding.get("tool_id", 0))
            if not row and binding.get("tool_code"):
                matches = await self.db.rows(t.tools, t.tools.c.code == binding["tool_code"], limit=1)
                row = matches[0] if matches else None
            if not row or row["status"] != 1:
                raise ValueError("Agent 绑定了不可用工具")
            # No in-memory registration gap: persisted MCP bindings reconstruct on every run.
            target = None
            if row["type"] == "mcp":
                server = await self.db.get(t.mcp_servers, row["mcp_server_id"])
                if not server:
                    raise ValueError("MCP 服务不存在")
                remote = await self.remote_tools(server)
                target = next((tool for tool in remote if tool.name == row["handler"]), None)
                if not target:
                    raise ValueError("MCP 工具已移除，请重新同步")

            merged_config = {**row["default_config"], **binding.get("config", {})}

            async def call(_row=row, _config=merged_config, _target=target, **args):
                try:
                    if _row["is_dangerous"] and not approved:
                        raise ValueError("此工具需要人工审批，请通过包含 human 节点的工作流调用。")
                    with operation("tool." + _row["code"], tool=_row["code"]):
                        async with asyncio.timeout(_row["timeout_ms"] / 1000):
                            output = (
                                await _target.ainvoke({**_config, **args})
                                if _target is not None
                                else await self.invoke(_row["code"], {**_config, **args}, user, approved)
                            )
                    return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
                except TimeoutError:
                    return json.dumps({"error": "工具调用超时", "status": "timeout"}, ensure_ascii=False)
                except Exception as exc:
                    return json.dumps({"error": str(exc)}, ensure_ascii=False)

            result.append(
                StructuredTool.from_function(
                    name=row["code"],
                    description=row["description"],
                    coroutine=call,
                    args_schema=row["parameters"],
                )
            )
        return result

    async def call(self, code, args, user, approved=False):
        matches = await self.db.rows(t.tools, t.tools.c.code == code, t.tools.c.status == 1, limit=1)
        if not matches:
            raise ValueError(f"未知工具 {code}")
        row = matches[0]
        if row["is_dangerous"] and not approved:
            raise ValueError("危险工具需要前置 human 审批节点")
        tools = await self.build([{"tool_id": row["id"]}], user, approved)
        value = await tools[0].ainvoke(args)
        if isinstance(value, str) and value.startswith('{"error":'):
            raise RuntimeError(value)
        return value

    async def invoke(self, code, args, user, approved=False):
        if code == "calculator":
            return str(simple_eval(args["expression"], names={}, functions={}))
        if code == "datetime":
            stamp = datetime.now(ZoneInfo(args.get("tz", "Asia/Shanghai")))
            op = args.get("operation", "now")
            if op == "add_days":
                stamp += timedelta(days=args.get("days", 0))
            elif op == "diff":
                year_end = datetime(stamp.year + 1, 1, 1, tzinfo=stamp.tzinfo)
                return f"{int((year_end - stamp).total_seconds() / 86400)} days until {stamp.year + 1}-01-01"
            elif op != "now":
                raise ValueError("支持 now、add_days 和 diff")
            return stamp.isoformat()
        if code == "kb_search":
            return await self.rag.retrieve(
                user["id"], args["kb_id"], args["query"], min(20, max(1, args.get("top_k", 5)))
            )
        if code == "web_search":
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(
                    self.cfg.searxng_url, params={"q": args["query"], "format": "json", "language": "zh-CN"}
                )
                res.raise_for_status()
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("content", "")[:200],
                    }
                    for r in res.json().get("results", [])[: min(20, max(1, args.get("count", 5)))]
                ]
        if code == "http_client":
            url = urlparse(args["url"])
            allowed = any(
                url.hostname == host or (url.hostname or "").endswith("." + host)
                for host in self.cfg.allowed_http_hosts
            )
            if url.scheme not in {"http", "https"} or not allowed or url.username or url.password:
                raise ValueError("域名未列入 NX_ALLOWED_HTTP_HOSTS")
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                async with client.stream("GET", args["url"], headers=args.get("headers", {})) as res:
                    chunks = bytearray()
                    async for chunk in res.aiter_bytes():
                        chunks.extend(chunk[: max(0, 256 * 1024 - len(chunks))])
                        if len(chunks) >= 256 * 1024:
                            break
                    content = BeautifulSoup(
                        chunks.decode(res.encoding or "utf-8", errors="replace"), "html.parser"
                    ).get_text(" ", strip=True)
                    return {"status": res.status_code, "content": " ".join(content.split())[:4000]}
        if code == "file_ops":
            root = (Path(self.cfg.file_root) / str(user["id"])).resolve()
            path = (root / args["path"]).resolve()
            if not path.is_relative_to(root) or path == root:
                raise ValueError("路径超出用户授权目录")

            def operate():
                if args["operation"] == "read":
                    if path.stat().st_size > 10 * 1024 * 1024:
                        raise ValueError("文件过大")
                    return path.read_text(encoding="utf-8")
                if args["operation"] != "save":
                    raise ValueError("支持 read 和 save")
                content = args.get("content", "")
                if len(content.encode()) > 10 * 1024 * 1024:
                    raise ValueError("文件过大")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return {"saved": args["path"], "bytes": len(content.encode("utf-8"))}

            return await asyncio.to_thread(operate)
        if code == "db_query":
            if user["role"] != "admin":
                raise ValueError("数据库查询工具仅管理员可用")
            sql = args["sql"].strip().rstrip(";")
            if not sql.lower().startswith("select ") or ";" in sql:
                raise ValueError("仅允许单条 SELECT")
            async with self.db.engine.begin() as conn:
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                await conn.execute(text("SET LOCAL statement_timeout = '5s'"))
                rows = (await conn.execute(text(sql))).mappings().fetchmany(100)
                return serial([dict(x) for x in rows])
        if code == "code_exec":
            if not self.cfg.sandbox_enabled:
                raise ValueError("代码沙箱未启用")
            result = await asyncio.to_thread(self.sandbox, args)
            if self.db is not None:
                await self.db.add(
                    t.sandbox_executions,
                    {
                        "user_id": user["id"],
                        "tool_call_id": "exec_" + uuid.uuid4().hex,
                        "language": args["language"],
                        "code_hash": hashlib.sha256(args["code"].encode()).hexdigest(),
                        "exit_code": result["exit_code"],
                        "duration_ms": result["duration"],
                        "stdout_head": result["stdout"][:8192],
                        "stderr_head": result["stderr"][:8192],
                    },
                )
            return result
        raise ValueError(f"没有实现的工具 {code}")

    def sandbox(self, args):
        import docker

        started = time.monotonic()
        client = docker.from_env()
        language = args["language"]
        if language == "python":
            command = ["python", "-c", args["code"]]
        elif language == "shell":
            command = ["sh", "-c", args["code"]]
        elif language == "go":
            command = ["sh", "-c", "printf '%s' \"$ZHIXING_CODE\" > /tmp/main.go && go run /tmp/main.go"]
        else:
            raise ValueError("不支持的语言")
        container = None
        try:
            container = client.containers.run(
                self.cfg.sandbox_image,
                command=command,
                detach=True,
                network_disabled=True,
                mem_limit="512m",
                nano_cpus=1000000000,
                pids_limit=64,
                read_only=True,
                # Go compiles a binary into /tmp before running it. Docker tmpfs is
                # otherwise noexec, which makes every Go execution fail after build.
                tmpfs={"/tmp": "rw,exec,nosuid,nodev,size=128m"},
                user="65534:65534",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                environment={"ZHIXING_CODE": args["code"], "GOCACHE": "/tmp/gocache"},
            )
            result = container.wait(timeout=self.cfg.sandbox_timeout)
            stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")[:50000]
            stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")[:50000]
            return {
                "exit_code": result["StatusCode"],
                "output": container.logs().decode(errors="replace")[:50000],
                "stdout": stdout,
                "stderr": stderr,
                "duration": int((time.monotonic() - started) * 1000),
            }
        finally:
            if container:
                container.remove(force=True)
            client.close()
