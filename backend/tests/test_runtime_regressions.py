"""SDK, workflow, CLI and runtime regression coverage."""

import hashlib
import json
import os
import re
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGenerationChunk

from app import models as t
from app.agents.workflow import condition, render
from app.core.security import passwords
from app.main import app
from app.services import catalog
from app.services.llm import CompatibleChatOpenAI
from app.terminal import TerminalClient
from conftest import ScriptedModel


async def test_compatible_sdk_preserves_reasoning_for_stream_and_tool_round_trip():
    from langchain_core.messages import HumanMessage

    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            frames = [
                {
                    "id": "test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "test-chat",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
                for delta in [
                    {"role": "assistant", "reasoning_content": "reason-1"},
                    {"reasoning_content": "reason-2"},
                    {"content": "answer"},
                ]
            ]
            payload = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n"
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=payload.encode()
            )
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "test-chat",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "answer",
                            "reasoning_content": "nonstream-reason",
                        },
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        model = CompatibleChatOpenAI(
            model="test-chat",
            api_key="test-key",
            base_url="http://test/v1",
            http_async_client=http,
            use_responses_api=False,
            max_retries=0,
        )
        chunks = [chunk async for chunk in model.astream([HumanMessage("hello")])]
        assert "".join(c.additional_kwargs.get("reasoning_content", "") for c in chunks) == "reason-1reason-2"
        result = await model.ainvoke([HumanMessage("hello")])
        assert result.additional_kwargs["reasoning_content"] == "nonstream-reason"
        await model.ainvoke([HumanMessage("hello"), result, HumanMessage("continue")])
        assert requests[-1]["messages"][1]["reasoning_content"] == "nonstream-reason"


def test_required_routes_are_implemented():
    snapshot = json.loads((Path(__file__).parent / "fixtures" / "api_routes.json").read_text())

    def normalize(path):
        return re.sub(r":[A-Za-z_][A-Za-z_0-9]*|\{[^}]+\}", "{}", path)

    actual = {
        (method.upper(), normalize(path))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    expected = {(row["method"], normalize(row["path"])) for row in snapshot}
    assert expected <= actual, expected - actual


async def test_default_model_uses_priority_without_requiring_default_flag(rt):
    provider_id = rt.test_model["provider_id"]
    choices = []
    for priority, default in [(20, False), (5, False), (80, True)]:
        choices.append(
            await rt.db.add(
                t.models,
                {
                    "provider_id": provider_id,
                    "type": "rerank",
                    "model_name": f"rank-{priority}",
                    "alias": "audit-" + uuid.uuid4().hex,
                    "priority": priority,
                    "is_default": default,
                },
            )
        )
    assert (await rt.gateway.resolve(kind="rerank", alias="missing")).model["id"] == choices[2]["id"]
    await rt.db.change(t.models, choices[2]["id"], {"status": 0})
    assert (await rt.gateway.resolve(kind="rerank", alias="missing")).model["id"] == choices[1]["id"]
    listing = await catalog.listing(t.models, (), rt, rt.test_user, type="rerank")
    assert [row["priority"] for row in listing] == [5, 20, 80]


async def test_terminal_client_authenticates_regular_user_and_streams_same_session(rt):
    suffix = uuid.uuid4().hex
    user = await rt.db.add(
        t.users,
        {
            "username": "cli_" + suffix,
            "email": suffix + "@test.local",
            "password_hash": passwords.hash("cli-test-password"),
            "role": "user",
        },
    )
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            terminal = TerminalClient(http)
            with pytest.raises(httpx.HTTPStatusError):
                await terminal.login(user["username"], "wrong-password")
            await terminal.login(user["username"], "cli-test-password")
            first = [event async for event in terminal.events("hello")]
            ident = terminal.session_id
            second = [event async for event in terminal.events("hello again")]
            assert terminal.session_id == ident
            assert first[-1][0] == second[-1][0] == "done"
            session = await rt.db.get(t.sessions, ident)
            assert session["user_id"] == user["id"] and session["message_count"] == 4
    finally:
        await rt.db.remove(t.users, user["id"])


async def test_terminal_client_does_not_bypass_login(rt):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        with pytest.raises(httpx.HTTPStatusError) as error:
            _ = [event async for event in TerminalClient(http).events("hello")]
        assert error.value.response.status_code == 401


async def test_session_list_keeps_pins_activity_order_and_hides_archived(rt, client):
    stamp = t.now()
    expected = []
    for index, (pinned, status, age) in enumerate(
        [(False, "active", 2), (True, "active", 30), (False, "active", 1), (False, "archived", 0)]
    ):
        ident = str(uuid.uuid4())
        await rt.db.add(
            t.sessions,
            {
                "id": ident,
                "user_id": rt.test_user["id"],
                "pinned": pinned,
                "status": status,
                "last_msg_at": stamp - timedelta(days=age),
                "title": str(index),
            },
        )
        expected.append(ident)
    result = (await client.get("/api/v1/sessions")).json()["data"]
    assert [row["id"] for row in result["list"]] == [expected[1], expected[2], expected[0]]
    assert result["total"] == 3


async def test_agent_keyword_matches_description_as_well_as_name(rt, client):
    await rt.db.change(
        t.agents, rt.test_expert["id"], {"name": "General expert", "description": "quantum research"}
    )
    result = (await client.get("/api/v1/agents", params={"keyword": "quantum"})).json()["data"]
    assert [row["id"] for row in result["list"]] == [rt.test_expert["id"]]


async def test_decision_trace_keeps_thought_arguments_and_answer(rt, client, monkeypatch):
    class ThoughtfulModel(ScriptedModel):
        async def _astream(self, messages, **kwargs):
            if not isinstance(messages[-1], ToolMessage):
                yield ChatGenerationChunk(message=AIMessageChunk(content="先计算。"))
            async for chunk in super()._astream(messages, **kwargs):
                yield chunk

    monkeypatch.setattr(rt.gateway, "chat", lambda *args, **kw: ThoughtfulModel())
    response = await client.post(
        "/api/v1/chat/stream", json={"agent_id": rt.test_expert["id"], "content": "计算2+3"}
    )
    assert "event: done" in response.text
    sessions = await rt.db.rows(t.sessions, t.sessions.c.user_id == rt.test_user["id"])
    messages = await rt.db.rows(t.messages, t.messages.c.session_id == sessions[0]["id"], ascending=True)
    trace = messages[-1]["metadata"]["agent_trace"]
    assert [step["type"] for step in trace] == ["thought", "action", "answer"]
    assert trace[1]["args"] == {"expression": "2+3"}
    assert "5" in trace[-1]["result"]


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("", True),
        ("true", True),
        ("!false && count > 2", True),
        ('text == "true && false"', True),
        ("flag != true || count < 1", False),
        ("nil == value", True),
        ("count in [1, 2, 3]", True),
        ("features.enabled && !disabled", True),
    ],
)
def test_condition_preserves_literals_and_go_boolean_operators(expression, expected):
    assert (
        condition(
            expression,
            {
                "count": 3,
                "flag": True,
                "text": "true && false",
                "value": None,
                "features": {"enabled": True},
                "disabled": False,
            },
        )
        is expected
    )


async def test_empty_condition_can_follow_linear_edge(rt):
    dsl = """name: empty-condition
nodes:
  - {key: pass, type: condition}
  - {key: calc, type: tool, tool_code: calculator, args: {expression: '2+3'}}
edges: [pass, calc]
"""
    workflow = await rt.db.add(
        t.workflows, {"name": "empty-condition", "creator_id": rt.test_user["id"], "dsl": dsl}
    )
    run = await rt.workflow.run(workflow, rt.test_user, {})
    assert run["status"] == "succeeded" and run["output"]["result"] == "5"


@pytest.mark.parametrize("value", [True, False])
def test_yaml_boolean_condition_literal_is_accepted(value):
    assert condition(value, {}) is value


async def test_go_yaml_yes_no_node_names_remain_strings(rt):
    dsl = """name: workflow-yaml-keys
nodes:
  - {key: check, type: condition, expr: true, then: yes, else: no}
  - {key: yes, type: tool, tool_code: calculator, args: {expression: '2+3'}}
  - {key: no, type: tool, tool_code: calculator, args: {expression: '2+4'}}
edges: [{from: check, to: yes}]
out: yes
"""
    workflow = await rt.db.add(
        t.workflows, {"name": "workflow-yaml-keys", "creator_id": rt.test_user["id"], "dsl": dsl}
    )
    run = await rt.workflow.run(workflow, rt.test_user, {})
    assert run["status"] == "succeeded" and run["output"]["result"] == "5"


async def test_parallel_branches_can_run_nested_parallel_and_subflow(rt):
    child = await rt.db.add(
        t.workflows,
        {
            "name": "child",
            "creator_id": rt.test_user["id"],
            "dsl": "name: child\nnodes: [{key: calc, type: tool, tool_code: calculator, args: {expression: '2+3'}}]",
        },
    )
    dsl = f"""name: nested-parallel
nodes:
  - {{key: top, type: parallel, branches: [nested, child]}}
  - {{key: nested, type: parallel, branches: [calc]}}
  - {{key: calc, type: tool, tool_code: calculator, args: {{expression: '3*4'}}}}
  - {{key: child, type: subflow, workflow: {child["id"]}}}
edges: [top]
out: top
"""
    workflow = await rt.db.add(t.workflows, {"name": "nested", "creator_id": rt.test_user["id"], "dsl": dsl})
    run = await rt.workflow.run(workflow, rt.test_user, {})
    assert run["status"] == "succeeded", run["error"]
    assert run["output"]["result"] == {"nested": {"calc": "12"}, "child": {"calc": "5"}}


def test_unresolved_template_is_preserved_like_go_renderer():
    assert render("Hello {{name}} / {{missing}}", {"name": "world"}) == "Hello world / {{missing}}"


async def test_file_save_returns_path_and_utf8_byte_count(rt):
    result = await rt.tools.call(
        "file_ops",
        {"operation": "save", "path": "result.txt", "content": "你好"},
        rt.test_user,
        approved=True,
    )
    assert json.loads(result) == {"saved": "result.txt", "bytes": 6}
    assert (
        await rt.tools.call(
            "file_ops", {"operation": "read", "path": "result.txt"}, rt.test_user, approved=True
        )
        == "你好"
    )


@pytest.mark.skipif(os.getenv("ZHIXING_TEST_SANDBOX") != "1", reason="Enable live Docker sandbox checks")
async def test_code_execution_preserves_separate_streams_and_hash_only_audit(rt):
    code = "import sys\nprint('audit-out')\nprint('audit-err', file=sys.stderr)\nsys.exit(7)"
    result = json.loads(
        await rt.tools.call("code_exec", {"language": "python", "code": code}, rt.test_user, approved=True)
    )
    assert result["exit_code"] == 7 and result["stdout"].strip() == "audit-out"
    assert result["stderr"].strip() == "audit-err" and result["duration"] >= 0
    rows = await rt.db.rows(t.sandbox_executions, t.sandbox_executions.c.user_id == rt.test_user["id"])
    assert len(rows) == 1 and rows[0]["code_hash"] == hashlib.sha256(code.encode()).hexdigest()
    assert rows[0]["exit_code"] == 7 and rows[0]["stdout_head"].strip() == "audit-out"
    assert code not in json.dumps(rows[0], default=str) and "code" not in rows[0]
