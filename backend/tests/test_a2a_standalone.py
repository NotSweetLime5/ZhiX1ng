import httpx

from app import models as t
from app.a2a_server import app, service_user


async def test_legacy_a2a_port_has_isolated_anonymous_identity(rt, client):
    app.state.runtime = rt
    identity = await service_user(rt)
    app.state.a2a_user = identity
    assert identity["role"] == "service" and identity["status"] == 0
    transport = httpx.ASGITransport(app=app)
    body = {"jsonrpc": "2.0", "id": 1, "method": "message/ping"}
    async with httpx.AsyncClient(transport=transport, base_url="http://a2a:8082") as remote:
        card = (await remote.get("/.well-known/agent.json")).json()
        assert card["url"] == "http://a2a:8082/a2a" and "security" not in card
        assert (await remote.post("/a2a", json=body)).json()["result"]["status"] == "alive"
        invalid = await remote.post("/a2a", json=body, headers={"Authorization": "Bearer invalid"})
        assert invalid.status_code == 401
        response = await remote.post(
            "/a2a",
            json={
                **body,
                "method": "message/send",
                "params": {"message": {"parts": [{"type": "text", "text": "hello"}]}},
            },
        )
        assert response.json()["result"]["status"] == "completed"
        sessions = await rt.db.rows(t.sessions, t.sessions.c.user_id == identity["id"])
        assert sessions and identity["id"] != rt.test_user["id"]
        rt.cfg = rt.cfg.model_copy(update={"a2a_allow_anonymous": False})
        assert (await remote.post("/a2a", json=body)).status_code == 401
    # The administration API retains its login requirement.
    assert (await client.post("/a2a", json=body, headers={"Authorization": ""})).status_code == 401
