"""Authenticated HTTP/SSE terminal client, independent of database access."""

import json


class TerminalClient:
    def __init__(self, http, agent_id=0):
        self.http, self.agent_id = http, agent_id
        self.session_id = None

    async def login(self, username, password):
        response = await self.http.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0 or not body.get("data", {}).get("access_token"):
            raise ValueError(body.get("message", "登录失败"))
        self.http.headers["Authorization"] = "Bearer " + body["data"]["access_token"]

    async def events(self, content):
        body = {"content": content, "agent_id": self.agent_id}
        if self.session_id:
            body["session_id"] = self.session_id
        async with self.http.stream("POST", "/api/v1/chat/stream", json=body) as response:
            response.raise_for_status()
            event, parts = "message", []
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    parts.append(line[5:].lstrip())
                elif not line and parts:
                    data = json.loads("\n".join(parts))
                    if event == "meta" and data.get("session_id"):
                        self.session_id = data["session_id"]
                    yield event, data
                    event, parts = "message", []
            if parts:
                yield event, json.loads("\n".join(parts))
