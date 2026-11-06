import asyncio
import json
import re
from typing import Annotated, TypedDict

import yaml
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from simpleeval import EvalWithCompoundTypes
from sqlalchemy.dialects.postgresql import insert

from app import models as t
from app.core.serialization import serial


class Rejected(Exception):
    pass


class WorkflowLoader(yaml.SafeLoader):
    """Keep YAML identifiers such as yes/no/on/off as strings."""


WorkflowLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in values if tag != "tag:yaml.org,2002:bool"]
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
WorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false|True|False|TRUE|FALSE)$"), list("tTfF")
)


def merge(left, right):
    return {**left, **right}


class State(TypedDict, total=False):
    values: Annotated[dict, merge]
    approved: bool
    approval_comment: str


def parse_dsl(raw):
    data = yaml.load(raw, Loader=WorkflowLoader)
    if not isinstance(data, dict) or not data.get("name"):
        raise ValueError("DSL 必须包含 name")
    nodes = data.get("nodes", [])
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 100:
        raise ValueError("nodes 必须包含1至100个节点")
    keys = [n.get("key") for n in nodes if isinstance(n, dict)]
    if len(keys) != len(nodes) or any(
        not isinstance(k, str) or not re.fullmatch(r"[A-Za-z][\w-]{0,63}", k) for k in keys
    ):
        raise ValueError("节点 key 必须为字母开头的有效名称")
    if len(set(keys)) != len(keys):
        raise ValueError("节点 key 重复")
    allowed = {"llm", "tool", "kb", "condition", "parallel", "human", "subflow"}
    branches = set()
    adj = {key: [] for key in keys}
    for node in nodes:
        kind = node.get("type")
        if kind not in allowed:
            raise ValueError(f"未知节点类型：{kind}")
        required = {
            "llm": ["prompt"],
            "tool": ["tool_code"],
            "kb": ["kb_id", "query"],
            "condition": [],
            "parallel": ["branches"],
            "subflow": ["workflow"],
        }.get(kind, [])
        if any(not node.get(field) for field in required):
            raise ValueError(f"节点 {node['key']} 缺少必要字段：{required}")
        references = (
            node.get("branches", [])
            if kind == "parallel"
            else (
                [target for target in (node.get("then"), node.get("else")) if target]
                if kind == "condition"
                else []
            )
        )
        for reference in references:
            if reference not in keys:
                raise ValueError(f"节点引用不存在：{reference}")
            adj[node["key"]].append(reference)
        if kind == "parallel":
            branches.update(references)
            for target in references:
                branch = next(n for n in nodes if n["key"] == target)
                if branch["type"] == "human":
                    raise ValueError("human 审批必须位于主流程或子工作流，不能在 parallel 中绕过审批")
    edges = data.get("edges")
    if not edges:
        linear = [k for k in keys if k not in branches]
        edges = [{"from": a, "to": b} for a, b in zip(linear, linear[1:], strict=False)]
    elif isinstance(edges, list) and all(isinstance(x, str) for x in edges):
        edges = [{"from": a, "to": b} for a, b in zip(edges, edges[1:], strict=False)]
    if not isinstance(edges, list):
        raise ValueError("edges 必须为数组")
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("from") not in keys or edge.get("to") not in keys:
            raise ValueError("边引用不存在的节点")
        adj[edge["from"]].append(edge["to"])
    for node in nodes:
        if node["type"] == "condition":
            fallback = next((edge["to"] for edge in edges if edge["from"] == node["key"]), END)
            node["then"] = node.get("then") or fallback
            node["else"] = node.get("else") or fallback
    color = {}

    def visit(key):
        if color.get(key) == 1:
            raise ValueError("工作流包含环")
        if color.get(key) == 2:
            return
        color[key] = 1
        for child in adj[key]:
            visit(child)
        color[key] = 2

    for key in keys:
        visit(key)
    if data.get("out") and data["out"] not in keys:
        raise ValueError("out 引用不存在的节点")
    data["edges"] = edges
    data["branch_keys"] = branches
    return data


def render(value, state):
    if isinstance(value, dict):
        return {k: render(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, state) for v in value]
    if not isinstance(value, str):
        return value

    def resolve(match):
        path = match.group(1).strip().split(".")
        current = state
        for key in path:
            if key == "result" and not isinstance(current, dict):
                continue
            if not isinstance(current, dict) or key not in current:
                return match.group(0)
            current = current[key]
        return current if isinstance(current, str) else json.dumps(current, ensure_ascii=False)

    return re.sub(r"{{\s*([^{}]+?)\s*}}", resolve, value)


def condition(expression, values):
    if not isinstance(expression, str):
        expression = "" if expression is None else str(expression)
    if not expression.strip():
        return True
    # Preserve quoted text: words/operators inside literals are user data.
    segments = re.split(r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')""", expression)
    for index in range(0, len(segments), 2):
        part = segments[index].replace("&&", " and ").replace("||", " or ")
        part = re.sub(r"!(?!=)", " not ", part)
        segments[index] = re.sub(
            r"\b(true|false|nil)\b",
            lambda m: {
                "true": "True",
                "false": "False",
                "nil": "None",
            }[m.group()],
            part,
        )
    return bool(EvalWithCompoundTypes(names=values, functions={}).eval("".join(segments).strip()))


class Workflow:
    def __init__(self, db, gateway, tools, rag, checkpointer):
        self.db, self.gateway, self.tools, self.rag, self.checkpointer = db, gateway, tools, rag, checkpointer

    async def snapshot(self, run_id, node, status, state, output=None, error=""):
        values = {
            "run_id": run_id,
            "node_key": node["key"],
            "node_type": node["type"],
            "status": status,
            "input": serial(state),
            "output": {"result": serial(output)},
            "error": error,
            "finished_at": t.now() if status in {"succeeded", "failed"} else None,
        }
        async with self.db.engine.begin() as conn:
            stmt = insert(t.steps).values(**values)
            await conn.execute(stmt.on_conflict_do_update(index_elements=["run_id", "node_key"], set_=values))

    async def execute(self, node, state, user, dsl, run_id, config, stack):
        async with asyncio.timeout(min(300, max(1, node.get("timeout_s", 60)))):
            return await self._execute(node, state, user, dsl, run_id, config, stack)

    async def _execute(self, node, state, user, dsl, run_id, config, stack):
        kind, values = node["type"], state["values"]
        if kind == "llm":
            desc = await self.gateway.resolve(alias=node.get("model"))
            result = await self.gateway.invoke(
                desc, [{"role": "user", "content": render(node["prompt"], values)}], config
            )
            return result.content
        if kind == "kb":
            refs = await self.rag.retrieve(user["id"], node["kb_id"], render(node["query"], values))
            return refs
        if kind == "tool":
            return await self.tools.call(
                node["tool_code"], render(node.get("args", {}), values), user, state.get("approved", False)
            )
        if kind == "condition":
            return condition(node.get("expr", ""), values)
        if kind == "parallel":

            async def branch(key):
                target = next(n for n in dsl["nodes"] if n["key"] == key)
                return await self.execute(target, state, user, dsl, run_id, config, stack)

            outputs = await asyncio.gather(*(branch(key) for key in node["branches"]))
            return dict(zip(node["branches"], outputs, strict=True))
        if kind == "subflow":
            workflow_id = node["workflow"]
            if workflow_id in stack or len(stack) >= 8:
                raise ValueError("子工作流递归或嵌套过深")
            child = await self.db.get(t.workflows, workflow_id, t.workflows.c.creator_id == user["id"])
            if not child:
                raise ValueError("子工作流不存在或无权访问")
            # The nested graph uses the parent's checkpoint namespace. GraphInterrupt
            # bubbles through the parent node, so nested human nodes resume correctly.
            child_graph = await self.compile(
                parse_dsl(child["dsl"]),
                user,
                run_id,
                (*stack, workflow_id),
                prefix=node["key"] + "__",
                checkpoint=None,
            )
            result = await child_graph.ainvoke(
                {"values": values, "approved": state.get("approved", False)}, config
            )
            return result["values"]
        raise ValueError(f"未知节点类型 {kind}")

    async def compile(self, dsl, user, run_id, stack=(), prefix="", checkpoint=True):
        graph = StateGraph(State)
        primary_nodes = [n for n in dsl["nodes"] if n["key"] not in dsl["branch_keys"]]
        for node in primary_nodes:

            async def run_node(state, config, _node=node):
                snapshot_node = {**_node, "key": prefix + _node["key"]}
                if _node["type"] == "human":
                    await self.snapshot(run_id, snapshot_node, "waiting_approval", state["values"])
                    decision = interrupt(
                        {
                            "node_key": prefix + _node["key"],
                            "prompt": render(_node.get("prompt", "请审批"), state["values"]),
                        }
                    )
                    if not decision.get("approved"):
                        raise Rejected(decision.get("comment") or "人工审批驳回")
                    await self.snapshot(run_id, snapshot_node, "succeeded", state["values"], decision)
                    return {
                        "values": {_node["key"]: decision},
                        "approved": True,
                        "approval_comment": decision.get("comment", ""),
                    }
                try:
                    async with asyncio.timeout(min(300, max(1, _node.get("timeout_s", 60)))):
                        value = await self.execute(_node, state, user, dsl, run_id, config, stack)
                    await self.snapshot(run_id, snapshot_node, "succeeded", state["values"], value)
                    result = {_node["key"]: value}
                    if _node["type"] == "parallel":
                        result.update(value)
                    return {"values": result}
                except Exception as exc:
                    await self.snapshot(run_id, snapshot_node, "failed", state["values"], error=str(exc))
                    raise

            graph.add_node(node["key"], run_node)
        entry = dsl["edges"][0]["from"] if dsl["edges"] else primary_nodes[0]["key"]
        graph.add_edge(START, entry)
        for node in primary_nodes:
            key = node["key"]
            if node["type"] == "condition":
                graph.add_conditional_edges(
                    key,
                    lambda s, _k=key, _n=node: _n["then"] if s["values"][_k] else _n["else"],
                    {node["then"]: node["then"], node["else"]: node["else"]},
                )
            else:
                outgoing = [e["to"] for e in dsl["edges"] if e["from"] == key]
                if len(outgoing) > 1:
                    raise ValueError("多路边请使用 parallel 节点")
                graph.add_edge(key, outgoing[0] if outgoing else END)
        return graph.compile(checkpointer=self.checkpointer if checkpoint else None, name="ZhixingWorkflow")

    async def run(self, workflow, user, input_):
        dsl = parse_dsl(workflow["dsl"])
        missing = [key for key in dsl.get("input", []) if key not in input_]
        if missing:
            raise ValueError(f"缺少工作流入参：{missing}")
        run = await self.db.add(
            t.runs,
            {
                "workflow_id": workflow["id"],
                "user_id": user["id"],
                "input": input_,
                "dsl_snapshot": workflow["dsl"],
            },
        )
        return await self.drive(run, user, {"values": input_, "approved": False})

    async def drive(self, run, user, input_):
        try:
            dsl = parse_dsl(run["dsl_snapshot"])
            graph = await self.compile(dsl, user, run["id"], (run["workflow_id"],))
            config = {"configurable": {"thread_id": f"workflow:{run['id']}"}, "recursion_limit": 200}
            result = await graph.ainvoke(input_, config)
            paused = result.get("__interrupt__")
            values = result.get("values", {})
            output = {**values, "result": values.get(dsl.get("out", dsl["nodes"][-1]["key"]))}
            if paused:
                output["approval"] = paused[0].value
            return await self.db.change(
                t.runs,
                run["id"],
                {
                    "status": "waiting_approval" if paused else "succeeded",
                    "output": serial(output),
                    "finished_at": None if paused else t.now(),
                },
            )
        except Rejected as exc:
            return await self.db.change(
                t.runs, run["id"], {"status": "canceled", "error": str(exc), "finished_at": t.now()}
            )
        except Exception as exc:
            return await self.db.change(
                t.runs, run["id"], {"status": "failed", "error": str(exc), "finished_at": t.now()}
            )

    async def approve(self, run, user, decision):
        # An advisory lock coordinates concurrent approvals across API processes.
        from sqlalchemy import text

        async with self.db.engine.connect() as conn:
            acquired = await conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": -run["id"]})
            if not acquired:
                raise ValueError("该运行正在处理审批")
            try:
                latest = await self.db.get(t.runs, run["id"], t.runs.c.user_id == user["id"])
                if latest["status"] != "waiting_approval":
                    raise ValueError("工作流不在等待审批状态")
                return await self.drive(latest, user, Command(resume=decision))
            finally:
                await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": -run["id"]})
