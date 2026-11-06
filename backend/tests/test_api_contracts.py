"""Public HTTP, health and A2A protocol contracts."""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from app import models as t
from app.main import app


def test_public_http_routes_are_available_in_fastapi():
    # Required API routes, including health, metrics and A2A.
    legacy = json.loads((Path(__file__).parent / "fixtures" / "api_routes.json").read_text())
    actual = {
        (method.upper(), re.sub(r"\{[^}]+\}", "{}", path))
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }
    missing = {(route["method"], route["path"]) for route in legacy} - actual
    assert not missing, f"Missing required HTTP routes: {sorted(missing)}"


async def test_python_health_metrics_and_agent_card(client):
    health = await client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["backend"] == "python"
    metrics = await client.get("/metrics")
    assert metrics.status_code == 200 and "zhixing_http_requests_total" in metrics.text
    card = await client.get("/.well-known/agent.json", headers={"Authorization": ""})
    assert card.status_code == 200
    assert card.json()["url"] == "http://test/a2a"
    assert card.json() == (await client.get("/.well-known/agent-card.json")).json()


async def test_a2a_ping_returns_health_status(client):
    response = await client.post("/a2a", json={"jsonrpc": "2.0", "id": "probe", "method": "message/ping"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "probe" and body["result"]["status"] == "alive"
    assert datetime.fromisoformat(body["result"]["time"]).tzinfo is not None


async def test_a2a_send_executes_python_agent(rt, client):
    response = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "chat",
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "error" not in body, body
    assert body["id"] == "chat" and body["result"]["status"]["state"] == "completed"
    assert body["result"]["artifacts"][0]["parts"][0]["text"] == "已完成"
    messages = await rt.db.rows(
        t.messages, t.messages.c.session_id == body["result"]["contextId"], ascending=True
    )
    assert [(row["role"], row["content"]) for row in messages] == [
        ("user", "hello"),
        ("assistant", "已完成"),
    ]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"jsonrpc": "1.0", "method": "message/ping"}, -32600),
        ({"jsonrpc": "2.0", "method": "missing"}, -32601),
        ({"jsonrpc": "2.0", "method": "message/send", "params": {}}, -32602),
    ],
)
async def test_a2a_protocol_errors(client, payload, code):
    response = await client.post("/a2a", json={"id": "error", **payload})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == code
