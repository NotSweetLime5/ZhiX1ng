"""Bundled real MCP service, using the same search and HTTP policy as the API.

Bind loopback by default. This service exposes only read-only public tools; it
never exposes database queries, user files, credentials, or sandbox execution.
"""

from mcp.server.fastmcp import FastMCP

from app.core.config import settings
from app.services.tools import Tools


def create_server(host="127.0.0.1", port=None):
    cfg = settings()
    tools = Tools(None, None, cfg)
    server = FastMCP(
        "Zhixing local tools", host=host, port=port or cfg.mcp_port, stateless_http=True, json_response=True
    )

    @server.tool()
    async def calculator(expression: str) -> str:
        """Calculate a mathematical expression."""
        return await tools.invoke("calculator", {"expression": expression}, {})

    @server.tool()
    async def current_time(timezone: str = "Asia/Shanghai") -> str:
        """Return the current time in an IANA timezone."""
        return await tools.invoke("datetime", {"operation": "now", "tz": timezone}, {})

    @server.tool()
    async def web_search(query: str, count: int = 5) -> list[dict]:
        """Search the live internet through the local SearXNG service."""
        return await tools.invoke("web_search", {"query": query, "count": count}, {})

    @server.tool()
    async def fetch_page(url: str) -> dict:
        """Read a public page whose domain is permitted by NX_ALLOWED_HTTP_HOSTS."""
        return await tools.invoke("http_client", {"url": url}, {})

    return server
