from mcp.server.fastmcp import FastMCP

server = FastMCP("Zhixing MCP test", host="127.0.0.1", port=18086, stateless_http=True, json_response=True)


@server.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    server.run(transport="streamable-http")
